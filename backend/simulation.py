<<<<<<< HEAD
from backend.domain.simulation import *  # noqa: F401,F403
=======
from __future__ import annotations

import csv
import io
import math
import random
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional


def iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")


@dataclass
class BeltItem:
    id: str
    category: str  # "light" | "standard" | "heavy" | "defective"
    label: str
    weight_kg: float
    length_m: float
    position_m: float
    color: str
    is_defective: bool = False
    weighed: bool = False
    inspected: bool = False
    created_at: float = field(default_factory=time.time)


class ConveyorSimulator:
    """
    Motor físico de 2.º orden + Autómata PLC + Controlador PID Discreto en Tiempo Real
    para Faja Transportadora Industrial de 10.0 metros (Modelo FT-400X, Motor 5.5 kW).
    """

    BELT_LENGTH_M = 10.0
    PULLEY_DIAMETER_M = 0.32
    MAX_CAPACITY_KG = 120.0
    MAX_SPEED_MPS = 3.0
    MIN_SPEED_MPS = 0.2

    # Posiciones físicas de sensores sobre la faja (en metros)
    SENSOR_PE01_POS = 1.2   # Fotocélula de entrada
    SENSOR_LC02_POS = 4.0   # Celda de carga dinámica (plataforma 3.3m - 4.7m)
    SENSOR_VS03_POS = 6.8   # Cámara de visión artificial + desviador neumático
    SENSOR_IN04_POS = 9.2   # Sensor inductivo de salida / despacho

    PID_PRESETS = {
        "balanced": {
            "name": "Óptimo Industrial (Ziegler-Nichols Mod.)",
            "kp": 36.0,
            "ki": 26.0,
            "kd": 4.2,
            "p_enabled": True,
            "i_enabled": True,
            "d_enabled": True,
            "filter_tf": 0.12,
        },
        "aggressive": {
            "name": "Subamortiguado / Rápido (Con Oscilación)",
            "kp": 88.0,
            "ki": 68.0,
            "kd": 0.4,
            "p_enabled": True,
            "i_enabled": True,
            "d_enabled": True,
            "filter_tf": 0.08,
        },
        "smooth": {
            "name": "Sobreamortiguado / Suave",
            "kp": 18.0,
            "ki": 11.0,
            "kd": 6.5,
            "p_enabled": True,
            "i_enabled": True,
            "d_enabled": True,
            "filter_tf": 0.18,
        },
        "p_only": {
            "name": "Solo Proporcional (Muestra Error Estacionario)",
            "kp": 34.0,
            "ki": 0.0,
            "kd": 0.0,
            "p_enabled": True,
            "i_enabled": False,
            "d_enabled": False,
            "filter_tf": 0.12,
        },
        "pi_classic": {
            "name": "Control PI Clásico Industrial",
            "kp": 32.0,
            "ki": 22.0,
            "kd": 0.0,
            "p_enabled": True,
            "i_enabled": True,
            "d_enabled": False,
            "filter_tf": 0.12,
        },
    }

    ITEM_PROFILES = {
        "light": {
            "label": "Ligera",
            "weight_range": (2.2, 4.8),
            "length_m": 0.42,
            "color": "#2563EB",
            "is_defective": False,
        },
        "standard": {
            "label": "Estándar",
            "weight_range": (7.5, 13.5),
            "length_m": 0.50,
            "color": "#059669",
            "is_defective": False,
        },
        "heavy": {
            "label": "Pesada",
            "weight_range": (16.5, 25.0),
            "length_m": 0.58,
            "color": "#D97706",
            "is_defective": False,
        },
        "defective": {
            "label": "Defecto QA",
            "weight_range": (5.0, 14.0),
            "length_m": 0.46,
            "color": "#DC2626",
            "is_defective": True,
        },
    }

    def __init__(self, event_hook: Optional[Callable[[Dict[str, Any]], None]] = None) -> None:
        self._lock = threading.RLock()
        self._event_hook = event_hook

        # Estado principal del PLC: RUNNING | PAUSED | STOPPED | FAULT | E_STOP
        self.state: str = "RUNNING"
        self.direction: str = "FORWARD"  # FORWARD | REVERSE
        self.target_speed_mps: float = 1.40
        self.actual_speed_mps: float = 1.40
        self._drive_state_mps: float = 1.56  # Estado interno par electromagnético VFD

        # ------------------------------------------------------------------
        # Parámetros y Estados Individuales del Controlador PID Discreto
        # ------------------------------------------------------------------
        self.pid_mode: str = "AUTO"  # "AUTO" (Lazo cerrado PID) | "MANUAL" (Lazo abierto CV%)
        self.pid_preset: str = "balanced"
        self.pid_kp: float = 36.0
        self.pid_ki: float = 26.0
        self.pid_kd: float = 4.2
        self.pid_p_enabled: bool = True
        self.pid_i_enabled: bool = True
        self.pid_d_enabled: bool = True
        self.pid_filter_tf: float = 0.12  # Constante filtro derivativo (s)
        self.pid_cv_min: float = 0.0
        self.pid_cv_max: float = 100.0
        self.pid_manual_cv: float = 52.0  # % salida manual en lazo abierto

        # Estados dinámicos calculados en cada ciclo del PID
        self.pid_error: float = 0.0
        self._pid_prev_error: float = 0.0
        self.pid_p_term: float = 0.0
        self.pid_i_term: float = 52.0  # Inicializado sin salto (bumpless)
        self.pid_d_term: float = 0.0
        self.pid_cv_pct: float = 52.0
        self.pid_iae: float = 0.0      # Integral del Error Absoluto
        self.pid_overshoot_pct: float = 0.0
        self._last_sp_for_overshoot: float = 1.40
        self._peak_pv_since_sp: float = 1.40
        self.load_disturbance_pct: float = 0.0  # Freno/perturbación externa (0-45%)
        self._pulse_disturbance_until: float = 0.0

        # Configuración de alimentación y control de calidad
        self.auto_feed: bool = True
        self.feed_rate_per_min: float = 16.0
        self.auto_divert_defective: bool = True
        self.defect_probability: float = 0.12

        # Variables eléctricas, térmicas y mecánicas
        self.ambient_temp_c: float = 24.0
        self.motor_temp_c: float = 36.8
        self.motor_current_a: float = 4.6
        self.motor_voltage_v: float = 380.0
        self.power_kw: float = 1.95
        self.energy_kwh: float = 0.420
        self.vfd_freq_hz: float = 39.0
        self.pulley_rpm: float = 83.5
        self.vibration_mms: float = 1.45
        self.belt_tension_pct: float = 97.8
        self.belt_offset_m: float = 0.0

        # Sensores e I/O industriales
        self.sensor_pe01_entry: bool = False
        self.sensor_lc02_active: bool = False
        self.sensor_lc02_weight_kg: float = 0.0
        self.last_weighed_kg: float = 0.0
        self.sensor_vs03_vision: bool = False
        self.sensor_vs03_defect_flag: bool = False
        self.sensor_in04_exit: bool = False
        self.actuator_diverter_active: bool = False
        self.diverter_hold_until: float = 0.0

        # Gestión de fallas activas
        self.active_fault_code: Optional[str] = None
        self.active_fault_desc: Optional[str] = None

        # Contadores de producción y OEE
        self.item_seq: int = 0
        self.dispatched_count: int = 18
        self.rejected_count: int = 2
        self.spawned_count: int = 22
        self.total_weight_dispatched_kg: float = 186.4

        # Tiempos acumulados para OEE
        self.started_epoch: float = time.time()
        self.total_elapsed_s: float = 120.0
        self.run_time_s: float = 115.0
        self.fault_time_s: float = 0.0

        self._last_tick: float = time.time()
        self._last_spawn_ts: float = time.time() - 1.5
        self._last_history_ts: float = 0.0
        self._last_pid_sample_ts: float = 0.0

        # Elementos actualmente sobre la faja
        self.items: List[BeltItem] = []

        # Buffers circulares para gráficas e historial
        self.history: deque = deque(maxlen=180)
        self.pid_history: deque = deque(maxlen=140)  # Osciloscopio PID alta resolución (10 Hz)
        self.events: deque = deque(maxlen=100)
        self.diverted_recent: deque = deque(maxlen=8)

        self._seed_initial_state()

    def restore_persisted_state(self, saved: Optional[Dict[str, Any]]) -> None:
        """Restaura desde la base de datos (PostgreSQL/SQLite) el estado operativo y PID guardado."""
        if not saved or not isinstance(saved, dict):
            return
        with self._lock:
            saved_state = str(saved.get("plc_state") or "RUNNING").upper()
            if saved_state in ("RUNNING", "PAUSED", "STOPPED"):
                self.state = saved_state
            else:
                self.state = "STOPPED"

            saved_dir = str(saved.get("direction") or "FORWARD").upper()
            if saved_dir in ("FORWARD", "REVERSE"):
                self.direction = saved_dir

            if saved.get("target_speed_mps") is not None:
                self.target_speed_mps = round(
                    min(self.MAX_SPEED_MPS, max(self.MIN_SPEED_MPS, float(saved["target_speed_mps"]))),
                    2,
                )
            if saved.get("auto_feed") is not None:
                self.auto_feed = bool(saved["auto_feed"])
            if saved.get("feed_rate_per_min") is not None:
                self.feed_rate_per_min = round(min(45.0, max(3.0, float(saved["feed_rate_per_min"]))), 1)
            if saved.get("auto_divert_defective") is not None:
                self.auto_divert_defective = bool(saved["auto_divert_defective"])

            if saved.get("pid_mode") in ("AUTO", "MANUAL"):
                self.pid_mode = str(saved["pid_mode"])
            if saved.get("pid_preset"):
                self.pid_preset = str(saved["pid_preset"])
            if saved.get("pid_kp") is not None:
                self.pid_kp = round(min(150.0, max(0.0, float(saved["pid_kp"]))), 2)
            if saved.get("pid_ki") is not None:
                self.pid_ki = round(min(120.0, max(0.0, float(saved["pid_ki"]))), 2)
            if saved.get("pid_kd") is not None:
                self.pid_kd = round(min(50.0, max(0.0, float(saved["pid_kd"]))), 2)
            if saved.get("pid_p_enabled") is not None:
                self.pid_p_enabled = bool(saved["pid_p_enabled"])
            if saved.get("pid_i_enabled") is not None:
                self.pid_i_enabled = bool(saved["pid_i_enabled"])
            if saved.get("pid_d_enabled") is not None:
                self.pid_d_enabled = bool(saved["pid_d_enabled"])
            if saved.get("pid_filter_tf") is not None:
                self.pid_filter_tf = round(min(1.0, max(0.02, float(saved["pid_filter_tf"]))), 3)
            if saved.get("pid_cv_min") is not None:
                self.pid_cv_min = round(min(60.0, max(0.0, float(saved["pid_cv_min"]))), 1)
            if saved.get("pid_cv_max") is not None:
                self.pid_cv_max = round(min(100.0, max(20.0, float(saved["pid_cv_max"]))), 1)
            if saved.get("pid_manual_cv") is not None:
                self.pid_manual_cv = round(min(100.0, max(0.0, float(saved["pid_manual_cv"]))), 1)

            if saved.get("dispatched_count") is not None:
                self.dispatched_count = max(0, int(saved["dispatched_count"]))
            if saved.get("rejected_count") is not None:
                self.rejected_count = max(0, int(saved["rejected_count"]))
            if saved.get("total_weight_dispatched_kg") is not None:
                self.total_weight_dispatched_kg = round(max(0.0, float(saved["total_weight_dispatched_kg"])), 2)
            if saved.get("energy_kwh") is not None:
                self.energy_kwh = round(max(0.0, float(saved["energy_kwh"])), 3)

    def _seed_initial_state(self) -> None:
        initial_specs = [
            ("standard", 2.1),
            ("heavy", 5.3),
            ("light", 8.1),
        ]
        for cat, pos in initial_specs:
            item = self._build_item(cat, position_m=pos)
            if pos > self.SENSOR_LC02_POS:
                item.weighed = True
                self.last_weighed_kg = item.weight_kg
            if pos > self.SENSOR_VS03_POS:
                item.inspected = True
            self.items.append(item)

        now = time.time()
        for i in range(30, 0, -1):
            ts_str = datetime.fromtimestamp(now - i).strftime("%H:%M:%S")
            spd = round(1.40 + math.sin(i * 0.3) * 0.02, 2)
            load = round(28.0 + math.cos(i * 0.25) * 6.5, 1)
            curr = round(2.8 + 0.065 * load + 1.1 * spd, 2)
            temp = round(35.5 + (30 - i) * 0.04, 1)
            self.history.append(
                {
                    "timestamp": ts_str,
                    "epoch_ms": int((now - i) * 1000),
                    "speed_mps": spd,
                    "target_speed_mps": 1.40,
                    "current_a": curr,
                    "temp_c": temp,
                    "load_kg": load,
                    "vibration_mms": round(1.35 + math.sin(i * 0.5) * 0.12, 2),
                    "power_kw": round((curr * 380.0 * 1.732 * 0.86) / 1000.0, 2),
                    "dispatched_count": max(0, self.dispatched_count - (i // 3)),
                    "oee_pct": 94.2,
                    "pid_cv_pct": 52.1,
                }
            )

        # Sembrar traza inicial de 8 segundos para el osciloscopio PID (10 Hz)
        for j in range(80, 0, -1):
            t_pt = now - j * 0.1
            err_sim = 0.015 * math.sin(j * 0.22)
            pv_sim = round(1.40 - err_sim, 3)
            p_sim = round(self.pid_kp * err_sim, 2)
            i_sim = round(51.8 + 0.4 * math.cos(j * 0.15), 2)
            d_sim = round(-0.25 * math.cos(j * 0.22), 2)
            cv_sim = round(min(100.0, max(0.0, p_sim + i_sim + d_sim)), 2)
            self.pid_history.append(
                {
                    "timestamp": datetime.fromtimestamp(t_pt).strftime("%H:%M:%S.%f")[:-5],
                    "sp": 1.40,
                    "pv": pv_sim,
                    "error": round(err_sim, 3),
                    "cv_pct": cv_sim,
                    "p_term": p_sim,
                    "i_term": i_sim,
                    "d_term": d_sim,
                    "disturbance_pct": 0.0,
                }
            )

        self._record_event(
            level="INFO",
            source="PLC-PID",
            code="SYS_BOOT",
            message="SCADA PID + Lazo Cerrado PID inicializados (SP=1.40 m/s, Kp=36, Ki=26, Kd=4.2).",
            notify_webhook=False,
        )

    def _build_item(self, category: str, position_m: Optional[float] = None) -> BeltItem:
        if category not in self.ITEM_PROFILES:
            category = "standard"
        prof = self.ITEM_PROFILES[category]
        self.item_seq += 1
        w_min, w_max = prof["weight_range"]
        weight = round(random.uniform(w_min, w_max), 2)
        if position_m is None:
            position_m = 0.25 if self.direction == "FORWARD" else (self.BELT_LENGTH_M - 0.25)
        return BeltItem(
            id=f"PKG-{1000 + self.item_seq}",
            category=category,
            label=prof["label"],
            weight_kg=weight,
            length_m=prof["length_m"],
            position_m=round(position_m, 3),
            color=prof["color"],
            is_defective=prof["is_defective"],
        )

    def _record_event(
        self,
        level: str,
        source: str,
        code: str,
        message: str,
        extra: Optional[Dict[str, Any]] = None,
        notify_webhook: bool = True,
    ) -> Dict[str, Any]:
        evt = {
            "id": f"EVT-{int(time.time() * 1000)}-{random.randint(10, 99)}",
            "timestamp": iso_now(),
            "time_short": datetime.now().strftime("%H:%M:%S"),
            "level": level,
            "source": source,
            "code": code,
            "message": message,
            "state": self.state,
            "extra": extra or {},
        }
        self.events.appendleft(evt)
        if notify_webhook and self._event_hook is not None:
            try:
                self._event_hook(evt)
            except Exception:
                pass
        return evt

    # ------------------------------------------------------------------
    # Ciclo de actualización física + Controlador PID en tiempo real (20 Hz)
    # ------------------------------------------------------------------
    def step(self) -> None:
        with self._lock:
            now = time.time()
            dt = min(max(now - self._last_tick, 0.005), 0.25)
            self._last_tick = now

            self.total_elapsed_s += dt
            if self.state == "RUNNING":
                self.run_time_s += dt
            elif self.state in ("FAULT", "E_STOP"):
                self.fault_time_s += dt

            # Fin automático de golpe transitorio de carga si expiró
            if self._pulse_disturbance_until > 0 and now >= self._pulse_disturbance_until:
                self._pulse_disturbance_until = 0.0
                self.load_disturbance_pct = 0.0

            total_load_kg = sum(it.weight_kg for it in self.items)

            # ------------------------------------------------------------------
            # 1. Algoritmo PID Discreto + Dinámica Electromecánica de 2.º Orden
            # ------------------------------------------------------------------
            if self.state == "RUNNING":
                sp = self.target_speed_mps
                pv = self.actual_speed_mps
                err = sp - pv
                self.pid_error = round(err, 4)
                self.pid_iae = round(min(9999.0, self.pid_iae + abs(err) * dt), 3)

                if self.pid_mode == "AUTO":
                    # Término Proporcional (P)
                    p_out = (self.pid_kp * err) if self.pid_p_enabled else 0.0

                    # Término Derivativo filtrado (D) con filtro de primer orden Tf
                    if self.pid_d_enabled and self.pid_kd > 0.0:
                        raw_deriv = (err - self._pid_prev_error) / dt
                        raw_d = self.pid_kd * raw_deriv
                        alpha = dt / (max(0.02, self.pid_filter_tf) + dt)
                        d_out = self.pid_d_term + alpha * (raw_d - self.pid_d_term)
                        d_out = max(-45.0, min(45.0, d_out))
                    else:
                        d_out = 0.0

                    # Término Integral (I) con Anti-Windup por clamping dinámico
                    if self.pid_i_enabled and self.pid_ki > 0.0:
                        candidate_i = self.pid_i_term + (self.pid_ki * err * dt)
                        # Anti-windup: limitar acumulador para no saturar indefinidamente
                        i_min = self.pid_cv_min - min(0.0, p_out)
                        i_max = self.pid_cv_max - max(0.0, p_out)
                        self.pid_i_term = max(min(candidate_i, max(i_min, i_max)), min(i_min, i_max))
                    elif not self.pid_i_enabled:
                        self.pid_i_term = 0.0

                    raw_cv = p_out + self.pid_i_term + d_out
                    cv_clamped = max(self.pid_cv_min, min(self.pid_cv_max, raw_cv))

                    self.pid_p_term = round(p_out, 2)
                    self.pid_i_term = round(self.pid_i_term, 2)
                    self.pid_d_term = round(d_out, 2)
                    self.pid_cv_pct = round(cv_clamped, 2)
                    # Mantener sincronizado manual_cv para transferencia sin salto (bumpless)
                    self.pid_manual_cv = self.pid_cv_pct
                else:
                    # Modo MANUAL (Lazo Abierto): el operador fija directamente % CV del VFD
                    cv_clamped = max(self.pid_cv_min, min(self.pid_cv_max, self.pid_manual_cv))
                    self.pid_p_term = 0.0
                    self.pid_d_term = 0.0
                    self.pid_i_term = round(cv_clamped, 2)  # Seguimiento bumpless
                    self.pid_cv_pct = round(cv_clamped, 2)

                self._pid_prev_error = err

                # Planta de 2.º orden: Etapa 1 (respuesta par VFD tau_e=0.18s) + Etapa 2 (inercia mecánica tau_m=0.62s)
                vfd_no_load_mps = (self.pid_cv_pct / 100.0) * self.MAX_SPEED_MPS
                tau_e = 0.18
                self._drive_state_mps += ((vfd_no_load_mps - self._drive_state_mps) / tau_e) * dt

                # Caída de velocidad por carga mecánica sobre banda y freno perturbador externo
                load_droop_mps = (0.0068 * total_load_kg) + ((self.load_disturbance_pct / 100.0) * 1.35)
                mech_target_mps = max(0.0, self._drive_state_mps - load_droop_mps)
                tau_m = 0.62
                new_pv = self.actual_speed_mps + ((mech_target_mps - self.actual_speed_mps) / tau_m) * dt
                # Pequeño ruido realista de encoder incremental
                encoder_ripple = random.uniform(-0.0025, 0.0025) if new_pv > 0.05 else 0.0
                self.actual_speed_mps = max(0.0, min(self.MAX_SPEED_MPS * 1.15, new_pv + encoder_ripple))

                # Cálculo de sobreimpulso máximo (Overshoot %) respecto a la consigna vigente
                if abs(sp - self._last_sp_for_overshoot) > 0.01:
                    self._last_sp_for_overshoot = sp
                    self._peak_pv_since_sp = self.actual_speed_mps
                    self.pid_overshoot_pct = 0.0
                else:
                    if self.actual_speed_mps > self._peak_pv_since_sp:
                        self._peak_pv_since_sp = self.actual_speed_mps
                    if sp > 0.1 and self._peak_pv_since_sp > sp:
                        self.pid_overshoot_pct = round(((self._peak_pv_since_sp - sp) / sp) * 100.0, 1)

            elif self.state in ("E_STOP", "FAULT"):
                self.pid_cv_pct = 0.0
                self.pid_p_term = 0.0
                self.pid_d_term = 0.0
                self._drive_state_mps = 0.0
                self.actual_speed_mps = max(0.0, self.actual_speed_mps - 5.5 * dt)
                self.pid_error = round(0.0 - self.actual_speed_mps, 4)
            else:
                # PAUSED o STOPPED
                self.pid_cv_pct = 0.0
                self.pid_p_term = 0.0
                self.pid_d_term = 0.0
                self._drive_state_mps = max(0.0, self._drive_state_mps - 2.4 * dt)
                self.actual_speed_mps = max(0.0, self.actual_speed_mps - 2.0 * dt)
                self.pid_error = 0.0

            self.actual_speed_mps = round(max(0.0, self.actual_speed_mps), 3)

            # 2. Alimentación automática de paquetes
            if self.state == "RUNNING" and self.auto_feed and self.actual_speed_mps > 0.15:
                interval_s = 60.0 / max(1.0, self.feed_rate_per_min)
                if (now - self._last_spawn_ts) >= interval_s and len(self.items) < 16:
                    spawn_pos = 0.25 if self.direction == "FORWARD" else (self.BELT_LENGTH_M - 0.25)
                    clearance_ok = all(abs(it.position_m - spawn_pos) > 0.85 for it in self.items)
                    if clearance_ok:
                        r = random.random()
                        if r < self.defect_probability:
                            cat = "defective"
                        elif r < 0.40:
                            cat = "light"
                        elif r < 0.78:
                            cat = "standard"
                        else:
                            cat = "heavy"
                        new_item = self._build_item(cat, position_m=spawn_pos)
                        self.items.append(new_item)
                        self.spawned_count += 1
                        self._last_spawn_ts = now

            # 3. Cinemática de la banda y desplazamiento de paquetes
            dir_sign = 1.0 if self.direction == "FORWARD" else -1.0
            delta_x = self.actual_speed_mps * dt * dir_sign
            self.belt_offset_m = (self.belt_offset_m + delta_x) % 1.0

            remaining_items: List[BeltItem] = []
            pe01 = False
            lc02 = False
            lc02_weight = 0.0
            vs03 = False
            vs03_defect = False
            in04 = False

            for item in self.items:
                item.position_m += delta_x
                half_len = item.length_m * 0.5

                if abs(item.position_m - self.SENSOR_PE01_POS) <= (half_len + 0.18):
                    pe01 = True

                if abs(item.position_m - self.SENSOR_LC02_POS) <= 0.65:
                    lc02 = True
                    lc02_weight += item.weight_kg
                    if not item.weighed:
                        item.weighed = True
                        self.last_weighed_kg = item.weight_kg

                if abs(item.position_m - self.SENSOR_VS03_POS) <= (half_len + 0.20):
                    vs03 = True
                    if item.is_defective:
                        vs03_defect = True
                    if not item.inspected:
                        item.inspected = True
                        if item.is_defective and self.auto_divert_defective:
                            self.actuator_diverter_active = True
                            self.diverter_hold_until = now + 0.65
                            self.rejected_count += 1
                            self.diverted_recent.appendleft(
                                {
                                    "id": item.id,
                                    "weight_kg": item.weight_kg,
                                    "time": datetime.now().strftime("%H:%M:%S"),
                                }
                            )
                            self._record_event(
                                level="WARNING",
                                source="VISION-VS03",
                                code="QA_REJECT",
                                message=f"Unidad {item.id} ({item.weight_kg} kg) desviada por control de calidad.",
                                extra={"item_id": item.id, "weight_kg": item.weight_kg},
                            )
                            continue

                if abs(item.position_m - self.SENSOR_IN04_POS) <= (half_len + 0.18):
                    in04 = True

                if self.direction == "FORWARD" and item.position_m >= self.BELT_LENGTH_M:
                    self.dispatched_count += 1
                    self.total_weight_dispatched_kg = round(
                        self.total_weight_dispatched_kg + item.weight_kg, 2
                    )
                    continue
                if self.direction == "REVERSE" and item.position_m <= 0.0:
                    self.dispatched_count += 1
                    self.total_weight_dispatched_kg = round(
                        self.total_weight_dispatched_kg + item.weight_kg, 2
                    )
                    continue

                remaining_items.append(item)

            self.items = remaining_items

            self.sensor_pe01_entry = pe01
            self.sensor_lc02_active = lc02
            self.sensor_lc02_weight_kg = round(lc02_weight, 2)
            self.sensor_vs03_vision = vs03
            self.sensor_vs03_defect_flag = vs03_defect
            self.sensor_in04_exit = in04
            if now > self.diverter_hold_until:
                self.actuator_diverter_active = False

            # 4. Modelo eléctrico y térmico del motor + VFD
            total_load_kg = sum(it.weight_kg for it in self.items)

            if total_load_kg > self.MAX_CAPACITY_KG and self.state == "RUNNING":
                self._trigger_fault_locked(
                    code="FLT_OVERWEIGHT",
                    desc=f"Sobrecarga mecánica en banda ({total_load_kg:.1f} kg > {self.MAX_CAPACITY_KG:.0f} kg máx).",
                )

            if self.actual_speed_mps > 0.01 or self.pid_cv_pct > 1.0:
                circumference = math.pi * self.PULLEY_DIAMETER_M
                self.pulley_rpm = round((self.actual_speed_mps / circumference) * 60.0, 1)
                self.vfd_freq_hz = round(0.75 * self.pid_cv_pct, 1)  # 0-100% CV -> 0-75 Hz VFD
                noise_i = random.uniform(-0.05, 0.05)
                disturbance_amps = (self.load_disturbance_pct / 100.0) * 4.8
                self.motor_current_a = round(
                    max(
                        1.2,
                        2.55
                        + 0.068 * total_load_kg
                        + 0.025 * self.pid_cv_pct
                        + disturbance_amps
                        + noise_i,
                    ),
                    2,
                )
                v_eff = self.motor_voltage_v * min(1.0, 0.45 + 0.55 * (self.vfd_freq_hz / 50.0))
                self.power_kw = round((1.732 * v_eff * self.motor_current_a * 0.86) / 1000.0, 2)
                self.energy_kwh = round(self.energy_kwh + (self.power_kw * dt / 3600.0), 4)

                base_vib = 0.95 + 0.55 * self.actual_speed_mps + 0.012 * total_load_kg + 0.02 * self.load_disturbance_pct
                if self.active_fault_code == "FLT_MECH_JAM":
                    base_vib += 6.2
                self.vibration_mms = round(base_vib + random.uniform(-0.08, 0.08), 2)
                self.belt_tension_pct = round(
                    min(100.0, max(82.0, 96.5 + 0.025 * total_load_kg + random.uniform(-0.15, 0.15))),
                    1,
                )
            else:
                self.pulley_rpm = 0.0
                self.vfd_freq_hz = 0.0
                self.motor_current_a = 0.15 if self.state != "E_STOP" else 0.0
                self.power_kw = 0.04 if self.state != "E_STOP" else 0.0
                self.vibration_mms = round(0.18 + random.uniform(-0.03, 0.03), 2)
                self.belt_tension_pct = 95.0

            target_temp = self.ambient_temp_c + (self.motor_current_a ** 1.48) * 1.15
            if self.active_fault_code == "FLT_OVERTEMP":
                target_temp = 89.5
            thermal_tau = 22.0
            self.motor_temp_c = round(
                self.motor_temp_c + ((target_temp - self.motor_temp_c) / thermal_tau) * dt,
                2,
            )

            # 5. Muestreo rápido 10 Hz para el Osciloscopio del Controlador PID
            if (now - self._last_pid_sample_ts) >= 0.10:
                self._last_pid_sample_ts = now
                self.pid_history.append(
                    {
                        "timestamp": datetime.now().strftime("%H:%M:%S.%f")[:-5],
                        "sp": round(self.target_speed_mps if self.state == "RUNNING" else 0.0, 3),
                        "pv": round(self.actual_speed_mps, 3),
                        "error": round(self.pid_error, 3),
                        "cv_pct": self.pid_cv_pct,
                        "p_term": self.pid_p_term,
                        "i_term": self.pid_i_term,
                        "d_term": self.pid_d_term,
                        "disturbance_pct": round(self.load_disturbance_pct, 1),
                    }
                )

            # 6. Muestreo general 1 Hz para tendencias globales
            if (now - self._last_history_ts) >= 1.0:
                self._last_history_ts = now
                oee_metrics = self._compute_oee_locked()
                self.history.append(
                    {
                        "timestamp": datetime.now().strftime("%H:%M:%S"),
                        "epoch_ms": int(now * 1000),
                        "speed_mps": round(self.actual_speed_mps, 2),
                        "target_speed_mps": round(self.target_speed_mps, 2),
                        "current_a": self.motor_current_a,
                        "temp_c": round(self.motor_temp_c, 1),
                        "load_kg": round(total_load_kg, 1),
                        "vibration_mms": self.vibration_mms,
                        "power_kw": self.power_kw,
                        "dispatched_count": self.dispatched_count,
                        "oee_pct": oee_metrics["oee_pct"],
                        "pid_cv_pct": self.pid_cv_pct,
                    }
                )

    def _compute_oee_locked(self) -> Dict[str, float]:
        availability = min(1.0, max(0.0, self.run_time_s / max(1.0, self.total_elapsed_s)))
        nominal_ref = 1.50
        perf_base = (self.actual_speed_mps / nominal_ref) if self.state == "RUNNING" else 0.88
        performance = min(1.0, max(0.45, 0.72 + 0.26 * min(1.1, perf_base)))
        total_processed = self.dispatched_count + self.rejected_count
        quality = (self.dispatched_count / total_processed) if total_processed > 0 else 1.0
        oee = availability * performance * quality
        return {
            "availability_pct": round(availability * 100.0, 1),
            "performance_pct": round(performance * 100.0, 1),
            "quality_pct": round(quality * 100.0, 1),
            "oee_pct": round(oee * 100.0, 1),
        }

    def _trigger_fault_locked(self, code: str, desc: str, source: str = "PLC-SAFETY") -> None:
        self.state = "FAULT"
        self.active_fault_code = code
        self.active_fault_desc = desc
        self._record_event(
            level="CRITICAL",
            source=source,
            code=code,
            message=desc,
            extra={"fault_code": code},
        )

    # ------------------------------------------------------------------
    # Configuración individual y pruebas dinámicas del Controlador PID
    # ------------------------------------------------------------------
    def update_pid_config(
        self,
        *,
        mode: Optional[str] = None,
        kp: Optional[float] = None,
        ki: Optional[float] = None,
        kd: Optional[float] = None,
        p_enabled: Optional[bool] = None,
        i_enabled: Optional[bool] = None,
        d_enabled: Optional[bool] = None,
        filter_tf: Optional[float] = None,
        cv_min: Optional[float] = None,
        cv_max: Optional[float] = None,
        manual_cv: Optional[float] = None,
        setpoint_mps: Optional[float] = None,
        disturbance_pct: Optional[float] = None,
        preset: Optional[str] = None,
        reset_integral: bool = False,
        reset_metrics: bool = False,
        pulse_disturbance: bool = False,
        source: str = "PID-TUNER",
    ) -> Dict[str, Any]:
        with self._lock:
            changes: List[str] = []

            if preset and preset in self.PID_PRESETS:
                p_cfg = self.PID_PRESETS[preset]
                self.pid_preset = preset
                self.pid_kp = p_cfg["kp"]
                self.pid_ki = p_cfg["ki"]
                self.pid_kd = p_cfg["kd"]
                self.pid_p_enabled = p_cfg["p_enabled"]
                self.pid_i_enabled = p_cfg["i_enabled"]
                self.pid_d_enabled = p_cfg["d_enabled"]
                self.pid_filter_tf = p_cfg["filter_tf"]
                self.pid_mode = "AUTO"
                changes.append(f"Preset '{p_cfg['name']}'")

            if mode is not None:
                m_up = mode.strip().upper()
                if m_up in ("AUTO", "MANUAL"):
                    self.pid_mode = m_up
                    changes.append(f"Modo={m_up}")

            manual_gain_touched = any(
                v is not None for v in (kp, ki, kd, p_enabled, i_enabled, d_enabled)
            )
            if manual_gain_touched and not preset:
                self.pid_preset = "custom"

            if kp is not None:
                self.pid_kp = round(min(150.0, max(0.0, float(kp))), 2)
                changes.append(f"Kp={self.pid_kp}")
            if ki is not None:
                self.pid_ki = round(min(120.0, max(0.0, float(ki))), 2)
                changes.append(f"Ki={self.pid_ki}")
            if kd is not None:
                self.pid_kd = round(min(50.0, max(0.0, float(kd))), 2)
                changes.append(f"Kd={self.pid_kd}")

            if p_enabled is not None:
                self.pid_p_enabled = bool(p_enabled)
                changes.append(f"P={'ON' if self.pid_p_enabled else 'OFF'}")
            if i_enabled is not None:
                self.pid_i_enabled = bool(i_enabled)
                if not self.pid_i_enabled:
                    self.pid_i_term = 0.0
                changes.append(f"I={'ON' if self.pid_i_enabled else 'OFF'}")
            if d_enabled is not None:
                self.pid_d_enabled = bool(d_enabled)
                if not self.pid_d_enabled:
                    self.pid_d_term = 0.0
                changes.append(f"D={'ON' if self.pid_d_enabled else 'OFF'}")

            if filter_tf is not None:
                self.pid_filter_tf = round(min(1.0, max(0.02, float(filter_tf))), 3)
                changes.append(f"Tf={self.pid_filter_tf}s")

            if cv_min is not None:
                self.pid_cv_min = round(min(60.0, max(0.0, float(cv_min))), 1)
                changes.append(f"CVmin={self.pid_cv_min}%")
            if cv_max is not None:
                self.pid_cv_max = round(min(100.0, max(max(20.0, self.pid_cv_min + 5.0), float(cv_max))), 1)
                changes.append(f"CVmax={self.pid_cv_max}%")

            if manual_cv is not None:
                self.pid_manual_cv = round(min(100.0, max(0.0, float(manual_cv))), 1)
                changes.append(f"CVmanual={self.pid_manual_cv}%")

            if setpoint_mps is not None:
                spd = round(min(self.MAX_SPEED_MPS, max(self.MIN_SPEED_MPS, float(setpoint_mps))), 2)
                self.target_speed_mps = spd
                changes.append(f"SP={spd:.2f} m/s")

            if disturbance_pct is not None:
                self.load_disturbance_pct = round(min(45.0, max(0.0, float(disturbance_pct))), 1)
                self._pulse_disturbance_until = 0.0
                changes.append(f"Perturbación={self.load_disturbance_pct}%")

            if pulse_disturbance:
                self.load_disturbance_pct = 30.0
                self._pulse_disturbance_until = time.time() + 4.0
                changes.append("Golpe de carga 30% por 4s")

            if reset_integral:
                self.pid_i_term = 0.0
                changes.append("Acumulador Integral reiniciado (I=0)")

            if reset_metrics:
                self.pid_iae = 0.0
                self.pid_overshoot_pct = 0.0
                self._peak_pv_since_sp = self.actual_speed_mps
                changes.append("Métricas IAE/Overshoot reiniciadas")

            if changes:
                self._record_event(
                    level="INFO",
                    source=source,
                    code="PID_TUNE",
                    message=f"Sintonía PID actualizada: {', '.join(changes)}.",
                    notify_webhook=(source not in ("HMI-WEB", "PID-TUNER")),
                )

            return {"ok": True, "pid": self.get_pid_state_locked()}

    def get_pid_state_locked(self) -> Dict[str, Any]:
        return {
            "mode": self.pid_mode,
            "active_preset": self.pid_preset,
            "setpoint_mps": round(self.target_speed_mps, 2),
            "pv_mps": round(self.actual_speed_mps, 3),
            "error_mps": round(self.pid_error, 3),
            "kp": self.pid_kp,
            "ki": self.pid_ki,
            "kd": self.pid_kd,
            "p_enabled": self.pid_p_enabled,
            "i_enabled": self.pid_i_enabled,
            "d_enabled": self.pid_d_enabled,
            "filter_tf": self.pid_filter_tf,
            "cv_min": self.pid_cv_min,
            "cv_max": self.pid_cv_max,
            "manual_cv": self.pid_manual_cv,
            "cv_pct": self.pid_cv_pct,
            "p_term": self.pid_p_term,
            "i_term": self.pid_i_term,
            "d_term": self.pid_d_term,
            "iae": self.pid_iae,
            "overshoot_pct": self.pid_overshoot_pct,
            "disturbance_pct": self.load_disturbance_pct,
            "history": list(self.pid_history)[-120:],
        }

    # ------------------------------------------------------------------
    # Comandos de Control HMI / REST API / Node-RED
    # ------------------------------------------------------------------
    def execute_command(
        self,
        action: str,
        value: Any = None,
        source: str = "HMI-WEB",
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        params = params or {}
        action_norm = (action or "").strip().lower()

        with self._lock:
            if action_norm == "start":
                if self.state in ("FAULT", "E_STOP"):
                    return {
                        "ok": False,
                        "message": f"No se puede iniciar: sistema bloqueado por {self.state}. Ejecute 'reset_fault' primero.",
                        "state": self.state,
                    }
                self.state = "RUNNING"
                self._record_event(
                    "SUCCESS",
                    source,
                    "CMD_START",
                    f"Faja transportadora puesta EN MARCHA (SP={self.target_speed_mps:.2f} m/s, PID={self.pid_mode}).",
                )
                return {"ok": True, "message": "Faja en marcha", "state": self.state}

            elif action_norm == "pause":
                if self.state == "RUNNING":
                    self.state = "PAUSED"
                    self._record_event("WARNING", source, "CMD_PAUSE", "Operación pausada temporalmente.")
                return {"ok": True, "message": "Faja en pausa", "state": self.state}

            elif action_norm == "stop":
                if self.state not in ("E_STOP", "FAULT"):
                    self.state = "STOPPED"
                    self._record_event("INFO", source, "CMD_STOP", "Parada controlada de faja transportadora.")
                return {"ok": True, "message": "Faja detenida", "state": self.state}

            elif action_norm in ("emergency_stop", "estop", "e_stop"):
                self.state = "E_STOP"
                self.actual_speed_mps = 0.0
                self.pid_cv_pct = 0.0
                self.active_fault_code = "E_STOP_LATCH"
                self.active_fault_desc = "Parada de Emergencia (Seta E-STOP accionada). Rearme requerido."
                self._record_event(
                    "CRITICAL",
                    source,
                    "E_STOP_TRIGGERED",
                    "¡PARADA DE EMERGENCIA ACTIVADA! Corte inmediato de energía al variador VFD.",
                )
                return {"ok": True, "message": "Parada de emergencia activada", "state": self.state}

            elif action_norm in ("reset", "reset_fault"):
                prev = self.state
                self.active_fault_code = None
                self.active_fault_desc = None
                if self.motor_temp_c > 65.0:
                    self.motor_temp_c = 44.0
                self.state = "STOPPED"
                self._record_event(
                    "SUCCESS",
                    source,
                    "CMD_RESET",
                    f"Rearme de seguridades completado (estado previo: {prev}). Listo para arrancar.",
                )
                return {"ok": True, "message": "Seguridades rearmadas. Sistema en STOPPED.", "state": self.state}

            elif action_norm == "set_speed":
                raw_val = value if value is not None else params.get("speed_mps", 1.4)
                spd = float(raw_val)
                spd = round(min(self.MAX_SPEED_MPS, max(self.MIN_SPEED_MPS, spd)), 2)
                self.target_speed_mps = spd
                self._record_event(
                    "INFO",
                    source,
                    "SET_SPEED",
                    f"Consigna SP ajustada a {spd:.2f} m/s.",
                    extra={"target_speed_mps": spd},
                )
                return {"ok": True, "message": f"Consigna SP: {spd:.2f} m/s", "target_speed_mps": spd}

            elif action_norm in ("set_pid", "tune_pid"):
                cfg_payload = value if isinstance(value, dict) else params
                return self.update_pid_config(
                    mode=cfg_payload.get("mode"),
                    kp=cfg_payload.get("kp"),
                    ki=cfg_payload.get("ki"),
                    kd=cfg_payload.get("kd"),
                    p_enabled=cfg_payload.get("p_enabled"),
                    i_enabled=cfg_payload.get("i_enabled"),
                    d_enabled=cfg_payload.get("d_enabled"),
                    filter_tf=cfg_payload.get("filter_tf"),
                    cv_min=cfg_payload.get("cv_min"),
                    cv_max=cfg_payload.get("cv_max"),
                    manual_cv=cfg_payload.get("manual_cv"),
                    setpoint_mps=cfg_payload.get("setpoint_mps"),
                    disturbance_pct=cfg_payload.get("disturbance_pct"),
                    preset=cfg_payload.get("preset"),
                    reset_integral=bool(cfg_payload.get("reset_integral", False)),
                    reset_metrics=bool(cfg_payload.get("reset_metrics", False)),
                    pulse_disturbance=bool(cfg_payload.get("pulse_disturbance", False)),
                    source=source,
                )

            elif action_norm == "set_direction":
                raw_dir = str(value if value is not None else params.get("direction", "FORWARD")).upper()
                if raw_dir not in ("FORWARD", "REVERSE"):
                    return {"ok": False, "message": "Dirección inválida. Use FORWARD o REVERSE."}
                self.direction = raw_dir
                label_dir = "AVANCE (→)" if raw_dir == "FORWARD" else "REVERSA (←)"
                self._record_event("INFO", source, "SET_DIR", f"Sentido de giro cambiado a {label_dir}.")
                return {"ok": True, "message": f"Sentido: {raw_dir}", "direction": self.direction}

            elif action_norm == "set_auto_feed":
                enabled = bool(value if value is not None else params.get("enabled", True))
                self.auto_feed = enabled
                if "rate_per_min" in params and params["rate_per_min"] is not None:
                    self.feed_rate_per_min = round(min(45.0, max(3.0, float(params["rate_per_min"]))), 1)
                estado_txt = "ACTIVADA" if enabled else "DESACTIVADA"
                self._record_event(
                    "INFO",
                    source,
                    "SET_FEEDER",
                    f"Alimentación automática {estado_txt} ({self.feed_rate_per_min:.0f} uds/min).",
                )
                return {
                    "ok": True,
                    "auto_feed": self.auto_feed,
                    "feed_rate_per_min": self.feed_rate_per_min,
                }

            elif action_norm == "set_feed_rate":
                raw_rate = value if value is not None else params.get("rate_per_min", 16.0)
                self.feed_rate_per_min = round(min(45.0, max(3.0, float(raw_rate))), 1)
                return {"ok": True, "feed_rate_per_min": self.feed_rate_per_min}

            elif action_norm == "set_auto_divert":
                enabled = bool(value if value is not None else params.get("enabled", True))
                self.auto_divert_defective = enabled
                self._record_event(
                    "INFO",
                    source,
                    "SET_DIVERTER",
                    f"Clasificador neumático automático {'ACTIVADO' if enabled else 'DESACTIVADO'}.",
                )
                return {"ok": True, "auto_divert_defective": self.auto_divert_defective}

            elif action_norm == "spawn_item":
                category = str(value if value is not None else params.get("category", "standard")).lower()
                if len(self.items) >= 18:
                    return {"ok": False, "message": "Banda llena (máximo 18 unidades simultáneas)."}
                spawn_pos = 0.25 if self.direction == "FORWARD" else (self.BELT_LENGTH_M - 0.25)
                for existing in self.items:
                    if abs(existing.position_m - spawn_pos) < 0.45:
                        spawn_pos += 0.52 if self.direction == "FORWARD" else -0.52
                spawn_pos = min(self.BELT_LENGTH_M - 0.2, max(0.2, spawn_pos))
                item = self._build_item(category, position_m=spawn_pos)
                if "weight_kg" in params and params["weight_kg"] is not None:
                    item.weight_kg = round(min(50.0, max(0.5, float(params["weight_kg"]))), 2)
                self.items.append(item)
                self.spawned_count += 1
                self._record_event(
                    "INFO",
                    source,
                    "ITEM_SPAWN",
                    f"Unidad inyectada: {item.id} [{item.label}, {item.weight_kg} kg].",
                    extra={"item_id": item.id, "category": item.category, "weight_kg": item.weight_kg},
                    notify_webhook=(source != "HMI-WEB"),
                )
                return {"ok": True, "message": f"Unidad {item.id} agregada", "item": asdict(item)}

            elif action_norm == "clear_belt":
                removed = len(self.items)
                self.items.clear()
                self._record_event("INFO", source, "BELT_CLEAR", f"Banda despejada manualmente ({removed} unidades retiradas).")
                return {"ok": True, "message": f"{removed} unidades retiradas de la banda."}

            elif action_norm == "reset_counters":
                self.dispatched_count = 0
                self.rejected_count = 0
                self.spawned_count = len(self.items)
                self.total_weight_dispatched_kg = 0.0
                self._record_event("INFO", source, "RESET_COUNTERS", "Contadores de lote de producción reiniciados a cero.")
                return {"ok": True, "message": "Contadores reiniciados"}

            elif action_norm == "inject_fault":
                fault_type = str(value if value is not None else params.get("fault_type", "overload")).lower()
                if fault_type in ("overload", "motor_overload"):
                    self.motor_current_a = 15.8
                    self._trigger_fault_locked(
                        "FLT_MOTOR_OVERLOAD",
                        "Disparo de relé térmico F1: Sobrecorriente en motor principal (15.8 A).",
                        source=source,
                    )
                elif fault_type in ("jam", "mech_jam"):
                    self.vibration_mms = 8.9
                    self._trigger_fault_locked(
                        "FLT_MECH_JAM",
                        "Atasco mecánico detectado en rodillo motriz (vibración crítica 8.9 mm/s).",
                        source=source,
                    )
                elif fault_type in ("overtemp", "thermal"):
                    self.motor_temp_c = 86.4
                    self._trigger_fault_locked(
                        "FLT_OVERTEMP",
                        "Alarma PT100 devanado estator: Sobretemperatura crítica (86.4 °C).",
                        source=source,
                    )
                else:
                    self._trigger_fault_locked(
                        "FLT_EXTERNAL",
                        f"Falla externa reportada vía API ({fault_type}).",
                        source=source,
                    )
                return {
                    "ok": True,
                    "state": self.state,
                    "fault_code": self.active_fault_code,
                    "fault_desc": self.active_fault_desc,
                }

            else:
                return {
                    "ok": False,
                    "message": f"Acción desconocida: '{action}'.",
                }

    # ------------------------------------------------------------------
    # Snapshots estructurados para Dashboard, Node-RED y Exportación
    # ------------------------------------------------------------------
    def get_snapshot(self) -> Dict[str, Any]:
        with self._lock:
            total_load_kg = round(sum(it.weight_kg for it in self.items), 2)
            uptime_s = int(time.time() - self.started_epoch)
            elapsed_min = max(0.25, self.run_time_s / 60.0)
            throughput_cpm = round(self.dispatched_count / elapsed_min, 1)
            oee = self._compute_oee_locked()

            return {
                "timestamp": iso_now(),
                "plc": {
                    "model": "SCADA-PID-IIoT",
                    "state": self.state,
                    "direction": self.direction,
                    "uptime_s": uptime_s,
                    "active_fault_code": self.active_fault_code,
                    "active_fault_desc": self.active_fault_desc,
                    "auto_feed": self.auto_feed,
                    "feed_rate_per_min": self.feed_rate_per_min,
                    "auto_divert_defective": self.auto_divert_defective,
                },
                "kinematics": {
                    "belt_length_m": self.BELT_LENGTH_M,
                    "target_speed_mps": round(self.target_speed_mps, 2),
                    "actual_speed_mps": round(self.actual_speed_mps, 2),
                    "pulley_rpm": self.pulley_rpm,
                    "vfd_freq_hz": self.vfd_freq_hz,
                    "belt_offset_m": round(self.belt_offset_m, 4),
                    "belt_tension_pct": self.belt_tension_pct,
                },
                "pid": self.get_pid_state_locked(),
                "motor": {
                    "current_a": self.motor_current_a,
                    "voltage_v": self.motor_voltage_v,
                    "power_kw": self.power_kw,
                    "energy_kwh": self.energy_kwh,
                    "temp_c": round(self.motor_temp_c, 1),
                    "ambient_temp_c": self.ambient_temp_c,
                    "vibration_mms": self.vibration_mms,
                },
                "production": {
                    "items_on_belt": len(self.items),
                    "current_load_kg": total_load_kg,
                    "max_capacity_kg": self.MAX_CAPACITY_KG,
                    "load_utilization_pct": round((total_load_kg / self.MAX_CAPACITY_KG) * 100.0, 1),
                    "dispatched_count": self.dispatched_count,
                    "rejected_count": self.rejected_count,
                    "spawned_count": self.spawned_count,
                    "total_weight_dispatched_kg": self.total_weight_dispatched_kg,
                    "throughput_cpm": throughput_cpm,
                    **oee,
                },
                "sensors": {
                    "PE_01_entry": self.sensor_pe01_entry,
                    "LC_02_active": self.sensor_lc02_active,
                    "LC_02_weight_kg": self.sensor_lc02_weight_kg,
                    "last_weighed_kg": self.last_weighed_kg,
                    "VS_03_presence": self.sensor_vs03_vision,
                    "VS_03_defect": self.sensor_vs03_defect_flag,
                    "IN_04_exit": self.sensor_in04_exit,
                    "DO_diverter": self.actuator_diverter_active,
                    "positions_m": {
                        "PE_01": self.SENSOR_PE01_POS,
                        "LC_02": self.SENSOR_LC02_POS,
                        "VS_03": self.SENSOR_VS03_POS,
                        "IN_04": self.SENSOR_IN04_POS,
                    },
                },
                "items": [asdict(it) for it in self.items],
                "diverted_recent": list(self.diverted_recent),
                "events": list(self.events)[:25],
                "history": list(self.history)[-60:],
            }

    def get_register_map(self) -> Dict[str, Any]:
        snap = self.get_snapshot()
        pid = snap["pid"]
        return {
            "timestamp": snap["timestamp"],
            "device_id": "SCADA-PID-01",
            "digital_inputs": {
                "DI_00_PE01_ENTRY": snap["sensors"]["PE_01_entry"],
                "DI_01_LC02_PRESENCE": snap["sensors"]["LC_02_active"],
                "DI_02_VS03_VISION": snap["sensors"]["VS_03_presence"],
                "DI_03_VS03_DEFECT": snap["sensors"]["VS_03_defect"],
                "DI_04_IN04_EXIT": snap["sensors"]["IN_04_exit"],
                "DI_05_ESTOP_OK": snap["plc"]["state"] != "E_STOP",
            },
            "digital_outputs": {
                "DO_00_MOTOR_RUN": snap["plc"]["state"] == "RUNNING",
                "DO_01_REVERSE_RELAY": snap["plc"]["direction"] == "REVERSE",
                "DO_02_PNEUMATIC_DIVERTER": snap["sensors"]["DO_diverter"],
                "DO_03_FAULT_BEACON": snap["plc"]["state"] in ("FAULT", "E_STOP"),
                "DO_04_PID_CLOSED_LOOP": pid["mode"] == "AUTO",
            },
            "analog_registers": {
                "AI_00_SPEED_MPS": snap["kinematics"]["actual_speed_mps"],
                "AO_00_SPEED_SETPOINT_MPS": snap["kinematics"]["target_speed_mps"],
                "AI_01_MOTOR_CURRENT_A": snap["motor"]["current_a"],
                "AI_02_MOTOR_TEMP_C": snap["motor"]["temp_c"],
                "AI_03_VIBRATION_MMS": snap["motor"]["vibration_mms"],
                "AI_04_SCALE_WEIGHT_KG": snap["sensors"]["LC_02_weight_kg"],
                "AI_05_TOTAL_LOAD_KG": snap["production"]["current_load_kg"],
                "AI_06_OEE_PCT": snap["production"]["oee_pct"],
                "PID_CV_OUTPUT_PCT": pid["cv_pct"],
                "PID_ERROR_MPS": pid["error_mps"],
                "PID_KP": pid["kp"],
                "PID_KI": pid["ki"],
                "PID_KD": pid["kd"],
            },
            "counters": {
                "CNT_DISPATCHED": snap["production"]["dispatched_count"],
                "CNT_REJECTED": snap["production"]["rejected_count"],
                "CNT_ITEMS_ON_BELT": snap["production"]["items_on_belt"],
            },
            "plc_state": snap["plc"]["state"],
            "fault_code": snap["plc"]["active_fault_code"],
        }

    def export_history_csv(self) -> str:
        with self._lock:
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(
                [
                    "timestamp",
                    "epoch_ms",
                    "speed_mps",
                    "target_speed_mps",
                    "pid_cv_pct",
                    "current_a",
                    "temp_c",
                    "load_kg",
                    "vibration_mms",
                    "power_kw",
                    "dispatched_count",
                    "oee_pct",
                ]
            )
            for row in self.history:
                writer.writerow(
                    [
                        row["timestamp"],
                        row["epoch_ms"],
                        row["speed_mps"],
                        row["target_speed_mps"],
                        row.get("pid_cv_pct", 0.0),
                        row["current_a"],
                        row["temp_c"],
                        row["load_kg"],
                        row["vibration_mms"],
                        row["power_kw"],
                        row["dispatched_count"],
                        row["oee_pct"],
                    ]
                )
            return buf.getvalue()
>>>>>>> 6b869b7 (Initial commit: S_F_T)
