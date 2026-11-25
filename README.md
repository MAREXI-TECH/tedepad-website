# tedepad.com

Código de la web pública de **TEDEPAD®** — [tedepad.com](https://tedepad.com), en español e inglés.

Es una web estática: un pequeño script de Python genera las páginas a partir de los textos y las noticias, y GitHub Pages
la publica. No hay servidor, base de datos ni formularios que guarden datos.

## Contenido

- `content/noticias/` — las noticias, una por archivo (español en `es/`, inglés en `en/`).
- `img/` — imágenes de la web y de las noticias. Los créditos de las imágenes que lo requieren están en
  [`IMAGENES.md`](IMAGENES.md).
- `build.py` — genera la web.

## Verla en local

Con Python 3:

```
python build.py
```

La web queda en la carpeta `_site/`.

## Contribuciones y seguridad

Este repositorio lo mantiene el equipo de la web; no se aceptan cambios externos.
Si crees haber encontrado un problema de seguridad, **no abras una incidencia pública**: escríbenos a
info@tedepad.com.

Los textos, imágenes y marcas pertenecen a sus titulares. Todos los derechos reservados.
