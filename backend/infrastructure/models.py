"""Modelos ORM SQLAlchemy del sistema SCADA PID.

Este módulo contiene únicamente el metadata y las entidades persistentes.
Mantiene los nombres de tablas y columnas existentes para compatibilidad.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, Float, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utc_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class Base(DeclarativeBase):
    pass


# ------------------------------------------------------------------
# Modelos ORM Relacionales (Compatibles 100% con PostgreSQL y SQLite)
# ------------------------------------------------------------------
class ScadaRuntimeStateRow(Base):
    __tablename__ = "scada_runtime_state"

    state_key: Mapped[str] = mapped_column(String(32), primary_key=True, default="primary")
    plc_state: Mapped[str] = mapped_column(String(24), default="RUNNING")
    direction: Mapped[str] = mapped_column(String(16), default="FORWARD")
    target_speed_mps: Mapped[float] = mapped_column(Float, default=1.40)

    auto_feed: Mapped[bool] = mapped_column(Boolean, default=True)
    feed_rate_per_min: Mapped[float] = mapped_column(Float, default=16.0)
    auto_divert_defective: Mapped[bool] = mapped_column(Boolean, default=True)

    pid_mode: Mapped[str] = mapped_column(String(16), default="AUTO")
    pid_preset: Mapped[str] = mapped_column(String(32), default="balanced")
    pid_kp: Mapped[float] = mapped_column(Float, default=36.0)
    pid_ki: Mapped[float] = mapped_column(Float, default=26.0)
    pid_kd: Mapped[float] = mapped_column(Float, default=4.2)
    pid_p_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    pid_i_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    pid_d_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    pid_filter_tf: Mapped[float] = mapped_column(Float, default=0.12)
    pid_cv_min: Mapped[float] = mapped_column(Float, default=0.0)
    pid_cv_max: Mapped[float] = mapped_column(Float, default=100.0)
    pid_manual_cv: Mapped[float] = mapped_column(Float, default=52.0)

    dispatched_count: Mapped[int] = mapped_column(Integer, default=18)
    rejected_count: Mapped[int] = mapped_column(Integer, default=2)
    total_weight_dispatched_kg: Mapped[float] = mapped_column(Float, default=186.4)
    energy_kwh: Mapped[float] = mapped_column(Float, default=0.420)
    updated_at: Mapped[str] = mapped_column(String(40), default=_utc_iso)


class ScadaTelemetryLogRow(Base):
    __tablename__ = "scada_telemetry_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp_iso: Mapped[str] = mapped_column(String(40), index=True)
    plc_state: Mapped[str] = mapped_column(String(24))
    speed_mps: Mapped[float] = mapped_column(Float)
    target_speed_mps: Mapped[float] = mapped_column(Float)
    pid_cv_pct: Mapped[float] = mapped_column(Float)
    pid_error_mps: Mapped[float] = mapped_column(Float)
    current_a: Mapped[float] = mapped_column(Float)
    temp_c: Mapped[float] = mapped_column(Float)
    load_kg: Mapped[float] = mapped_column(Float)
    vibration_mms: Mapped[float] = mapped_column(Float)
    power_kw: Mapped[float] = mapped_column(Float)
    dispatched_count: Mapped[int] = mapped_column(Integer)
    rejected_count: Mapped[int] = mapped_column(Integer)
    oee_pct: Mapped[float] = mapped_column(Float)


class ScadaEventLogRow(Base):
    __tablename__ = "scada_events_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_uid: Mapped[str] = mapped_column(String(64), index=True)
    timestamp_iso: Mapped[str] = mapped_column(String(40))
    time_short: Mapped[str] = mapped_column(String(16))
    level: Mapped[str] = mapped_column(String(16), index=True)
    source: Mapped[str] = mapped_column(String(48))
    code: Mapped[str] = mapped_column(String(48))
    message: Mapped[str] = mapped_column(Text)
    plc_state: Mapped[str] = mapped_column(String(24))
    extra_json: Mapped[str] = mapped_column(Text, default="{}")


class RagDocumentRow(Base):
    __tablename__ = "rag_documents_store"

    filename: Mapped[str] = mapped_column(String(180), primary_key=True)
    title: Mapped[str] = mapped_column(String(240))
    content: Mapped[str] = mapped_column(Text)
    builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    chunks_count: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[str] = mapped_column(String(40), default=_utc_iso)


class RagChatTurnRow(Base):
    __tablename__ = "rag_chat_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    turn_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    timestamp_short: Mapped[str] = mapped_column(String(16))
    query: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    provider_used: Mapped[str] = mapped_column(String(32), default="local-rag")
    model_used: Mapped[str] = mapped_column(String(80), default="")
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    active_agents_json: Mapped[str] = mapped_column(Text, default="[]")
    sources_json: Mapped[str] = mapped_column(Text, default="[]")
    web_search_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[str] = mapped_column(String(40), default=_utc_iso)


class AppKvSettingRow(Base):
    __tablename__ = "app_kv_settings"

    key: Mapped[str] = mapped_column(String(96), primary_key=True)
    value_json: Mapped[str] = mapped_column(Text, default="{}")
    updated_at: Mapped[str] = mapped_column(String(40), default=_utc_iso)


Index("ix_telemetry_id_desc", ScadaTelemetryLogRow.id.desc())
Index("ix_events_id_desc", ScadaEventLogRow.id.desc())


