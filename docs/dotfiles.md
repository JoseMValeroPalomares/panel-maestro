# Copia de tus dotfiles desde el panel

Si guardas tu configuración en un repositorio de git, la página **Copias** te enseña qué ha cambiado y la sube a GitHub con
un botón. Si no tienes ninguno, la tarjeta no aparece.

## Configurarlo

Por defecto busca `~/dotfiles`, con la estructura de GNU Stow: `stow/<componente>/...` y `seeds/<componente>/...`. Para otra
ruta, en `.env`:

```bash
PANEL_DOTFILES_DIR=/ruta/a/mis/dotfiles
```

Hacen falta dos cosas en el repositorio: una rama con remoto y acceso por clave SSH sin contraseña, y el script
`scripts/check-secrets.sh`, que debe terminar con error si encuentra algo que no deba subirse. Sin ese script no se sube nada.

## Qué hace el botón

1. Trae a `stow/` y `seeds/` lo que cambió en tu `~`. Si tus configuraciones están enlazadas con Stow, ya estarán al día.
2. Pasa `scripts/check-secrets.sh`. Si encuentra algo, deja el repositorio como estaba y te dice el archivo y la línea.
3. Hace un commit y lo sube, sin forzar nunca. Si GitHub tiene cambios más nuevos coloca los tuyos encima; si chocan, para.

Nunca escribe en `~` y nunca borra nada del repositorio. Lo que ya no esté en tu sistema se avisa y se conserva.

## Si retocaste el repositorio a mano

Si limpiaste archivos del repositorio y en `~` siguen como estaban, copiar `~` desharía ese trabajo. Indica el último commit
en el que los archivos estaban tal cual y el panel solo traerá lo que hayas cambiado desde entonces, sin tocar tus retoques:

```bash
PANEL_DOTFILES_BASE=<commit>
```

Si un archivo cambió en las mismas líneas en los dos lados, se queda fuera de la subida y el panel lo marca como «Choca».

## Qué no cubre

- Una carpeta de `~` que el repositorio aún no tenga no entra sola: es un componente nuevo de tu instalador.
- Los archivos nuevos solo entran si están en carpetas de las que el repositorio ya guarda algo.
- Los paquetes que instales no se añaden a ninguna lista.
