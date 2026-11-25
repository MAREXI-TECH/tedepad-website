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
- **Aprobación antes de publicar (25/11/2026):** el entorno `github-pages` exige la aprobación de **ChristianMarexi**
  (con verificación en dos pasos; se puede aprobar desde la app de GitHub del móvil). Lo guardado en el panel queda en
  `main`, pero no sale a la web hasta que se aprueba el despliegue en *Actions* (GitHub avisa por correo; la petición
  caduca a los 30 días). Si se guardan varias noticias seguidas, basta con aprobar la última ejecución. Así, una clave
  robada no puede publicar nada. Los editores (p. ej., marketing de Industrias Ferri) no necesitan hacer nada más que
  guardar. Clave del panel: 90 días; al caducar, crear una nueva y dársela. Mejor cerrar sesión en el panel al terminar
  en ordenadores compartidos.
- **Resumen al aprobar:** el paso «Resumen para la aprobación» (`tools/resumen_cambios.py`) muestra en la página de la
  ejecución qué noticias son nuevas, editadas o borradas, las imágenes y cualquier cambio fuera de las noticias,
  comparando con lo publicado (`/version.txt`, el commit que está en la web). Los cambios del panel llevan mensajes que
  empiezan por «Panel:» con la cuenta que los hizo (`commit_messages` en `admin/config.yml`).
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

## Política de seguridad (CSP)

Al publicar, `build.py` añade a **todas las páginas** (menos `/admin/`, que tiene la suya) una política de seguridad
(`Content-Security-Policy` en una etiqueta `<meta>`, justo al principio de `<head>`, porque GitHub Pages no deja
poner cabeceras): **solo se ejecutan los scripts en línea de una lista fija** (`CSP_SCRIPTS` en `build.py`),
identificados por su huella SHA-256; las páginas públicas no cargan archivos `.js` (ni siquiera de tedepad.com, para
que no se puedan reutilizar los del panel). Imágenes de tedepad.com o incrustadas (`data:`); vídeos, estilos y fuentes
solo de tedepad.com; ningún formulario puede enviar datos; sin iframes ni objetos incrustados. Los estilos en línea sí
se permiten.

Antes de publicar, `build.py` revisa cada página como lo haría el navegador y **para la publicación** si encuentra algo
que la CSP bloquearía o que no debería estar: scripts en línea que no están en la lista, archivos de script, eventos
`on…=`, enlaces `javascript:`, imágenes/estilos/vídeos de otras webs, iframes, `<base>`, formularios con `action`, una
CSP propia, la CSP mal colocada, o archivos que pueden ejecutar código fuera de `/admin/` (`.svg`, `.htm`, `.js`…).
Los datos `<script type="application/ld+json">` sí se permiten.

Hoy la lista tiene dos scripts: el del **formulario de contacto** (pie de todas las páginas, `plantillas/pie-*.html`)
y el de **redirección de direcciones antiguas** (`404.html`).

> **Importante — al cambiar uno de esos scripts (o añadir otro), hay que actualizar su huella en `CSP_SCRIPTS`.**
> Si no se hace, la publicación **se para** con un error «script en línea no permitido (sha256-…)» que dice la página
> y la huella nueva (la web sigue como estaba; no se rompe). Pasos: `python build.py` → comprobar que el cambio es
> legítimo → poner la huella nueva en `CSP_SCRIPTS` (y quitar la vieja si ya no se usa) → volver a generar → commit →
> `bash tools/huella_codigo.sh --update` → commit. Nunca añadir `'unsafe-inline'` a los scripts para «arreglarlo».

Límite conocido: con la etiqueta `<meta>` no se puede usar `frame-ancestors`, así que otra web podría mostrar las
páginas públicas dentro de un marco (no tienen nada delicado; el panel `/admin/` se protege con su propia guardia).

## Probar en local

Solo hace falta Python 3.9 o superior, sin dependencias:

```
python build.py
python -m http.server 8000 --directory _site
```

y abrir `http://localhost:8000/`.
