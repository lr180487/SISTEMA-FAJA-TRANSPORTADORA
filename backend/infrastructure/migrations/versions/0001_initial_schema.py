"""Esquema inicial SCADA PID.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-11-22

Snapshot independiente del esquema inicial. checkfirst permite adoptar una
instalación heredada con las tablas ya creadas y crear únicamente lo faltante.
No importa los modelos vivos para mantener esta revisión inmutable.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None

metadata = sa.MetaData()

sa.Table(
    "scada_runtime_state", metadata,
    sa.Column("state_key", sa.String(32), primary_key=True),
    sa.Column("plc_state", sa.String(24), nullable=False),
    sa.Column("direction", sa.String(16), nullable=False),
    sa.Column("target_speed_mps", sa.Float(), nullable=False),
    sa.Column("auto_feed", sa.Boolean(), nullable=False),
    sa.Column("feed_rate_per_min", sa.Float(), nullable=False),
    sa.Column("auto_divert_defective", sa.Boolean(), nullable=False),
    sa.Column("pid_mode", sa.String(16), nullable=False),
    sa.Column("pid_preset", sa.String(32), nullable=False),
    sa.Column("pid_kp", sa.Float(), nullable=False),
    sa.Column("pid_ki", sa.Float(), nullable=False),
    sa.Column("pid_kd", sa.Float(), nullable=False),
    sa.Column("pid_p_enabled", sa.Boolean(), nullable=False),
    sa.Column("pid_i_enabled", sa.Boolean(), nullable=False),
    sa.Column("pid_d_enabled", sa.Boolean(), nullable=False),
    sa.Column("pid_filter_tf", sa.Float(), nullable=False),
    sa.Column("pid_cv_min", sa.Float(), nullable=False),
    sa.Column("pid_cv_max", sa.Float(), nullable=False),
    sa.Column("pid_manual_cv", sa.Float(), nullable=False),
    sa.Column("dispatched_count", sa.Integer(), nullable=False),
    sa.Column("rejected_count", sa.Integer(), nullable=False),
    sa.Column("total_weight_dispatched_kg", sa.Float(), nullable=False),
    sa.Column("energy_kwh", sa.Float(), nullable=False),
    sa.Column("updated_at", sa.String(40), nullable=False),
)

telemetry = sa.Table(
    "scada_telemetry_log", metadata,
    sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
    sa.Column("timestamp_iso", sa.String(40), nullable=False),
    sa.Column("plc_state", sa.String(24), nullable=False),
    sa.Column("speed_mps", sa.Float(), nullable=False),
    sa.Column("target_speed_mps", sa.Float(), nullable=False),
    sa.Column("pid_cv_pct", sa.Float(), nullable=False),
    sa.Column("pid_error_mps", sa.Float(), nullable=False),
    sa.Column("current_a", sa.Float(), nullable=False),
    sa.Column("temp_c", sa.Float(), nullable=False),
    sa.Column("load_kg", sa.Float(), nullable=False),
    sa.Column("vibration_mms", sa.Float(), nullable=False),
    sa.Column("power_kw", sa.Float(), nullable=False),
    sa.Column("dispatched_count", sa.Integer(), nullable=False),
    sa.Column("rejected_count", sa.Integer(), nullable=False),
    sa.Column("oee_pct", sa.Float(), nullable=False),
)
sa.Index("ix_telemetry_id_desc", telemetry.c.id.desc())
sa.Index("ix_scada_telemetry_log_timestamp_iso", telemetry.c.timestamp_iso)

events = sa.Table(
    "scada_events_log", metadata,
    sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
    sa.Column("event_uid", sa.String(64), nullable=False),
    sa.Column("timestamp_iso", sa.String(40), nullable=False),
    sa.Column("time_short", sa.String(16), nullable=False),
    sa.Column("level", sa.String(16), nullable=False),
    sa.Column("source", sa.String(48), nullable=False),
    sa.Column("code", sa.String(48), nullable=False),
    sa.Column("message", sa.Text(), nullable=False),
    sa.Column("plc_state", sa.String(24), nullable=False),
    sa.Column("extra_json", sa.Text(), nullable=False),
)
sa.Index("ix_events_id_desc", events.c.id.desc())
sa.Index("ix_scada_events_log_event_uid", events.c.event_uid)
sa.Index("ix_scada_events_log_level", events.c.level)

sa.Table(
    "rag_documents_store", metadata,
    sa.Column("filename", sa.String(180), primary_key=True),
    sa.Column("title", sa.String(240), nullable=False),
    sa.Column("content", sa.Text(), nullable=False),
    sa.Column("builtin", sa.Boolean(), nullable=False),
    sa.Column("chunks_count", sa.Integer(), nullable=False),
    sa.Column("updated_at", sa.String(40), nullable=False),
)

chat = sa.Table(
    "rag_chat_history", metadata,
    sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
    sa.Column("turn_id", sa.String(80), nullable=False, unique=True),
    sa.Column("timestamp_short", sa.String(16), nullable=False),
    sa.Column("query", sa.Text(), nullable=False),
    sa.Column("answer", sa.Text(), nullable=False),
    sa.Column("provider_used", sa.String(32), nullable=False),
    sa.Column("model_used", sa.String(80), nullable=False),
    sa.Column("latency_ms", sa.Float(), nullable=False),
    sa.Column("active_agents_json", sa.Text(), nullable=False),
    sa.Column("sources_json", sa.Text(), nullable=False),
    sa.Column("web_search_json", sa.Text(), nullable=False),
    sa.Column("created_at", sa.String(40), nullable=False),
)
sa.Index("ix_rag_chat_history_turn_id", chat.c.turn_id, unique=True)

sa.Table(
    "app_kv_settings", metadata,
    sa.Column("key", sa.String(96), primary_key=True),
    sa.Column("value_json", sa.Text(), nullable=False),
    sa.Column("updated_at", sa.String(40), nullable=False),
)


def upgrade() -> None:
    metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    metadata.drop_all(bind=op.get_bind(), checkfirst=True)
