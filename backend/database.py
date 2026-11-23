<<<<<<< HEAD
from backend.infrastructure.database import *  # noqa: F401,F403
=======
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, TypeVar

from sqlalchemy import (
    Boolean,
    Float,
    Index,
    Integer,
    String,
    Text,
    create_engine,
    delete,
    event,
    func,
    select,
    text,
)
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from backend.config import mask_dsn, settings

T = TypeVar("T")


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


# ------------------------------------------------------------------
# Gestor Dual de Base de Datos: PostgreSQL (Primario) -> SQLite (Fallback)
# ------------------------------------------------------------------
class DatabaseManager:
    """
    Gestiona la persistencia relacional intentando conectar primero a PostgreSQL
    y conmutando automáticamente a SQLite local (`WAL`) si PostgreSQL no está
    disponible al arrancar o si se interrumpe en tiempo de ejecución.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._engine: Optional[Engine] = None
        self._session_factory: Optional[sessionmaker[Session]] = None

        self.active_backend: str = "uninitialized"  # "postgresql" | "sqlite"
        self.preferred_backend: str = settings.db_preferred_engine
        self.fallback_active: bool = False
        self.fallback_reason: Optional[str] = None
        self.postgres_dsn_masked: str = ""
        self.sqlite_path_str: str = str(settings.sqlite_db_path)
        self.connected_at: Optional[str] = None
        self.last_write_at: Optional[str] = None
        self._telemetry_write_counter: int = 0
        self._event_write_counter: int = 0

        self.connect()

    def _build_pg_engine(self, custom_url: Optional[str] = None) -> Engine:
        pg_url = settings.build_postgres_url(custom_url=custom_url)
        self.postgres_dsn_masked = mask_dsn(pg_url)
        return create_engine(
            pg_url,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=5,
            connect_args={"connect_timeout": settings.postgres_connect_timeout},
        )

    def _build_sqlite_engine(self) -> Engine:
        sqlite_url = settings.build_sqlite_url()
        self.sqlite_path_str = str(settings.sqlite_db_path.resolve())
        eng = create_engine(
            sqlite_url,
            connect_args={"check_same_thread": False, "timeout": 15},
        )

        @event.listens_for(eng, "connect")
        def _set_sqlite_pragma(dbapi_conn, _conn_record):
            cursor = dbapi_conn.cursor()
            try:
                cursor.execute("PRAGMA journal_mode=WAL;")
                cursor.execute("PRAGMA synchronous=NORMAL;")
                cursor.execute("PRAGMA foreign_keys=ON;")
            finally:
                cursor.close()

        return eng

    def _activate_sqlite_locked(self, reason: Optional[str] = None) -> Dict[str, Any]:
        if self._engine is not None:
            try:
                self._engine.dispose()
            except Exception:
                pass
        eng = self._build_sqlite_engine()
        Base.metadata.create_all(eng)
        self._engine = eng
        self._session_factory = sessionmaker(bind=eng, expire_on_commit=False)
        self.active_backend = "sqlite"
        self.fallback_active = reason is not None
        self.fallback_reason = reason
        self.connected_at = _utc_iso()
        return self.get_status()

    def connect(self, custom_postgres_url: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            self.preferred_backend = settings.db_preferred_engine
            wants_pg = bool(custom_postgres_url) or self.preferred_backend in (
                "postgres",
                "postgresql",
                "auto",
            )

            if wants_pg:
                try:
                    pg_eng = self._build_pg_engine(custom_url=custom_postgres_url)
                    with pg_eng.connect() as conn:
                        conn.execute(text("SELECT 1"))
                    Base.metadata.create_all(pg_eng)
                    if self._engine is not None:
                        try:
                            self._engine.dispose()
                        except Exception:
                            pass
                    self._engine = pg_eng
                    self._session_factory = sessionmaker(bind=pg_eng, expire_on_commit=False)
                    self.active_backend = "postgresql"
                    self.fallback_active = False
                    self.fallback_reason = None
                    self.connected_at = _utc_iso()
                    return self.get_status()
                except Exception as exc:
                    short_err = str(exc).splitlines()[0][:180]
                    if not settings.db_auto_fallback_sqlite and not custom_postgres_url:
                        raise
                    return self._activate_sqlite_locked(
                        reason=f"PostgreSQL no disponible ({short_err}); usando SQLite local."
                    )

            return self._activate_sqlite_locked(reason=None)

    def reconnect(self, custom_postgres_url: Optional[str] = None) -> Dict[str, Any]:
        settings.reload_from_env()
        return self.connect(custom_postgres_url=custom_postgres_url)

    def _run_with_failover(self, operation: Callable[[Session], T]) -> T:
        with self._lock:
            if self._session_factory is None:
                self.connect()
            factory = self._session_factory
            current_backend = self.active_backend

        assert factory is not None
        try:
            with factory() as session:
                result = operation(session)
                session.commit()
                return result
        except OperationalError as exc:
            if current_backend == "postgresql" and settings.db_auto_fallback_sqlite:
                with self._lock:
                    short_err = str(exc).splitlines()[0][:160]
                    self._activate_sqlite_locked(
                        reason=f"Conmutación en vivo a SQLite por caída de PostgreSQL ({short_err})."
                    )
                    fallback_factory = self._session_factory
                assert fallback_factory is not None
                with fallback_factory() as session:
                    result = operation(session)
                    session.commit()
                    return result
            raise

    # ------------------------------------------------------------------
    # Diagnóstico y Estado de la Base de Datos
    # ------------------------------------------------------------------
    def get_status(self) -> Dict[str, Any]:
        counts = {
            "telemetry_rows": 0,
            "event_rows": 0,
            "document_rows": 0,
            "chat_rows": 0,
        }
        try:
            def _count_op(s: Session) -> Dict[str, int]:
                return {
                    "telemetry_rows": int(s.scalar(select(func.count()).select_from(ScadaTelemetryLogRow)) or 0),
                    "event_rows": int(s.scalar(select(func.count()).select_from(ScadaEventLogRow)) or 0),
                    "document_rows": int(s.scalar(select(func.count()).select_from(RagDocumentRow)) or 0),
                    "chat_rows": int(s.scalar(select(func.count()).select_from(RagChatTurnRow)) or 0),
                }

            counts = self._run_with_failover(_count_op)
        except Exception:
            pass

        return {
            "online": self.active_backend in ("postgresql", "sqlite"),
            "active_engine": self.active_backend,
            "preferred_engine": self.preferred_backend,
            "fallback_active": self.fallback_active,
            "fallback_reason": self.fallback_reason,
            "postgres_dsn": self.postgres_dsn_masked,
            "sqlite_path": self.sqlite_path_str,
            "connected_at": self.connected_at,
            "last_write_at": self.last_write_at,
            "counts": counts,
        }

    # ------------------------------------------------------------------
    # Persistencia y Restauración de Estado Operativo (Faja + PID)
    # ------------------------------------------------------------------
    def load_runtime_state(self) -> Optional[Dict[str, Any]]:
        try:
            def _op(s: Session) -> Optional[Dict[str, Any]]:
                row = s.get(ScadaRuntimeStateRow, "primary")
                if not row:
                    return None
                return {
                    "plc_state": row.plc_state,
                    "direction": row.direction,
                    "target_speed_mps": row.target_speed_mps,
                    "auto_feed": row.auto_feed,
                    "feed_rate_per_min": row.feed_rate_per_min,
                    "auto_divert_defective": row.auto_divert_defective,
                    "pid_mode": row.pid_mode,
                    "pid_preset": row.pid_preset,
                    "pid_kp": row.pid_kp,
                    "pid_ki": row.pid_ki,
                    "pid_kd": row.pid_kd,
                    "pid_p_enabled": row.pid_p_enabled,
                    "pid_i_enabled": row.pid_i_enabled,
                    "pid_d_enabled": row.pid_d_enabled,
                    "pid_filter_tf": row.pid_filter_tf,
                    "pid_cv_min": row.pid_cv_min,
                    "pid_cv_max": row.pid_cv_max,
                    "pid_manual_cv": row.pid_manual_cv,
                    "dispatched_count": row.dispatched_count,
                    "rejected_count": row.rejected_count,
                    "total_weight_dispatched_kg": row.total_weight_dispatched_kg,
                    "energy_kwh": row.energy_kwh,
                    "updated_at": row.updated_at,
                }

            return self._run_with_failover(_op)
        except SQLAlchemyError:
            return None

    def save_runtime_state_from_snapshot(self, snap: Dict[str, Any]) -> None:
        try:
            plc = snap["plc"]
            kin = snap["kinematics"]
            pid = snap["pid"]
            prod = snap["production"]
            mot = snap["motor"]
            now_str = _utc_iso()

            def _op(s: Session) -> None:
                row = s.get(ScadaRuntimeStateRow, "primary")
                if row is None:
                    row = ScadaRuntimeStateRow(state_key="primary")
                    s.add(row)
                row.plc_state = plc["state"]
                row.direction = plc["direction"]
                row.target_speed_mps = float(kin["target_speed_mps"])
                row.auto_feed = bool(plc["auto_feed"])
                row.feed_rate_per_min = float(plc["feed_rate_per_min"])
                row.auto_divert_defective = bool(plc["auto_divert_defective"])

                row.pid_mode = pid["mode"]
                row.pid_preset = pid.get("active_preset", "balanced")
                row.pid_kp = float(pid["kp"])
                row.pid_ki = float(pid["ki"])
                row.pid_kd = float(pid["kd"])
                row.pid_p_enabled = bool(pid["p_enabled"])
                row.pid_i_enabled = bool(pid["i_enabled"])
                row.pid_d_enabled = bool(pid["d_enabled"])
                row.pid_filter_tf = float(pid["filter_tf"])
                row.pid_cv_min = float(pid["cv_min"])
                row.pid_cv_max = float(pid["cv_max"])
                row.pid_manual_cv = float(pid["manual_cv"])

                row.dispatched_count = int(prod["dispatched_count"])
                row.rejected_count = int(prod["rejected_count"])
                row.total_weight_dispatched_kg = float(prod["total_weight_dispatched_kg"])
                row.energy_kwh = float(mot["energy_kwh"])
                row.updated_at = now_str

            self._run_with_failover(_op)
            self.last_write_at = now_str
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Registro Histórico de Telemetría y Eventos
    # ------------------------------------------------------------------
    def insert_telemetry_sample(self, snap: Dict[str, Any]) -> None:
        try:
            plc = snap["plc"]
            kin = snap["kinematics"]
            pid = snap["pid"]
            mot = snap["motor"]
            prod = snap["production"]
            now_str = snap.get("timestamp") or _utc_iso()

            def _op(s: Session) -> None:
                s.add(
                    ScadaTelemetryLogRow(
                        timestamp_iso=now_str,
                        plc_state=plc["state"],
                        speed_mps=float(kin["actual_speed_mps"]),
                        target_speed_mps=float(kin["target_speed_mps"]),
                        pid_cv_pct=float(pid["cv_pct"]),
                        pid_error_mps=float(pid["error_mps"]),
                        current_a=float(mot["current_a"]),
                        temp_c=float(mot["temp_c"]),
                        load_kg=float(prod["current_load_kg"]),
                        vibration_mms=float(mot["vibration_mms"]),
                        power_kw=float(mot["power_kw"]),
                        dispatched_count=int(prod["dispatched_count"]),
                        rejected_count=int(prod["rejected_count"]),
                        oee_pct=float(prod["oee_pct"]),
                    )
                )
                self._telemetry_write_counter += 1
                if self._telemetry_write_counter % 50 == 0:
                    max_rows = settings.db_max_telemetry_rows
                    total = int(s.scalar(select(func.count()).select_from(ScadaTelemetryLogRow)) or 0)
                    if total > max_rows:
                        cutoff_id = s.scalar(
                            select(ScadaTelemetryLogRow.id)
                            .order_by(ScadaTelemetryLogRow.id.desc())
                            .offset(max_rows)
                            .limit(1)
                        )
                        if cutoff_id is not None:
                            s.execute(
                                delete(ScadaTelemetryLogRow).where(ScadaTelemetryLogRow.id <= cutoff_id)
                            )

            self._run_with_failover(_op)
            self.last_write_at = _utc_iso()
        except Exception:
            pass

    def query_telemetry_log(self, limit: int = 100) -> List[Dict[str, Any]]:
        safe_limit = max(1, min(1000, int(limit)))
        try:
            def _op(s: Session) -> List[Dict[str, Any]]:
                rows = s.scalars(
                    select(ScadaTelemetryLogRow)
                    .order_by(ScadaTelemetryLogRow.id.desc())
                    .limit(safe_limit)
                ).all()
                return [
                    {
                        "id": r.id,
                        "timestamp": r.timestamp_iso,
                        "plc_state": r.plc_state,
                        "speed_mps": r.speed_mps,
                        "target_speed_mps": r.target_speed_mps,
                        "pid_cv_pct": r.pid_cv_pct,
                        "pid_error_mps": r.pid_error_mps,
                        "current_a": r.current_a,
                        "temp_c": r.temp_c,
                        "load_kg": r.load_kg,
                        "vibration_mms": r.vibration_mms,
                        "power_kw": r.power_kw,
                        "dispatched_count": r.dispatched_count,
                        "rejected_count": r.rejected_count,
                        "oee_pct": r.oee_pct,
                    }
                    for r in reversed(rows)
                ]

            return self._run_with_failover(_op)
        except Exception:
            return []

    def insert_event(self, evt: Dict[str, Any]) -> None:
        try:
            now_str = _utc_iso()

            def _op(s: Session) -> None:
                s.add(
                    ScadaEventLogRow(
                        event_uid=str(evt.get("id") or f"EVT-{int(time.time() * 1000)}"),
                        timestamp_iso=str(evt.get("timestamp") or now_str),
                        time_short=str(evt.get("time_short") or datetime.now().strftime("%H:%M:%S")),
                        level=str(evt.get("level") or "INFO"),
                        source=str(evt.get("source") or "SCADA"),
                        code=str(evt.get("code") or "EVENT"),
                        message=str(evt.get("message") or ""),
                        plc_state=str(evt.get("state") or "RUNNING"),
                        extra_json=json.dumps(evt.get("extra") or {}, ensure_ascii=False),
                    )
                )
                self._event_write_counter += 1
                if self._event_write_counter % 40 == 0:
                    max_rows = settings.db_max_event_rows
                    total = int(s.scalar(select(func.count()).select_from(ScadaEventLogRow)) or 0)
                    if total > max_rows:
                        cutoff_id = s.scalar(
                            select(ScadaEventLogRow.id)
                            .order_by(ScadaEventLogRow.id.desc())
                            .offset(max_rows)
                            .limit(1)
                        )
                        if cutoff_id is not None:
                            s.execute(
                                delete(ScadaEventLogRow).where(ScadaEventLogRow.id <= cutoff_id)
                            )

            self._run_with_failover(_op)
            self.last_write_at = now_str
        except Exception:
            pass

    def query_events_log(self, limit: int = 100, level: Optional[str] = None) -> List[Dict[str, Any]]:
        safe_limit = max(1, min(500, int(limit)))
        try:
            def _op(s: Session) -> List[Dict[str, Any]]:
                stmt = select(ScadaEventLogRow).order_by(ScadaEventLogRow.id.desc())
                if level:
                    stmt = stmt.where(ScadaEventLogRow.level == level.strip().upper())
                rows = s.scalars(stmt.limit(safe_limit)).all()
                return [
                    {
                        "id": r.event_uid,
                        "timestamp": r.timestamp_iso,
                        "time_short": r.time_short,
                        "level": r.level,
                        "source": r.source,
                        "code": r.code,
                        "message": r.message,
                        "state": r.plc_state,
                    }
                    for r in rows
                ]

            return self._run_with_failover(_op)
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Persistencia de Configuración Clave-Valor, Documentos y Chat IA
    # ------------------------------------------------------------------
    def get_kv_json(self, key: str) -> Optional[Dict[str, Any]]:
        try:
            def _op(s: Session) -> Optional[Dict[str, Any]]:
                row = s.get(AppKvSettingRow, key)
                if not row:
                    return None
                data = json.loads(row.value_json)
                return data if isinstance(data, dict) else None

            return self._run_with_failover(_op)
        except Exception:
            return None

    def set_kv_json(self, key: str, value: Dict[str, Any]) -> None:
        try:
            now_str = _utc_iso()
            encoded = json.dumps(value, ensure_ascii=False)

            def _op(s: Session) -> None:
                row = s.get(AppKvSettingRow, key)
                if row is None:
                    row = AppKvSettingRow(key=key, value_json=encoded, updated_at=now_str)
                    s.add(row)
                else:
                    row.value_json = encoded
                    row.updated_at = now_str

            self._run_with_failover(_op)
            self.last_write_at = now_str
        except Exception:
            pass

    def upsert_rag_document(
        self,
        filename: str,
        title: str,
        content: str,
        builtin: bool = False,
        chunks_count: int = 1,
    ) -> None:
        try:
            now_str = _utc_iso()

            def _op(s: Session) -> None:
                row = s.get(RagDocumentRow, filename)
                if row is None:
                    row = RagDocumentRow(
                        filename=filename,
                        title=title,
                        content=content,
                        builtin=builtin,
                        chunks_count=chunks_count,
                        updated_at=now_str,
                    )
                    s.add(row)
                else:
                    row.title = title
                    row.content = content
                    row.builtin = builtin
                    row.chunks_count = chunks_count
                    row.updated_at = now_str

            self._run_with_failover(_op)
            self.last_write_at = now_str
        except Exception:
            pass

    def delete_rag_document(self, filename: str) -> None:
        try:
            def _op(s: Session) -> None:
                row = s.get(RagDocumentRow, filename)
                if row is not None:
                    s.delete(row)

            self._run_with_failover(_op)
            self.last_write_at = _utc_iso()
        except Exception:
            pass

    def load_all_rag_documents(self) -> List[Dict[str, Any]]:
        try:
            def _op(s: Session) -> List[Dict[str, Any]]:
                rows = s.scalars(select(RagDocumentRow)).all()
                return [
                    {
                        "filename": r.filename,
                        "title": r.title,
                        "content": r.content,
                        "builtin": r.builtin,
                        "chunks_count": r.chunks_count,
                        "updated_at": r.updated_at,
                    }
                    for r in rows
                ]

            return self._run_with_failover(_op)
        except Exception:
            return []

    def insert_chat_turn(self, turn: Dict[str, Any]) -> None:
        try:
            now_str = _utc_iso()
            turn_id = str(turn.get("turn_id") or f"turn-{int(time.time() * 1000)}")

            def _op(s: Session) -> None:
                existing = s.scalar(select(RagChatTurnRow).where(RagChatTurnRow.turn_id == turn_id))
                if existing is not None:
                    return
                s.add(
                    RagChatTurnRow(
                        turn_id=turn_id,
                        timestamp_short=str(turn.get("timestamp") or datetime.now().strftime("%H:%M:%S")),
                        query=str(turn.get("query") or ""),
                        answer=str(turn.get("answer") or ""),
                        provider_used=str(turn.get("provider_used") or "local-rag"),
                        model_used=str(turn.get("model_used") or ""),
                        latency_ms=float(turn.get("latency_ms") or 0.0),
                        active_agents_json=json.dumps(turn.get("active_agents") or [], ensure_ascii=False),
                        sources_json=json.dumps(turn.get("sources") or [], ensure_ascii=False),
                        web_search_json=json.dumps(turn.get("web_search") or {}, ensure_ascii=False),
                        created_at=now_str,
                    )
                )

            self._run_with_failover(_op)
            self.last_write_at = now_str
        except Exception:
            pass

    def load_recent_chat_turns(self, limit: int = 20) -> List[Dict[str, Any]]:
        try:
            def _op(s: Session) -> List[Dict[str, Any]]:
                rows = s.scalars(
                    select(RagChatTurnRow)
                    .order_by(RagChatTurnRow.id.desc())
                    .limit(max(1, min(100, limit)))
                ).all()
                turns: List[Dict[str, Any]] = []
                for r in reversed(rows):
                    turns.append(
                        {
                            "turn_id": r.turn_id,
                            "timestamp": r.timestamp_short,
                            "query": r.query,
                            "answer": r.answer,
                            "provider_used": r.provider_used,
                            "model_used": r.model_used,
                            "latency_ms": r.latency_ms,
                            "active_agents": json.loads(r.active_agents_json or "[]"),
                            "sources": json.loads(r.sources_json or "[]"),
                            "web_search": json.loads(r.web_search_json or "{}"),
                        }
                    )
                return turns

            return self._run_with_failover(_op)
        except Exception:
            return []

    def clear_chat_turns(self) -> None:
        try:
            def _op(s: Session) -> None:
                s.execute(delete(RagChatTurnRow))

            self._run_with_failover(_op)
            self.last_write_at = _utc_iso()
        except Exception:
            pass
>>>>>>> 6b869b7 (Initial commit: S_F_T)
