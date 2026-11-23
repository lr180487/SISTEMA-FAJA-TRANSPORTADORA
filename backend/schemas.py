<<<<<<< HEAD
"""Compatibilidad: esquemas API en backend.api.schemas."""
from backend.api.schemas import *  # noqa: F401,F403
=======
from __future__ import annotations

from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field


# ------------------------------------------------------------------
# Contratos de Control de Faja y Simulación SCADA
# ------------------------------------------------------------------
class ControlCommandRequest(BaseModel):
    action: str = Field(
        ...,
        min_length=1,
        description=(
            "Acción operativa: start | pause | stop | emergency_stop | reset_fault | "
            "set_speed | set_direction | set_auto_feed | set_feed_rate | set_auto_divert | "
            "spawn_item | clear_belt | reset_counters | inject_fault | set_pid"
        ),
    )
    value: Optional[Any] = Field(default=None, description="Valor principal del comando")
    source: str = Field(default="HMI-WEB", description="Origen del comando")
    params: Dict[str, Any] = Field(default_factory=dict, description="Parámetros adicionales")


# ------------------------------------------------------------------
# Contratos del Controlador PID Individual (P · I · D)
# ------------------------------------------------------------------
class PidConfigRequest(BaseModel):
    mode: Optional[Literal["AUTO", "MANUAL", "auto", "manual"]] = None
    kp: Optional[float] = Field(default=None, ge=0.0, le=150.0)
    ki: Optional[float] = Field(default=None, ge=0.0, le=120.0)
    kd: Optional[float] = Field(default=None, ge=0.0, le=50.0)
    p_enabled: Optional[bool] = None
    i_enabled: Optional[bool] = None
    d_enabled: Optional[bool] = None
    filter_tf: Optional[float] = Field(default=None, ge=0.02, le=1.0)
    cv_min: Optional[float] = Field(default=None, ge=0.0, le=60.0)
    cv_max: Optional[float] = Field(default=None, ge=20.0, le=100.0)
    manual_cv: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    setpoint_mps: Optional[float] = Field(default=None, ge=0.2, le=3.0)
    disturbance_pct: Optional[float] = Field(default=None, ge=0.0, le=45.0)
    preset: Optional[str] = None
    reset_integral: bool = False
    reset_metrics: bool = False
    pulse_disturbance: bool = False
    source: str = "PID-TUNER"


# ------------------------------------------------------------------
# Contratos de Base de Datos (PostgreSQL -> Fallback SQLite)
# ------------------------------------------------------------------
class DatabaseReconnectRequest(BaseModel):
    database_url: Optional[str] = Field(
        default=None,
        description="URL PostgreSQL opcional para probar/reconectar (si se omite, recarga desde `.env`).",
    )


# ------------------------------------------------------------------
# Contratos del Asistente Inteligente y Gestión Documental
# ------------------------------------------------------------------
class RagAskRequest(BaseModel):
    query: str = Field(..., min_length=1)
    preferred_provider: Optional[str] = "auto"
    web_search_mode: Optional[str] = "always"


class RagAddTextDocumentRequest(BaseModel):
    title: str = Field(default="Nota Operativa")
    content: str = Field(..., min_length=1)
    filename: Optional[str] = None


class RagUploadFileRequest(BaseModel):
    filename: str = Field(..., min_length=1)
    content_base64: str = Field(..., min_length=1)


class RagWebSearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    save_to_rag: bool = False


class RagLlmConfigRequest(BaseModel):
    preferred_provider: Optional[str] = None
    openai_api_key: Optional[str] = None
    openai_base_url: Optional[str] = None
    openai_model: Optional[str] = None
    groq_api_key: Optional[str] = None
    groq_base_url: Optional[str] = None
    groq_model: Optional[str] = None
    gemini_api_key: Optional[str] = None
    gemini_model: Optional[str] = None
    ollama_base_url: Optional[str] = None
    ollama_model: Optional[str] = None
    web_search_mode: Optional[str] = None
    tavily_api_key: Optional[str] = None
    tavily_search_depth: Optional[str] = None
>>>>>>> 6b869b7 (Initial commit: S_F_T)
