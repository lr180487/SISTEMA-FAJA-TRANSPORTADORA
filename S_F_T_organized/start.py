#!/usr/bin/env python3
"""
Lanzador unificado del Sistema SCADA PID (Simulación Faja Transportadora).
Carga automáticamente `.env`, inicializa PostgreSQL con fallback a SQLite
y levanta el servidor FastAPI.

Uso:
  python3 start.py
  python3 start.py --host 0.0.0.0 --port 8000
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

try:
    import ddgs  # noqa: F401
    import dotenv
    import fastapi  # noqa: F401
    import psycopg  # noqa: F401
    import sqlalchemy  # noqa: F401
    import uvicorn
except ImportError:
    req_file = BASE_DIR / "requirements.txt"
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "--quiet", "-r", str(req_file)]
    )
    import dotenv
    import uvicorn


def main() -> None:
    env_file = BASE_DIR / ".env"
    if env_file.exists():
        dotenv.load_dotenv(dotenv_path=env_file, override=False)

    default_host = os.environ.get("HOST", "0.0.0.0")
    default_port = int(os.environ.get("PORT", "8000"))

    parser = argparse.ArgumentParser(description="SCADA PID · Servidor Backend")
    parser.add_argument("--host", default=default_host, help=f"Host de enlace (por defecto: {default_host})")
    parser.add_argument("--port", type=int, default=default_port, help=f"Puerto TCP (por defecto: {default_port})")
    args = parser.parse_args()

    os.environ["HOST"] = str(args.host)
    os.environ["PORT"] = str(args.port)

    print(f"[SCADA PID] Panel disponible en http://{args.host}:{args.port}")
    uvicorn.run("backend.main:app", host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()
