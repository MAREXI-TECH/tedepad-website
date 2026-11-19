# tedepad.com

Web estática de TEDEPAD® (español e inglés), publicada con GitHub Pages.

## Cómo funciona

- Las páginas fijas (portada, productos, quiénes somos, soporte, contacto, textos legales, `en/…`) son archivos HTML
  del repositorio y se publican tal cual.
- Las **noticias** salen de `content/noticias/es/*.md` y `content/noticias/en/*.md` (una por archivo,
  `AAAA-MM-DD-titulo.md`). `build.py` genera con ellas las páginas de cada noticia y las listas `/noticias/` y
  `/en/news/`, usando las partes fijas de `plantillas/` (sacadas de la propia web: estilos, pie, cabecera de la lista).
- Cada cambio en la rama `main` regenera y publica la web automáticamente (GitHub Actions → GitHub Pages).

### Español e inglés

- El español es obligatorio; el **inglés es opcional**. Las dos versiones se unen por la clave `translationKey`.
- **Sin versión inglesa:** la noticia aparece también en la lista inglesa con el aviso «Only available in Spanish» y
  lleva a la página española.
- **Si más tarde se añade el inglés:** la lista inglesa pasa a llevar a la página inglesa, con normalidad.
- Direcciones de las noticias nuevas: `/noticias/<titulo>/` y `/en/news/<title>/`. Las 22 noticias anteriores al panel
  (11 en cada idioma) mantienen sus direcciones de siempre.

## Panel de noticias

En `https://tedepad.com/admin/` hay un panel (Sveltia CMS) para **crear, editar y borrar noticias** sin tocar código.
Solo gestiona `content/noticias/` y las imágenes de `img/noticias/`; el resto de la web se cambia editando el
repositorio. Para escribir en inglés: en la noticia, selector de idioma → «Inglés» → «Habilitar Inglés».

- **Acceso:** cuenta de GitHub con verificación en dos pasos y permiso de escritura en este repositorio (que, por sí
  solo, permitiría cambiar todo: por eso existe el control de integridad de abajo). Se entra con «Iniciar sesión con
  un token de acceso»: un *fine-grained token* (`github_pat_…`) con acceso **solo a este repositorio**, permiso
  *Contents: Read and write* (nunca *Workflows*) y caducidad ≤ 90 días. El navegador lo recuerda (mejor un perfil de
  navegador solo para el panel, sin extensiones).
- **Guardia (`admin/guard.js`, código propio):** se carga antes de Sveltia; no deja abrir el panel dentro de otra web
  (iframe) y borra al momento cualquier token que no sea *fine-grained*.
- **Control de integridad (en `.github/workflows/pages.yml`):** solo se publica si todo lo que no son noticias
  (`content/noticias/{es,en}/*.md`, `img/noticias/*.{webp,jpg,png,gif,avif}`) coincide con la huella `CODE_TREE`. Con
  un token de editor solo se pueden cambiar noticias. **Tras cambiar código:** commit, `bash tools/huella_codigo.sh
  --update` y commit de `pages.yml`. Cualquier problema de contenido también detiene la publicación (`::error::`) y
  GitHub avisa por correo.
- **Reglas compartidas:** las normas del texto (`BODY_RULES`) y los acortadores (`SHORTENERS`) están en `build.py`;
  `python tools/reglas_panel.py` las copia a los patrones de `admin/config.yml` y la publicación comprueba que
  coinciden.
- **Seguridad:** el panel funciona entero en el navegador (sin servidor propio ni servicios de terceros con acceso).
  `admin/index.html` lleva una política de seguridad (CSP) que solo deja cargar código desde esta web y solo hablar con
  la API de GitHub. `build.py` trata todo lo que llega del panel como no fiable: imagen principal solo de
  `/img/noticias/`; dirección (slug) solo `a-z0-9-`; texto escapado; nunca pisa una página existente de la web.
- **Enlaces:** el texto de las noticias **no admite enlaces, imágenes ni direcciones web**: el panel no deja guardarlo
  y, si llegara por otra vía, la noticia no se publica. Las fuentes, vídeos y enlaces relacionados van en el apartado
  **«Fuentes y enlaces»** (`tipo`, `nombre`, `url`) y se muestran al final en el idioma de la noticia. Cada dirección
  se comprueba (`check_external_url`): solo `https://` a un dominio público, sin usuario/contraseña, IP, puerto raro,
  dominios `xn--`, acortadores ni archivos ejecutables o comprimidos.
- **Noticias anteriores al panel:** las 22 (`LEGACY_NEWS`) se publican con su HTML original **solo mientras su texto
  no cambie** (huella SHA-256). Si se edita su texto desde el panel, pasa a regirse por las normas nuevas y, como su
  HTML lleva enlaces, la publicación se detiene: para cambiar una noticia antigua, hacerlo en el repositorio.
- **Aspecto:** nombre y logo de TEDEPAD (`app_title`, `logo` en `admin/config.yml`) y colores de la web en
  `admin/panel.css`.
- **Copia fija:** `admin/sveltia-cms.js` y `admin/chunks/` son Sveltia CMS **0.258.1** (npm `@sveltia/cms`, integridad
  sha512 y certificado de origen comprobados). SHA-256 de `sveltia-cms.js`:
  `7b4add3ae688e7b1604c235b5aac1d007c0a414bdeee49d0ceca7c80c5549c8a`. Para actualizarlo: elegir una versión publicada
  hace al menos dos semanas, comprobar su integridad y su origen, probar en local, revisión y PR.

## Probar en local

Solo hace falta Python 3.9 o superior, sin dependencias:

```
python build.py
python -m http.server 8000 --directory _site
```

y abrir `http://localhost:8000/`.
