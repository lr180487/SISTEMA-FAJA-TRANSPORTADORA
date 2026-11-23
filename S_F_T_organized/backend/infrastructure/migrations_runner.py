"""Utilidades para ejecutar migraciones Alembic sobre un Engine existente."""
from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import Engine


def upgrade_database(engine: Engine) -> None:
    """Aplica todas las revisiones pendientes sobre el motor activo."""
    project_root = Path(__file__).resolve().parents[2]
    alembic_cfg = Config(str(project_root / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(project_root / "backend" / "infrastructure" / "migrations"))
    with engine.begin() as connection:
        alembic_cfg.attributes["connection"] = connection
        command.upgrade(alembic_cfg, "head")
