# Configuración S_F_T para Render con Python 3.14 y uv

## Archivos
- `pyproject.toml`: dependencias y metadatos del proyecto.
- `uv.lock`: versiones bloqueadas de dependencias (conservado del archivo recibido).
- `.python-version`: fija Python 3.14.10.
- `render.yaml`: configuración declarativa del Web Service.

## Comandos manuales en Render

Build Command:

```bash
curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR="$HOME/.local/bin" sh && "$HOME/.local/bin/uv" --version && "$HOME/.local/bin/uv" sync --locked --no-dev --no-install-project
```

Start Command:

```bash
./.venv/bin/python -m uvicorn backend.main:app --host 0.0.0.0 --port $PORT
```

## Por qué se usa la ruta absoluta de uv
Render estaba invocando un wrapper (`/home/render/envwrappers/uv`) que no encontraba el ejecutable `uv`.
La instalación se hace explícitamente en `$HOME/.local/bin` y se ejecuta por ruta absoluta,
evitando depender del wrapper o de que `PATH` se actualice entre comandos.

`--no-install-project` instala las dependencias bloqueadas sin intentar empaquetar la aplicación
como distribución Python; Uvicorn ejecuta el módulo desde el directorio raíz del repositorio.

## Importante
1. Copia estos cuatro archivos a la raíz del repositorio Git.
2. En Render, usa la raíz del repositorio como `Root Directory`.
3. Si usas `render.yaml`, sincroniza el Blueprint en Render. Si configuras el servicio manualmente,
   copia los comandos y variables anteriores.
4. No agregues `UV_VERSION` como si fuera una versión de Python. `PYTHON_VERSION` controla Python.
5. No borres ni regeneres `uv.lock` manualmente. El build usa `--locked` y fallará claramente
   si `pyproject.toml` y `uv.lock` dejan de estar sincronizados.

## Validación local realizada
- `uv lock --check`: correcto con uv 0.10.0.
- Se conservaron las dependencias y el contenido del lockfile recibido.
- No se pudo ejecutar un build de Render desde este entorno; la compilación final debe confirmarse en el deploy.
