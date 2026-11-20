"""Genera las noticias de tedepad.com (ES/EN) y publica la web en _site/.

Las páginas que no son noticias (portada, productos, quiénes somos, contacto, textos legales…) son archivos fijos del
repositorio y se copian tal cual. Las noticias salen de content/noticias/{es,en}/*.md (las escribe el panel /admin/)
con las plantillas de plantillas/ (sacadas de la propia web). Todo lo que llega del panel se trata como no fiable:
ver las defensas en el README, «Panel de noticias».

    python build.py          → genera _site/
"""
import base64
import hashlib
import html
import json
import os
import re
import shutil
import sys
from datetime import date
from html.parser import HTMLParser

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, '_site')
SITE = 'https://tedepad.com'
MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto',
         'septiembre', 'octubre', 'noviembre', 'diciembre']
esc = html.escape


# ------------------------------------------------------------------ lectura de contenido
def read_doc(path):
    """Devuelve (metadatos, cuerpo) de un archivo con cabecera '---' tipo YAML sencillo."""
    text = clean_text(open(path, encoding='utf-8', errors='replace').read().replace('\r\n', '\n'))
    meta, body = {}, text
    m = re.match(r'---\n(.*?)\n---\n?', text, re.S)
    if m:
        body = text[m.end():]
        lines = m.group(1).split('\n')
        i = 0
        while i < len(lines):
            line = lines[i]
            i += 1
            if ':' not in line or line.lstrip().startswith('#') or line[:1] in ' \t':
                continue
            k, v = line.split(':', 1)
            v = v.strip()
            if v == '' and i < len(lines) and lines[i].lstrip().startswith('- '):   # lista de elementos clave: valor
                # formato estricto: «- clave: valor» y «  clave: valor» con la sangría del primer elemento
                items, ok = [], True
                ind = len(lines[i]) - len(lines[i].lstrip())
                while i < len(lines) and (lines[i][:1] in ' \t-' and lines[i].strip()):
                    raw = lines[i]
                    i += 1
                    lead = len(raw) - len(raw.lstrip())
                    s_ = raw.strip()
                    if s_ in ('-', '- ') or (s_.startswith('- ') and lead != ind):
                        ok = False
                        items.append({'__mal_formado': '1'})   # el elemento entero se descarta
                        continue
                    if s_.startswith('- '):
                        items.append({})
                        s_ = s_[2:].strip()
                    elif lead != ind + 2 or not items or ':' not in s_:
                        ok = False
                        if items:
                            items[-1]['__mal_formado'] = '1'
                        continue
                    kk, vv = s_.split(':', 1)
                    kk = kk.strip()
                    if kk in items[-1]:
                        ok = False                      # clave repetida
                    items[-1][kk] = clean_text(str(yaml_scalar(vv.strip())))
                if not ok:
                    warn(f'{os.path.basename(path)}: «{k.strip()}» con formato no válido; se ignoran sus elementos dudosos')
                if k.strip() not in meta:               # si la clave se repite, vale la primera
                    meta[k.strip()] = items[:MAX_LINKS]
                continue
            if v in ('|', '|-', '>', '>-'):          # bloque multilínea de YAML
                block = []
                while i < len(lines) and (lines[i][:1] in ' \t' or not lines[i].strip()):
                    block.append(lines[i].strip())
                    i += 1
                v = ('\n' if v[0] == '|' else ' ').join(block).strip()
            else:
                v = yaml_scalar(v)
            meta[k.strip()] = clean_text(str(v))
    return meta, body


YAML_ESC = {'0': chr(0), 'a': chr(7), 'b': chr(8), 't': chr(9), 'n': chr(10), 'v': chr(11), 'f': chr(12),
            'r': chr(13), 'e': chr(27), ' ': ' ', '"': '"', '/': '/', '\\': '\\', 'N': chr(0x85),
            '_': chr(0xA0), 'L': chr(0x2028), 'P': chr(0x2029), '\t': chr(9)}


def yaml_dq(inner):
    """Escapes de las cadenas YAML entre comillas dobles (los que escribe el panel: \\_ espacio duro, \\N, \\x…)."""
    def rep(m):
        e = m.group(1)
        if e[0] in 'xuU':
            try:
                c = int(e[1:], 16)
                return '' if 0xD800 <= c <= 0xDFFF or c > 0x10FFFF else chr(c)
            except ValueError:
                return ''
        return YAML_ESC.get(e, '')
    return re.sub(r'\\(x[0-9a-fA-F]{2}|u[0-9a-fA-F]{4}|U[0-9a-fA-F]{8}|[\s\S])', rep, inner)


def yaml_scalar(v):
    """Valor de una línea YAML: entre comillas dobles (con sus escapes), simples o sin comillas."""
    if len(v) >= 2 and v[0] == v[-1] == '"':
        return yaml_dq(v[1:-1])
    if len(v) >= 2 and v[0] == v[-1] == "'":
        return v[1:-1].replace("''", "'")
    return v


def clean_text(t):
    """Quita caracteres de control y sustitutos Unicode sueltos (romperían el HTML, el RSS o la compilación)."""
    return re.sub('[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ud800-\udfff\ufdd0-\ufdef\ufffe\uffff]', '', t)


PROBLEMS = []          # avisos de contenido: si hay alguno, la publicación se detiene (y GitHub avisa por correo)


def warn(msg):
    print('AVISO: ' + msg)
    PROBLEMS.append(msg)


# Lo que llega del panel de noticias se trata como no fiable (ver README, «Panel de noticias»)
SLUG_OK = re.compile(r'[a-z0-9]+(?:-[a-z0-9]+)*')
IMG_OK = re.compile(r'/img/noticias/[A-Za-z0-9._-]+\.(?:webp|jpe?g|png|gif|avif)')
IMG_EXT = ('.webp', '.jpg', '.jpeg', '.png', '.gif', '.avif')
MAX_NEWS_BYTES = 200_000                       # una noticia normal ocupa 2–10 KB
MAX_LINKS = 12                                 # «Fuentes y enlaces» por noticia

# Noticias publicadas antes del panel (22 = 11 × ES/EN, 19/11/2026): se publican con su HTML original y en sus
# direcciones de siempre, pero SOLO mientras su texto no cambie (huella SHA-256). Si se edita, se rige como nueva.
LEGACY_NEWS = {
    'es/2024-10-21-el-anisakis-un-problema-creciente-vinculado-a-la-pesca-el-consumo-y-el-cambio-climatico.md':
        'd360393580ef9b81268cb49424791d6b2f3b1d14d261cd252de2d2ac6221c0ab',
    'es/2024-11-04-el-anisakis-en-nuestros-platos-como-reducir-riesgos-y-proteger-los-oceanos.md':
        'c93853ce2bf128aca74e876da96b0cbc38df7e0d9e22595ebd732ba5655e6e41',
    'es/2024-11-18-expertos-debaten-en-mercamadrid-sobre-el-control-del-anisakis-en-la-distribucion-de-pescado.md':
        '347ed085ec69dcebdc9d6d353f59d53e74abdccfac180a3f01f3cb0bdfbe255c',
    'es/2024-12-09-el-anisakis-podria-estar-relacionado-con-el-cancer-de-colon-segun-medicos-espanoles.md':
        '76be458d9cf0e50f5b24c3a8b973ec6c353b70fd93af621551d615e0022b64d1',
    'es/2024-12-23-espana-marca-un-hito-en-la-lucha-contra-el-anisakis-con-un-dispositivo-pionero-validado-por-el-csic.md':
        '8232a6d3558a37e9208d29fe7bf02b9639d8a4fa0861244d9f72cade561a4fa4',
    'es/2025-01-13-retiran-del-mercado-espanol-huevas-de-merluza-procedentes-de-marruecos-por-contaminacion-con-anisakis.md':
        'd1bdc7ff92b61b49fc3fad08980cea7fa28dc96f6809c5ef3d3c46f6b7558a7d',
    'es/2025-04-10-detectan-alergenos-en-parasitos-de-peces-comerciales-claves-sobre-su-expresion-genetica-y-riesgos-al-consumir-pescado-crudo.md':
        '4322e6db0a7b157468d1bec21f9439a310f5ea0fba60976ae63ecdb0bf2aa5c5',
    'es/2025-04-14-como-saber-si-tengo-anisakis-causas-sintomas-y-tratamiento.md':
        'bac02947d8d8aee08ed9e108a6ed0f4eee2e07b7ac6c6f09acb131fe06990184',
    'es/2025-04-16-seguridad-alimentaria-en-comedores-escolares-que-podemos-aprender-del-caso-de-lleida.md':
        'feead9ffa0dcd8fff0c8d1cabd1f3bafd6c2ae63b5d430d76e9f30bb7b186213',
    'es/2025-04-21-cinco-especies-de-pescado-con-mas-riesgo-de-anisakis.md':
        'aec77f2d9d031b870483aed23e2bcacb8ae3a328e43bf14f173e168b620f2cd0',
    'es/2025-04-25-todo-lo-que-debes-saber-sobre-el-anisakis-segun-la-doctora-lourdes-perez-gonzalez.md':
        '7c9bd8cd39eb27ad5e53e188372227707b222a28bf00990ba5729294b4aac452',
    'en/2024-10-21-anisakis-a-growing-problem-linked-to-fisheries-consumption-and-climate-change.md':
        'cd2bfdab48fd9703aab7e5f34a13e8c486bb14b4e65ad4068212d7e420828a5f',
    'en/2024-11-04-anisakis-on-our-plates-how-to-reduce-risks-and-protect-the-oceans.md':
        'c32288e898d4d2812c47cedaf723e4475fefb5b914dafe9634dcb64a4aa62a56',
    'en/2024-11-18-experts-discuss-anisakis-control-in-fish-distribution-at-mercamadrid.md':
        '7c8f2a4593414039a338c82c853cd6c6ac70e258975dda7d5097b7775be4d762',
    'en/2024-12-09-anisakis-may-be-linked-to-colon-cancer-spanish-doctors-say.md':
        'ec9916e0e5f4d297ec084ac694a140bf5768c7536ac03dbbc511ed00f2a8e9da',
    'en/2024-12-23-spain-marks-a-milestone-in-the-fight-against-anisakis-with-a-pioneering-device-validated-by-csic.md':
        'e8bd05869067dee8f42591ff37727a6f033973cfc7219f6dbf9534c81a0d7d74',
    'en/2025-01-13-recall-of-this-fish-from-the-market-due-to-anisakis-contamination.md':
        'b802c311e2de4a51f963b2efed603253a81d72f8fef0629f6ca0fdb0ed16c2c2',
    'en/2025-04-10-allergens-detected-in-commercial-fish-parasites-clues-to-their-genetic-expression-and-risks-of-consuming-raw-fish.md':
        '17e734f9ea460dd60ea5f1e1684523ef087200daf10b9f60deaefa25c6b807d8',
    'en/2025-04-14-how-do-i-know-if-i-have-anisakis-causes-symptoms-and-treatment.md':
        '4fa3a462a133b42110d96d8f47d7d1f75ec0cd7e8ecf27fb9076fe56832cd4fa',
    'en/2025-04-16-food-safety-in-school-canteens-what-can-we-learn-from-the-case-of-lleida.md':
        'd3efa52d0c58f74e3a52e4b374c935e7135756e82ed6385308027b67bec0a3b4',
    'en/2025-04-21-these-are-the-five-fish-species-with-the-highest-risk-of-containing-anisakis.md':
        '1628aaacdeb196d2a0f8621da70f38c3bee0522f191ad3cde9633877b10259b2',
    'en/2025-04-25-everything-you-need-to-know-about-anisakis-according-to-dr-lourdes-perez-gonzalez.md':
        '62ab49b7cbc112900b1097f1161dcbed824b5eb479a219ae9b27e52fb07c6b30',
}

# Comprobación de las direcciones de «Fuentes y enlaces»
LINK_TYPES = {'fuente': ('Fuente', 'Fuentes'), 'video': ('Vídeo relacionado', 'Vídeos relacionados'),
              'enlace': ('Enlace relacionado', 'Enlaces relacionados')}
SHORTENERS = {'bit.ly', 'bitly.com', 't.co', 'tinyurl.com', 'goo.gl', 'ow.ly', 'is.gd', 'buff.ly', 'rebrand.ly',
              'cutt.ly', 'shorturl.at', 'shorturl.fm', 'tiny.cc', 'rb.gy', 's.id', 'v.gd', 'lnkd.in', 'trib.al',
              'dlvr.it', 'shorte.st', 'adf.ly', 'bl.ink', 'short.io', 'qrco.de', 'linktr.ee', 'x.gd', 'urlz.fr'}
# Orientativo: un servidor puede servir un ejecutable en cualquier ruta; esto solo evita los enlaces evidentes.
RISKY_EXT = ('.exe', '.msi', '.bat', '.cmd', '.scr', '.ps1', '.vbs', '.js', '.jar', '.apk', '.dmg',
             '.pkg', '.app', '.deb', '.rpm', '.sh', '.zip', '.rar', '.7z', '.gz', '.tgz', '.iso', '.img',
             '.svg', '.hta', '.lnk', '.reg', '.docm', '.xlsm', '.pptm')


def check_external_url(url):
    """Devuelve (url, '') si la dirección es aceptable o (None, motivo) si no. Solo https a un dominio público."""
    from urllib.parse import urlsplit
    u = (url or '').strip()
    if not u or len(u) > 500:
        return None, 'vacía o demasiado larga'
    if not re.fullmatch(r'https://[!#$%&()*+,\-./0-9:;=?@A-Z_a-z~\[\]]+', u):
        return None, 'debe empezar por https:// y no llevar espacios ni caracteres raros'
    try:
        p = urlsplit(u)
        host = (p.hostname or '').lower().rstrip('.')
        port = p.port
    except ValueError:
        return None, 'dirección mal formada'
    if '@' in p.netloc:
        return None, 'lleva usuario o contraseña'
    if port not in (None, 443):
        return None, 'usa un puerto no estándar'
    if not re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}', host):
        return None, 'el servidor debe ser un dominio (no una IP ni un nombre interno)'
    if 'xn--' in host:
        return None, 'dominio con caracteres internacionales (posible imitación de otro)'
    if host.endswith(('.local', '.internal', '.localhost', '.test', '.example', '.invalid')):
        return None, 'dominio interno o de pruebas'
    if host in SHORTENERS or any(host.endswith('.' + s) for s in SHORTENERS):
        return None, 'acortador de enlaces (oculta el destino real)'
    if host.endswith(WILDCARD_DNS) or host in {d.lstrip('.') for d in WILDCARD_DNS} or re.search(r'(?:^|\.)\d{1,3}(?:[.-]\d{1,3}){3}\.', host):
        return None, 'dominio que apunta a una IP cualquiera (nip.io, sslip.io…)'
    from urllib.parse import unquote, parse_qsl
    path = unquote(unquote(p.path)).lower().rstrip('/;. ')
    if path.endswith(RISKY_EXT) or re.search(r'\.(?:exe|msi|apk|dmg|zip|rar|7z|iso|scr|bat|jar)[;.]', path):
        return None, 'apunta a un archivo descargable o ejecutable'
    for _, v in parse_qsl(p.query + '&' + p.fragment, keep_blank_values=True):
        v = unquote(unquote(v)).lower().strip()
        if re.search(r'(?:https?:|^//|^www\.)', v):
            return None, 'lleva dentro otra dirección (redirección): enlazar directamente al destino'
        if v.rstrip('/;. ').endswith(RISKY_EXT):
            return None, 'apunta a un archivo descargable o ejecutable'
    return u, ''


# Dominios que resuelven a cualquier IP que se ponga en el nombre (sirven para esconder servidores propios)
WILDCARD_DNS = ('.nip.io', '.sslip.io', '.xip.io', '.lvh.me', '.localtest.me', '.traefik.me', '.local.gd')


# Texto de las noticias nuevas: sin enlaces ni imágenes de ningún tipo (van en «Fuentes y enlaces»)
# Las mismas reglas se copian al panel con tools/reglas_panel.py (que la publicación comprueba).
BODY_RULES = [
    r'\]\s*[(\[]',                                   # sintaxis de enlace o imagen [texto](…) / [texto][…]
    r'\[[^\]\n]{0,300}\]:\s*\S',                     # definición de enlace [1]: … (acotado: evita esperas)
    r'\[\s*\.\s*\]|\(\s*\.\s*\)',                    # dominios «desactivados» como evil[.]com
    r'<\s*/?\s*(?:a|img|iframe|script|object|embed)\b',   # etiquetas HTML de enlace, imagen o contenido externo
    r'\b(?:https?|ftp|mailto|javascript|data|file|hxxps?)\s*:',   # direcciones con protocolo
    r'\bwww\s*\.',                                   # www.…
    r'\b[a-z0-9-]{1,63}\.(?:com|es|org|net|eu|info|io|ly|me|gal|cat|co|uk|de|fr|it|pt|gov|edu|tv|biz|app|dev|ru|su|cn'
    r'|xyz|top|site|online|shop|store|club|link|click|live|pro|cc|ws|us|ca|mx|ar|cl|br|nl|be|ch|at|pl|se|no|dk|fi|ie'
    r'|ro|gr|tr|ua|jp|kr|in|au|nz|za|ai|to|gg|zip|mov|vip|win|bid|loc|lat|icu|cfd|sbs|rest|fun|space|website|tech)\b',   # dominio suelto
]
BODY_FORBIDDEN = re.compile('|'.join(BODY_RULES), re.I | re.A)


def body_problem(body):
    """Motivo por el que el texto de una noticia nueva no se puede publicar, o '' si está bien.
    Se normaliza antes (NFKC) para que caracteres «disfrazados» (p. ej. los dos puntos de ancho completo) no se cuelen."""
    import unicodedata
    m = BODY_FORBIDDEN.search(unicodedata.normalize('NFKC', body or ''))
    return f'el texto contiene un enlace o dirección web («{m.group(0).strip()}»): los enlaces van en «Fuentes y enlaces»' if m else ''


def render_links(items, fname):
    """Bloque «Fuente: …» / «Vídeo relacionado: …» al final de la noticia, con direcciones ya comprobadas."""
    groups = {k: [] for k in LINK_TYPES}
    for it in items if isinstance(items, list) else []:
        extra = set(it) - {'tipo', 'nombre', 'url'}
        if extra:
            warn(f'{fname}: enlace descartado (campos no permitidos: {", ".join(sorted(extra))})')
            continue
        kind = it.get('tipo', 'fuente') if it.get('tipo') in LINK_TYPES else 'fuente'
        name = re.sub(r'\s+', ' ', it.get('nombre', '')).strip()[:80]
        url, why = check_external_url(it.get('url', ''))
        if url and body_problem(name):
            url, why = None, 'el nombre visible no puede ser otra dirección web'
        if not url:
            warn(f'{fname}: enlace descartado ({why}): {it.get("url", "")!r}')
            continue
        name = name or (urlsplit_host(url))
        groups[kind].append(f'<a href="{esc(url)}" rel="nofollow noopener noreferrer">{esc(name)}</a>')
    out = []
    for kind, (one, many) in LINK_TYPES.items():
        if groups[kind]:
            out.append(f'<p class="fuentes">{one if len(groups[kind]) == 1 else many}: {", ".join(groups[kind])}</p>')
    return '\n'.join(out)


def urlsplit_host(url):
    from urllib.parse import urlsplit
    return (urlsplit(url).hostname or url).removeprefix('www.')


def safe_url(url):
    """Solo enlaces web (http/https), de correo, o rutas internas de la web. Cualquier otra cosa → None."""
    u = url.strip()
    if re.match(r'(?i)https?://[^\s<>"]+$', u) or re.match(r'(?i)mailto:[^\s<>"]+$', u):
        return u
    if re.match(r'/(?![/\\])[^\s<>"\\]*$', u) or re.match(r'#[\w-]*$', u):
        return u
    return None


def fecha(d):
    return f'{d.day} de {MESES[d.month - 1]} de {d.year}'


def plain(h):
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', h))).strip()


# ------------------------------------------------------------------ Markdown (subconjunto)
def md_inline(t, links=True):
    """links=False: los enlaces se publican como texto (noticias nuevas: los enlaces van en «Fuentes y enlaces»)."""
    t = esc(t.replace('\x00', ''), quote=False)
    hold = []                                  # etiquetas ya generadas: no se vuelven a procesar

    def keep(tag):
        hold.append(tag)
        return f'\x00{len(hold) - 1}\x00'

    if not links:                               # noticias nuevas: el editor escapa caracteres (\* \_ \[ …): se muestran tal cual
        t = re.sub(r'\\(&lt;|&gt;|&amp;|[\\`*_{}\[\]()#+\-.!|~])', lambda m: keep(m.group(1)), t)

    # Las noticias solo llevan una imagen (la principal, en la cabecera): las imágenes dentro del texto se quitan
    t = re.sub(r'!\[([^\[\]\x00]*)\]\(([^()\s\x00]+)\)', '', t)

    def link(m):
        url = None
        if links:                               # solo noticias antiguas sin cambios: internas o https comprobadas
            raw = html.unescape(m.group(2))
            url = safe_url(raw) if raw.startswith(('/', '#')) else check_external_url(raw)[0]
        if not url:
            return m.group(1)
        ext = re.match(r'https?://', url) and not re.match(r'https?://(www\.)?tedepad\.com(?=[/:?#]|$)', url)
        return keep(f'<a href="{esc(url)}"' + (' rel="noopener"' if ext else '') + '>') + m.group(1) + keep('</a>')
    t = re.sub(r'\[([^\[\]\x00]+)\]\(([^()\s\x00]+)\)', link, t)
    t = re.sub(r'\*\*((?:[^*\n]|\*(?!\*))+?)\*\*', r'<strong>\1</strong>', t)
    t = re.sub(r'(?<![\w*])\*(?![\s*])([^*\n]+?)(?<!\s)\*(?![\w*])', r'<em>\1</em>', t)
    t = t.replace('  \n', '<br>\n')
    return re.sub(r'\x00(\d+)\x00', lambda m: hold[int(m.group(1))], t)


def markdown(src, links=True):
    out = []
    il = lambda x: md_inline(x, links)
    src = re.sub(r'(?m)^(#{2,4} .*)$', r'\n\1\n', src)      # cada subtítulo, en su propio bloque
    for block in re.split(r'\n\s*\n', src.strip()):
        lines = block.split('\n')
        first = lines[0]
        if re.match(r'#{2,4} ', first):
            n = len(first) - len(first.lstrip('#'))
            out.append(f'<h{n}>{il(first[n:].strip())}</h{n}>')
        elif all(re.match(r'[-*] ', l) for l in lines):
            out.append('<ul>' + ''.join(f'<li>{il(l[2:].strip())}</li>' for l in lines) + '</ul>')
        elif all(re.match(r'\d+\. ', l) for l in lines):
            out.append('<ol>' + ''.join(f'<li>{il(l.split(". ", 1)[1].strip())}</li>' for l in lines) + '</ol>')
        elif all(l.startswith('>') for l in lines):
            out.append('<blockquote><p>' + il('\n'.join(l[1:].lstrip() for l in lines)) + '</p></blockquote>')
        elif re.fullmatch(r'!\[[^\]]*\]\([^)\s]+\)', block.strip()):
            continue                                # imagen suelta en el texto: no se publica (ver md_inline)
        else:
            out.append('<p>' + il(block) + '</p>')
    return '\n'.join(out)




# ====================================================================== parte propia de tedepad.com
# Noticias en dos idiomas (es obligatorio, en opcional) con plantillas sacadas de la web publicada (plantillas/).

LINK_LABELS = {
    'es': {'fuente': ('Fuente', 'Fuentes'), 'video': ('Vídeo relacionado', 'Vídeos relacionados'),
           'enlace': ('Enlace relacionado', 'Enlaces relacionados')},
    'en': {'fuente': ('Source', 'Sources'), 'video': ('Related video', 'Related videos'),
           'enlace': ('Related link', 'Related links')},
}
LEGACY_IMG = re.compile(r'/img/n-[A-Za-z0-9._-]+\.(?:webp|jpe?g|png)')     # imágenes de las 22 noticias antiguas

T = {
    'es': dict(home='/', who='/quienes-somos/', products='/productos/', support='/soporte/', news='/noticias/',
               contact='/contacto/', n_who='Quiénes somos', n_products='Productos', n_support='Soporte',
               n_news='Noticias', n_contact='Contacto', more='Leer más', back='Volver a Noticias',
               months=['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre',
                       'octubre', 'noviembre', 'diciembre']),
    'en': dict(home='/en/', who='/en/who-we-are/', products='/en/products/', support='/en/support/', news='/en/news/',
               contact='/en/contact/', n_who='Who we are', n_products='Products', n_support='Support',
               n_news='News', n_contact='Contact', more='Read more', back='Back to News',
               months=['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September',
                       'October', 'November', 'December']),
}
ONLY_ES = 'Only available in Spanish'


def tpl(name):
    return open(os.path.join(ROOT, 'plantillas', name), encoding='utf-8').read()


def date_str(d, lang):
    m = T[lang]['months'][d.month - 1]
    return f'{d.day} de {m} de {d.year}' if lang == 'es' else f'{m} {d.day}, {d.year}'


def page(lang, path, title, desc, body, alt_path, alt_real=True):
    """Misma estructura que las páginas de la web (cabecera, menú, idiomas, pie y formulario)."""
    t = T[lang]
    es_p, en_p = (path, alt_path) if lang == 'es' else (alt_path, path)
    cur = ' aria-current="page"'
    nav = ''.join(f'<a href="{t[k]}"{cur if t[k] == path else ""}>{t["n_" + k]}</a>'
                  for k in ('who', 'products', 'support', 'news', 'contact'))
    full_title = title if 'TEDEPAD' in title.upper() else f'{title} · TEDEPAD®'
    # hreflang solo hacia versiones reales: una noticia sin inglés no anuncia la lista inglesa como su traducción
    alternates = ''.join(f'<link rel="alternate" hreflang="{l}" href="{SITE}{p}">' + chr(10)
                         for l, p in (('es', es_p), ('en', en_p)) if alt_real or l == lang)
    foot = tpl(f'pie-{lang}.html').replace('© 2026 TEDEPAD', f'© {date.today().year} TEDEPAD')
    return f'''<!DOCTYPE html>
<html lang="{lang}">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(full_title)}</title>
<meta name="description" content="{esc(desc)}">
<link rel="canonical" href="{SITE}{path}">
{alternates}<link rel="alternate" hreflang="x-default" href="{SITE}{es_p}">
<meta property="og:type" content="website"><meta property="og:title" content="{esc(full_title)}"><meta property="og:description" content="{esc(desc)}">
<meta property="og:url" content="{SITE}{path}"><meta property="og:image" content="{SITE}/img/og.png">
<link rel="icon" type="image/png" href="/img/favicon.png">
<style>{tpl('estilo.css')}</style>
</head>
<body>
<header class="site-top"><div class="wrap site-top-in">
  <a class="brand" href="{t['home']}" aria-label="TEDEPAD®"><img src="/img/logo.png" alt="TEDEPAD®" width="180" height="45"></a>
  <input type="checkbox" id="menu" class="menu-tg" aria-label="Menú"><label for="menu" class="menu-btn" aria-hidden="true"><span></span></label>
  <nav class="nav">{nav}<span class="lang"><a href="{es_p}"{' class="on"' if lang == 'es' else ''} hreflang="es" lang="es">ES</a><a href="{en_p}"{' class="on"' if lang == 'en' else ''} hreflang="en" lang="en">EN</a></span></nav>
</div></header>
<main>
{body}
</main>
{foot}'''


def load_news():
    """Lee content/noticias/{es,en}/*.md y devuelve la lista de noticias (cada una con su versión es y, si la hay, en)."""
    base = os.path.join(ROOT, 'content', 'noticias')
    found = {'es': {}, 'en': {}}
    for lang in ('es', 'en'):
        d = os.path.join(base, lang)
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            p = os.path.join(d, f)
            if not f.endswith('.md'):
                warn(f'{lang}/{f}: archivo no permitido en las noticias')
                continue
            if not os.path.isfile(p) or os.path.islink(p):
                warn(f'{lang}/{f} se omite (no es un archivo normal)')
                continue
            if os.path.getsize(p) > MAX_NEWS_BYTES:
                warn(f'{lang}/{f} se omite (más de {MAX_NEWS_BYTES // 1000} KB)')
                continue
            meta, body = read_doc(p)
            meta = {k: (v if (k == 'enlaces') == isinstance(v, list) else ([] if k == 'enlaces' else ''))
                    for k, v in meta.items()}
            if meta.get('draft', '').lower() in ('true', 'si', 'sí', 'yes'):
                continue
            stem = f[:-3]
            m = re.match(r'(\d{4}-\d{2}-\d{2})-(.+)$', stem)
            if not m or not SLUG_OK.fullmatch(m.group(2)) or len(m.group(2)) > 200:
                warn(f'{lang}/{f} se omite (nombre de archivo no válido)')
                continue
            try:
                dt = date.fromisoformat(str(meta.get('date', m.group(1)))[:10])
            except ValueError:
                warn(f'{lang}/{f} se omite (fecha no válida: {meta.get("date")!r})')
                continue
            key = meta.get('translationKey', '') or (stem if lang == 'es' else '')
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}-[a-z0-9]+(?:-[a-z0-9]+)*', key or ''):
                warn(f'{lang}/{f} se omite (falta la clave que une los dos idiomas)')
                continue
            rel = f'{lang}/{f}'
            legacy = LEGACY_NEWS.get(rel) == hashlib.sha256(body.strip().encode('utf-8', 'replace')).hexdigest()
            if legacy:
                h = body                                     # HTML original de la web, intacto
                url = ('/' if lang == 'es' else '/en/') + m.group(2) + '/'
            else:
                why = body_problem(body) or next((f'«{k}»: ' + body_problem(meta.get(k, ''))
                                                  for k in ('title', 'summary', 'description')
                                                  if body_problem(meta.get(k, ''))), '')
                if why:
                    warn(f'{rel} NO se publica: {why}')
                    continue
                h = markdown(body, links=False)
                url = ('/noticias/' if lang == 'es' else '/en/news/') + m.group(2) + '/'
            image = meta.get('image', '').strip()
            if image and not (IMG_OK.fullmatch(image) or (legacy and LEGACY_IMG.fullmatch(image))):
                warn(f'{rel}: imagen no válida ({image!r})')
                image = ''
            try:
                iw, ih = int(meta.get('image_width') or 1200), int(meta.get('image_height') or 675)
            except ValueError:
                iw, ih = 1200, 675
            title = re.sub(r'\s+', ' ', meta.get('title', '')).strip()[:200] or m.group(2)
            summary = re.sub(r'\s+', ' ', meta.get('summary', '')).strip()[:300]
            if not summary:
                tx = plain(h)
                summary = tx if len(tx) <= 220 else tx[:220].rsplit(' ', 1)[0] + '…'
            desc = (meta.get('description', '') if legacy else
                    re.sub(r'\s+', ' ', meta.get('description', '')).strip()[:158]) or (summary or plain(h))[:158]
            links_html = render_links_lang(meta.get('enlaces', []), rel, lang)
            if links_html:
                h += '\n' + links_html
            if key in found[lang]:
                warn(f'{rel}: ya hay otra noticia con la misma clave ({key})')
                continue
            found[lang][key] = dict(lang=lang, file=rel, url=url, title=title, date=dt, image=image, iw=iw, ih=ih,
                                    summary=summary, desc=desc, html=h, legacy=legacy)
    news = []
    for key, es in found['es'].items():
        news.append({'key': key, 'es': es, 'en': found['en'].get(key)})
    for key in set(found['en']) - set(found['es']):
        warn(f'{found["en"][key]["file"]}: versión inglesa sin la española ({key}); no se publica')
    urls = [n[l]['url'] for n in news for l in ('es', 'en') if n[l]]
    if len(urls) != len(set(urls)):
        warn('hay dos noticias con la misma dirección')
    news.sort(key=lambda n: (n['es']['date'], n['key']), reverse=True)
    return news


def render_links_lang(items, fname, lang):
    """Como render_links, con los textos en el idioma de la noticia."""
    global LINK_TYPES
    saved, LINK_TYPES = LINK_TYPES, LINK_LABELS[lang]
    try:
        return render_links(items, fname)
    finally:
        LINK_TYPES = saved


def card(v, lang, notice=''):
    """Tarjeta de la lista (misma estructura que la web). notice: aviso de «solo en español» en la lista inglesa."""
    t = T[lang]
    im = (f'<img src="{v["image"]}" alt="" width="{v["iw"]}" height="{v["ih"]}" loading="lazy">' if v['image']
          else '<div class="noimg"><img src="/img/icon-fish.png" alt="" width="64" height="64"></div>')
    note = (f'<span class="only-es" style="display:inline-block;margin:.2rem 0 .3rem;padding:.1rem .55rem;border-radius:999px;'
            f'background:#eef2f8;color:#1f3b6b;font-size:.78rem;font-weight:600">{notice}</span>') if notice else ''
    tl = ' lang="es"' if notice else ''
    return (f'<a class="card" href="{v["url"]}">{im}<div><time datetime="{v["date"].isoformat()}">{date_str(v["date"], lang)}</time>'
            f'{note}<h3{tl}>{esc(v["title"])}</h3><p{tl}>{esc(v["summary"])}</p><span class="more">{t["more"]} →</span></div></a>')


def list_cards(news, lang):
    out = []
    for n in news:
        if n[lang]:
            out.append(card(n[lang], lang))
        elif lang == 'en':                                   # sin versión inglesa: la española, con aviso
            out.append(card(dict(n['es'], date=n['es']['date']), 'en', ONLY_ES))
    return ''.join(out)


def build_list(news, lang):
    t = T[lang]
    title, desc = tpl(f'lista-{lang}-titulo.txt').split('\n')[:2]
    title = html.unescape(title.replace(' · TEDEPAD®', ''))
    body = (tpl(f'lista-{lang}-antes.html') + f'<section><div class="wrap cards">{list_cards(news, lang)}</div></section>'
            + tpl(f'lista-{lang}-despues.html'))
    return page(lang, t['news'], title, html.unescape(desc), body, T['en' if lang == 'es' else 'es']['news'])


def build_post(n, lang, news):
    v, t = n[lang], T[lang]
    other = n['en' if lang == 'es' else 'es']
    alt = other['url'] if other else T['en' if lang == 'es' else 'es']['news']
    hero = f'<img class="post-img" src="{v["image"]}" alt="" width="{v["iw"]}" height="{v["ih"]}">' if v['image'] else ''
    others = [x[lang] for x in news if x[lang] and x is not n][:3]
    body = f'''<article class="post"><div class="wrap narrow"><p class="back"><a href="{t['news']}">← {t['back']}</a></p>
  <time datetime="{v['date'].isoformat()}">{date_str(v['date'], lang)}</time><h1>{esc(v['title'])}</h1>{hero}<div class="post-body">{v['html']}</div></div></article>
<section class="band"><div class="wrap"><h2>{t['n_news']}</h2><div class="cards">{''.join(card(x, lang) for x in others)}</div></div></section>'''
    return page(lang, v['url'], v['title'], v['desc'], body, alt, alt_real=bool(other))


SKIP_TOP = {'.git', '.github', '_site', 'content', 'plantillas', 'tools', 'build.py', 'README.md', '.gitignore',
            '__pycache__', 'CLAUDE.md'}
NEWS_IMG_DIR = os.path.normcase(os.path.join(ROOT, 'img', 'noticias'))


def copy_site():
    def ignore(folder, names):
        if os.path.normcase(folder) == os.path.normcase(ROOT):
            return [n for n in names if n in SKIP_TOP]
        f = os.path.normcase(folder)
        if f != NEWS_IMG_DIR and not f.startswith(NEWS_IMG_DIR + os.sep):
            return []
        bad = [n for n in names if not (n.lower().endswith(IMG_EXT) and os.path.isfile(os.path.join(folder, n))
                                        and not os.path.islink(os.path.join(folder, n)))]
        for n in bad:
            warn(f'img/noticias/{n} no se publica (solo imágenes {", ".join(IMG_EXT)})')
        return bad
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    shutil.copytree(ROOT, OUT, ignore=ignore)


def write(rel, content):
    p = os.path.join(OUT, rel.strip('/').replace('/', os.sep), 'index.html')
    if os.path.exists(p) and rel not in WRITTEN:
        warn(f'la noticia {rel} pisaría una página existente de la web; no se publica')
        return
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, 'w', encoding='utf-8', newline='\n').write(content)
    WRITTEN.add(rel)


WRITTEN = set()


# ------------------------------------------------------------------ política de seguridad (CSP) de las páginas públicas
# Cada página publicada (menos /admin/, que tiene la suya) lleva una CSP que solo deja ejecutar scripts de tedepad.com y
# los scripts en línea de esta lista, identificados por su huella SHA-256. Si una página tiene un script en línea que no
# está aquí, la publicación SE PARA (no se añade solo).
#
# >>> SI SE CAMBIA UNO DE ESTOS SCRIPTS (o se añade uno nuevo), HAY QUE ACTUALIZAR SU HUELLA AQUÍ: <<<
#     1. python build.py  → el error dice la huella nueva y la página («script en línea no permitido … sha256-…»).
#     2. Comprobar que el cambio es legítimo, cambiar la huella en esta lista y volver a generar.
#     3. Es un cambio de código: commit + `bash tools/huella_codigo.sh --update` (ver README, «Política de seguridad»).
CSP_SCRIPTS = {
    'sha256-8OLQNo+0ITeLpdX9wZWkhYocwJ0tAfmxepRfFv2UEyI=': 'formulario de contacto (pie de todas las páginas: plantillas/pie-*.html)',
    'sha256-GKnTzhpdeBdn4djT++K/ZVvrjXsF/DsWTs/jEML+YEk=': 'redirección de direcciones antiguas (404.html)',
}
# Las páginas públicas no cargan ningún archivo .js: script-src solo admite las huellas de la lista (ni siquiera 'self',
# para que no se puedan reutilizar los scripts del panel /admin/ desde una página pública).
CSP_BASE = ("default-src 'self'; script-src {scripts}; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "media-src 'self'; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; "
            "form-action 'none'; frame-src 'none'; upgrade-insecure-requests")
CSP_META = ('<meta http-equiv="Content-Security-Policy" content="'
            + CSP_BASE.format(scripts=' '.join(f"'{h}'" for h in CSP_SCRIPTS)) + '">')
JS_TYPES = {'', 'text/javascript', 'application/javascript', 'module', 'text/ecmascript', 'application/ecmascript'}
URL_ATTRS = {'src', 'href', 'action', 'formaction', 'poster', 'data', 'srcset', 'background', 'xlink:href'}
# Archivos que un navegador podría ejecutar como página o script: fuera de /admin/ no se publican sin revisar.
RISKY_FILES = ('.htm', '.xhtml', '.shtml', '.svg', '.js', '.mjs', '.xml', '.xsl', '.xslt')


def is_own_url(u):
    """True si la dirección es de la propia web (relativa o https://tedepad.com/…)."""
    u = u.strip()
    if not re.match(r'(?:[a-z][a-z0-9+.-]*:|//)', u, re.I):
        return True                                    # relativa: /img/x.png, ../x, #ancla
    return bool(re.match(r'(?:https?:)?//(?:www\.)?tedepad\.com(?:[/:?#]|$)', u, re.I))


class CspCheck(HTMLParser):
    """Recorre una página como lo haría el navegador: scripts, atributos peligrosos y recursos de fuera."""

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.problems, self.order, self.script, self.in_script = [], [], None, False

    def handle_starttag(self, tag, attrs):
        self.order.append(('start', tag, dict(attrs)))
        a = {k.lower(): (v or '') for k, v in attrs}
        for k, v in a.items():
            if k.startswith('on'):
                self.problems.append(f'atributo de evento «{k}=» (la CSP lo bloquea)')
            if k in URL_ATTRS and re.match(r'[\s\x00-\x20]*(?:java|vb)script\s*:', v, re.I):
                self.problems.append(f'enlace «{k}=javascript:…» (la CSP lo bloquea)')
        if tag == 'script':
            typ = a.get('type', '').strip().lower()
            if 'src' in a:
                self.problems.append(f'carga un archivo de script ({a["src"][:80]}): las páginas públicas no admiten '
                                     f'scripts externos; si hace falta, revisar la CSP de build.py')
            self.in_script, self.script = True, ([] if typ in JS_TYPES and 'src' not in a else None)
        elif tag in ('iframe', 'frame', 'object', 'embed', 'base', 'applet'):
            self.problems.append(f'etiqueta <{tag}> (la CSP la bloquea o no se permite)')
        elif tag == 'form' and a.get('action', '').strip():
            self.problems.append(f'formulario con action={a["action"][:60]} (la CSP no deja enviar formularios)')
        elif tag == 'meta' and a.get('http-equiv', '').strip().lower() == 'content-security-policy':
            self.order[-1] = ('csp', tag, a)
        # <link> solo carga algo si es hoja de estilos, icono, precarga o manifiesto (canonical/alternate son solo enlaces)
        loads = tag != 'link' or re.search(r'\b(stylesheet|icon|preload|modulepreload|prefetch|manifest)\b',
                                           a.get('rel', ''), re.I)
        for k in ('src', 'poster', 'srcset') + (('href',) if tag == 'link' else ()):
            if k not in a or not loads:
                continue
            urls = [x.strip().split()[0] for x in a[k].split(',') if x.strip()] if k == 'srcset' else [a[k]]
            for u in urls:
                if not is_own_url(u) and not (tag == 'img' and u.strip().lower().startswith('data:')):
                    self.problems.append(f'<{tag} {k}> de fuera de tedepad.com ({u[:80]}): la CSP lo bloquearía')

    handle_startendtag = handle_starttag

    def handle_endtag(self, tag):
        self.order.append(('end', tag, {}))
        if tag == 'script' and self.in_script:
            if self.script is not None:
                code = ''.join(self.script)
                h = 'sha256-' + base64.b64encode(hashlib.sha256(code.encode('utf-8')).digest()).decode()
                if h not in CSP_SCRIPTS:
                    self.problems.append(f'script en línea no permitido ({h}). Si el cambio es legítimo, añadir esa '
                                         f'huella a CSP_SCRIPTS en build.py (ver README, «Política de seguridad»)')
            self.in_script, self.script = False, None

    def handle_data(self, data):
        if self.in_script and self.script is not None:
            self.script.append(data)

    def close(self):
        super().close()
        if self.in_script:
            self.problems.append('<script> sin cerrar')


def csp_well_placed(s):
    """La CSP tiene que ser una etiqueta real dentro de <head> y llegar antes que cualquier script, estilo o enlace."""
    c = CspCheck()
    c.feed(s)
    c.close()
    seen_head = False
    for kind, tag, _ in c.order:
        if kind == 'start' and tag == 'head':
            seen_head = True
        elif kind == 'csp':
            return seen_head
        elif tag in ('script', 'style', 'link', 'body') or (kind == 'end' and tag == 'head'):
            return False
    return False


def apply_csp():
    """Añade la CSP a todas las páginas de _site/ (menos /admin/) y comprueba lo que contienen."""
    n = 0
    for d, dirs, files in os.walk(OUT):
        rel_d = os.path.relpath(d, OUT).replace(os.sep, '/')
        if rel_d == 'admin' or rel_d.startswith('admin/'):
            dirs[:] = []
            continue
        for f in files:
            p = os.path.join(d, f)
            rel = os.path.relpath(p, OUT).replace(os.sep, '/')
            low = f.lower()
            if low.endswith(RISKY_FILES) and rel not in ('sitemap.xml',):
                warn(f'{rel}: este tipo de archivo puede ejecutar código y no lleva la CSP; no se publica sin revisarlo')
                continue
            if not low.endswith('.html'):
                continue
            try:
                s = open(p, encoding='utf-8').read()
            except UnicodeDecodeError:
                warn(f'{rel}: no es UTF-8 válido; no se le puede poner la CSP')
                continue
            c = CspCheck()
            c.feed(s)
            c.close()
            if any(kind == 'csp' for kind, _, _ in c.order):
                warn(f'{rel} ya trae su propia CSP: revisarla (la de build.py no se añade dos veces)')
                continue
            for msg in dict.fromkeys(c.problems):
                warn(f'{rel}: {msg}')
            head = re.search(r'<head\b[^>]*>', s, re.I)
            if not head:
                warn(f'{rel}: no tiene <head>; no se le puede poner la CSP')
                continue
            s = s[:head.end()] + '\n' + CSP_META + s[head.end():]
            if not csp_well_placed(s):
                warn(f'{rel}: la CSP no queda al principio de <head> (antes de scripts, estilos y enlaces); revisar la página')
                continue
            open(p, 'w', encoding='utf-8', newline='\n').write(s)
            n += 1
    return n


def build():
    copy_site()
    news = load_news()
    for lang in ('es', 'en'):
        WRITTEN.add(T[lang]['news'])
        write(T[lang]['news'], build_list(news, lang))
        for n in news:
            if n[lang]:
                write(n[lang]['url'], build_post(n, lang, news))
    # sitemap con todas las páginas publicadas (fuera /admin/ y la 404)
    urls = []
    for d, _, files in os.walk(OUT):
        if 'index.html' in files:
            rel = '/' + os.path.relpath(d, OUT).replace(os.sep, '/').strip('.').strip('/')
            rel = rel if rel == '/' else rel + '/'
            if not rel.startswith('/admin/'):
                urls.append(rel)
    urls.sort(key=lambda u: (u.startswith('/en/'), u))
    today = date.today().isoformat()
    with open(os.path.join(OUT, 'sitemap.xml'), 'w', encoding='utf-8', newline='\n') as fh:
        fh.write('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                 + ''.join(f'  <url><loc>{SITE}{u}</loc><lastmod>{today}</lastmod></url>\n' for u in urls) + '</urlset>\n')
    with open(os.path.join(OUT, 'robots.txt'), 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(f'User-agent: *\nAllow: /\nDisallow: /admin/\nSitemap: {SITE}/sitemap.xml\n')
    con_csp = apply_csp()
    print(f'OK: {len(news)} noticias ({sum(1 for n in news if n["en"])} con inglés), {len(urls)} páginas en {OUT}; '
          f'CSP en {con_csp} archivos HTML')
    if PROBLEMS:
        for msg in PROBLEMS:
            print(f'::error::{msg}')
        print(f'ERROR: {len(PROBLEMS)} problema(s) en el contenido: NO se publica (la web sigue como estaba).')
        sys.exit(1)


if __name__ == '__main__':
    build()
