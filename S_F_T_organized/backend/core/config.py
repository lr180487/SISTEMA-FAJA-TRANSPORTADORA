from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional
from urllib.parse import quote_plus

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"


def load_env_file(env_path: Path = ENV_FILE, override: bool = False) -> Dict[str, str]:
    """
    Carga variables desde `.env` usando python-dotenv (con parser nativo de respaldo).
    Devuelve las claves presentes en el archivo `.env`.
    """
    parsed_keys: Dict[str, str] = {}
    if not env_path.exists():
        return parsed_keys

    try:
        from dotenv import dotenv_values, load_dotenv

        load_dotenv(dotenv_path=env_path, override=override)
        raw_vals = dotenv_values(dotenv_path=env_path)
        for k, v in raw_vals.items():
            if k:
                parsed_keys[k] = "" if v is None else str(v)
        return parsed_keys
    except Exception:
        pass

    # Respaldo nativo sin dependencias externas
    for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        clean = line.strip()
        if not clean or clean.startswith("#") or "=" not in clean:
            continue
        k, v = clean.split("=", 1)
        key = k.strip()
        val = v.strip().strip("\"'")
        parsed_keys[key] = val
        if override or key not in os.environ:
            os.environ[key] = val
    return parsed_keys


# Cargar `.env` inmediatamente al importar la configuración
load_env_file(ENV_FILE, override=False)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on", "si", "sí")


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw.strip())
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


def mask_dsn(url: str) -> str:
    """Enmascara contraseñas dentro de URLs de conexión de base de datos."""
    if not url:
        return ""
    return re.sub(r"(://[^:/@]+:)([^@]+)(@)", r"\1****\3", url)


def normalize_postgres_sqlalchemy_url(raw_url: str) -> str:
    """Normaliza esquemas postgres:// o postgresql:// al driver psycopg (SQLAlchemy 2)."""
    u = (raw_url or "").strip()
    if not u:
        return ""
    if u.startswith("postgres://"):
        return "postgresql+psycopg://" + u[len("postgres://") :]
    if u.startswith("postgresql://"):
        return "postgresql+psycopg://" + u[len("postgresql://") :]
    return u


@dataclass
class AppSettings:
    """Configuración centralizada del backend SCADA PID cargada desde `.env`."""

    app_name: str = os.environ.get("APP_NAME", "SCADA PID")
    app_description: str = (
        "Sistema en tiempo real de supervisión, control PID, persistencia PostgreSQL/SQLite "
        "y asistente inteligente para faja transportadora."
    )
    app_version: str = os.environ.get("APP_VERSION", "6.1.0")

    base_dir: Path = BASE_DIR
    env_file: Path = ENV_FILE
    frontend_dir: Path = BASE_DIR / "frontend"
    agents_dir: Path = BASE_DIR / "agents"
    knowledge_dir: Path = BASE_DIR / "knowledge_base"
    data_dir: Path = BASE_DIR / "data"

    host: str = os.environ.get("HOST", "0.0.0.0")
    port: int = _env_int("PORT", 8000)

    # Frecuencias del motor de simulación (20 Hz física / 10 Hz telemetría WebSocket)
    sim_dt_s: float = 0.05
    ws_broadcast_every_ticks: int = 2

    # Configuración de Base de Datos: PostgreSQL primario -> SQLite fallback
    db_preferred_engine: str = os.environ.get("DB_PREFERRED_ENGINE", "postgres").strip().lower()
    db_auto_fallback_sqlite: bool = _env_bool("DB_AUTO_FALLBACK_SQLITE", True)
    database_url: str = os.environ.get("DATABASE_URL", "").strip()

    postgres_host: str = os.environ.get("POSTGRES_HOST", "127.0.0.1").strip()
    postgres_port: int = _env_int("POSTGRES_PORT", 5432)
    postgres_db: str = os.environ.get("POSTGRES_DB", "scada_pid").strip()
    postgres_user: str = os.environ.get("POSTGRES_USER", "postgres").strip()
    postgres_password: str = os.environ.get("POSTGRES_PASSWORD", "postgres")
    postgres_sslmode: str = os.environ.get("POSTGRES_SSLMODE", "prefer").strip()
    postgres_connect_timeout: int = max(1, _env_int("POSTGRES_CONNECT_TIMEOUT", 2))

    sqlite_db_path: Path = Path(
        os.environ.get("SQLITE_DB_PATH", str(BASE_DIR / "data" / "scada_pid.db"))
    )

    db_telemetry_save_interval_s: float = max(1.0, _env_float("DB_TELEMETRY_SAVE_INTERVAL_S", 5.0))
    db_state_save_interval_s: float = max(1.0, _env_float("DB_STATE_SAVE_INTERVAL_S", 3.0))
    db_max_telemetry_rows: int = max(100, _env_int("DB_MAX_TELEMETRY_ROWS", 5000))
    db_max_event_rows: int = max(100, _env_int("DB_MAX_EVENT_ROWS", 1000))

    default_setpoint_mps: float = _env_float("DEFAULT_SETPOINT_MPS", 1.40)
    default_pid_preset: str = os.environ.get("DEFAULT_PID_PRESET", "balanced").strip()

    def reload_from_env(self) -> None:
        load_env_file(self.env_file, override=True)
        self.app_name = os.environ.get("APP_NAME", "SCADA PID")
        self.app_version = os.environ.get("APP_VERSION", "6.1.0")
        self.host = os.environ.get("HOST", "0.0.0.0")
        self.port = _env_int("PORT", 8000)
        self.db_preferred_engine = os.environ.get("DB_PREFERRED_ENGINE", "postgres").strip().lower()
        self.db_auto_fallback_sqlite = _env_bool("DB_AUTO_FALLBACK_SQLITE", True)
        self.database_url = os.environ.get("DATABASE_URL", "").strip()
        self.postgres_host = os.environ.get("POSTGRES_HOST", "127.0.0.1").strip()
        self.postgres_port = _env_int("POSTGRES_PORT", 5432)
        self.postgres_db = os.environ.get("POSTGRES_DB", "scada_pid").strip()
        self.postgres_user = os.environ.get("POSTGRES_USER", "postgres").strip()
        self.postgres_password = os.environ.get("POSTGRES_PASSWORD", "postgres")
        self.postgres_sslmode = os.environ.get("POSTGRES_SSLMODE", "prefer").strip()
        self.postgres_connect_timeout = max(1, _env_int("POSTGRES_CONNECT_TIMEOUT", 2))
        self.sqlite_db_path = Path(
            os.environ.get("SQLITE_DB_PATH", str(BASE_DIR / "data" / "scada_pid.db"))
        )
        self.db_telemetry_save_interval_s = max(1.0, _env_float("DB_TELEMETRY_SAVE_INTERVAL_S", 5.0))
        self.db_state_save_interval_s = max(1.0, _env_float("DB_STATE_SAVE_INTERVAL_S", 3.0))
        self.db_max_telemetry_rows = max(100, _env_int("DB_MAX_TELEMETRY_ROWS", 5000))
        self.db_max_event_rows = max(100, _env_int("DB_MAX_EVENT_ROWS", 1000))

    def build_postgres_url(self, custom_url: Optional[str] = None) -> str:
        raw = (custom_url or self.database_url or "").strip()
        if raw:
            return normalize_postgres_sqlalchemy_url(raw)
        user_enc = quote_plus(self.postgres_user)
        pwd_enc = quote_plus(self.postgres_password)
        return (
            f"postgresql+psycopg://{user_enc}:{pwd_enc}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
            f"?sslmode={self.postgres_sslmode}"
        )

    def build_sqlite_url(self) -> str:
        self.sqlite_db_path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{self.sqlite_db_path.resolve()}"


settings = AppSettings()
