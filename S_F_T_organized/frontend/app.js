(() => {
  "use strict";

  // Estado reactivo sincronizado con el backend (secuencia monotónica `seq`)
  const appState = {
    snapshot: null,
    lastSeq: 0,
    wsConnected: false,
    wsSocket: null,
    wsPingTimer: null,
    lastSnapshotTime: performance.now(),
    smoothOffsetM: 0,
    smoothItems: [],
    activeSeries: new Set(["speed_mps", "current_a", "temp_c"]),
    chartHoverIndex: null,
    renderedTurnIds: new Set(),
    welcomeChatHtml: "",
  };

  function throttle(fn, waitMs = 120) {
    let lastCall = 0;
    let timer = null;
    return (...args) => {
      const now = performance.now();
      const remaining = waitMs - (now - lastCall);
      if (remaining <= 0) {
        if (timer) {
          clearTimeout(timer);
          timer = null;
        }
        lastCall = now;
        fn(...args);
      } else {
        if (timer) clearTimeout(timer);
        timer = setTimeout(() => {
          lastCall = performance.now();
          timer = null;
          fn(...args);
        }, remaining);
      }
    };
  }

  const SERIES_META = {
    speed_mps: { label: "Velocidad", unit: "m/s", min: 0, max: 3.2, color: "#2563eb" },
    current_a: { label: "Corriente", unit: "A", min: 0, max: 16.0, color: "#059669" },
    temp_c: { label: "Temp Motor", unit: "°C", min: 20, max: 95.0, color: "#d97706" },
    load_kg: { label: "Carga Banda", unit: "kg", min: 0, max: 120.0, color: "#7c3aed" },
  };

  const STATE_LABELS_ES = {
    RUNNING: { text: "EN MARCHA", pillClass: "state-running" },
    PAUSED: { text: "EN PAUSA", pillClass: "state-paused" },
    STOPPED: { text: "DETENIDA", pillClass: "state-stopped" },
    FAULT: { text: "FALLA ACTIVA", pillClass: "state-fault" },
    E_STOP: { text: "EMERGENCIA E-STOP", pillClass: "state-fault" },
  };

  // Utilidad Toast
  function showToast(message, kind = "info") {
    const container = document.getElementById("toastContainer");
    if (!container) return;
    const el = document.createElement("div");
    el.className = `toast ${kind}`;
    el.textContent = message;
    container.appendChild(el);
    setTimeout(() => {
      el.style.opacity = "0";
      el.style.transition = "opacity 0.25s ease";
      setTimeout(() => el.remove(), 260);
    }, 3200);
  }

  function formatDuration(sec) {
    const s = Math.max(0, Math.floor(sec || 0));
    const hh = String(Math.floor(s / 3600)).padStart(2, "0");
    const mm = String(Math.floor((s % 3600) / 60)).padStart(2, "0");
    const ss = String(s % 60).padStart(2, "0");
    return `${hh}:${mm}:${ss}`;
  }

  async function apiFetch(path, options = {}) {
    const headers = Object.assign(
      { "Content-Type": "application/json" },
      options.headers || {}
    );
    const resp = await fetch(path, Object.assign({}, options, { headers }));
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      throw new Error(data.detail || data.message || `HTTP ${resp.status}`);
    }
    return data;
  }

  async function sendPlcCommand(action, value = null, params = {}) {
    try {
      const res = await apiFetch("/api/v1/control", {
        method: "POST",
        body: JSON.stringify({
          action,
          value,
          source: "HMI-WEB",
          params,
        }),
      });
      if (res.snapshot) {
        ingestSnapshot(res.snapshot, { force: true });
      }
      if (res.ok === false) {
        showToast(res.message || "Acción no permitida en este estado", "error");
      }
      return res;
    } catch (err) {
      showToast(`Error comando: ${err.message}`, "error");
    }
  }

  async function sendPidUpdate(payload) {
    try {
      const res = await apiFetch("/api/v1/pid", {
        method: "POST",
        body: JSON.stringify(Object.assign({ source: "PID-TUNER" }, payload)),
      });
      if (res.snapshot) {
        ingestSnapshot(res.snapshot, { force: true });
      }
      return res;
    } catch (err) {
      showToast(`Error PID: ${err.message}`, "error");
    }
  }

  // ------------------------------------------------------------------
  // Loader de Página (5 Segundos): Spinner concéntrico alrededor del Logo
  // ------------------------------------------------------------------
  let logoSpinnerFrame = null;
  let logoSpinnerInterval = null;
  let logoSpinnerSafetyTimer = null;
  let logoSpinnerHideTimer = null;

  function runLogoSpinner5s() {
    const pageLoader = document.getElementById("pageLogoLoader");
    const progressFill = document.getElementById("pageLoaderProgressFill");
    const percentEl = document.getElementById("pageLoaderPercent");
    const countdownEl = document.getElementById("pageLoaderCountdown");
    const stepTextEl = document.getElementById("pageLoaderStepText");

    const spinnerLayer = document.getElementById("logoSpinner");
    const badgeEl = document.getElementById("logoSpinnerBadge");

    if (logoSpinnerFrame) cancelAnimationFrame(logoSpinnerFrame);
    if (logoSpinnerInterval) clearInterval(logoSpinnerInterval);
    if (logoSpinnerSafetyTimer) clearTimeout(logoSpinnerSafetyTimer);
    if (logoSpinnerHideTimer) clearTimeout(logoSpinnerHideTimer);

    if (pageLoader) {
      pageLoader.style.display = "flex";
      // Forzar reflujo limpio para reiniciar transición si se pulsó Actualizar
      void pageLoader.offsetWidth;
      pageLoader.classList.remove("loader-done");
    }
    if (progressFill) {
      progressFill.style.width = "0%";
    }
    if (percentEl) percentEl.textContent = "0%";
    if (countdownEl) countdownEl.textContent = "5.0 s";
    if (stepTextEl) stepTextEl.textContent = "Cargando panel de control...";

    if (spinnerLayer) {
      spinnerLayer.classList.remove("spinner-hidden");
    }
    if (badgeEl) {
      badgeEl.classList.remove("badge-hidden", "badge-fading", "hidden", "opacity-0");
      badgeEl.textContent = "5.0s";
    }

    const durationMs = 5000;
    const tStartWall = Date.now();
    let finished = false;

    function finishLogoSpinner() {
      if (finished) return;
      finished = true;
      if (logoSpinnerFrame) cancelAnimationFrame(logoSpinnerFrame);
      if (logoSpinnerInterval) clearInterval(logoSpinnerInterval);
      if (logoSpinnerSafetyTimer) clearTimeout(logoSpinnerSafetyTimer);

      if (progressFill) progressFill.style.width = "100%";
      if (percentEl) percentEl.textContent = "100%";
      if (countdownEl) countdownEl.textContent = "0.0 s";
      if (badgeEl) badgeEl.textContent = "0.0s";
      if (stepTextEl) stepTextEl.textContent = "¡Listo!";

      if (pageLoader) {
        pageLoader.classList.add("loader-done");
      }
      if (spinnerLayer) {
        spinnerLayer.classList.add("spinner-hidden");
      }
      if (badgeEl) {
        badgeEl.classList.add("badge-fading");
      }
      logoSpinnerHideTimer = setTimeout(() => {
        if (pageLoader && pageLoader.classList.contains("loader-done")) {
          pageLoader.style.display = "none";
        }
        if (badgeEl) {
          badgeEl.classList.add("badge-hidden");
        }
      }, 360);
    }

    function updateSpinnerProgress() {
      if (finished) return;
      const elapsed = Math.min(durationMs, Math.max(0, Date.now() - tStartWall));
      const pct = Math.round((elapsed / durationMs) * 100);
      const remSec = Math.max(0, (durationMs - elapsed) / 1000);

      if (progressFill) progressFill.style.width = `${pct}%`;
      if (percentEl) percentEl.textContent = `${pct}%`;
      if (countdownEl) countdownEl.textContent = `${remSec.toFixed(1)} s`;
      if (badgeEl) badgeEl.textContent = `${remSec.toFixed(1)}s`;

      if (stepTextEl) {
        if (elapsed < 1300) {
          stepTextEl.textContent = "Cargando panel de control...";
        } else if (elapsed < 2600) {
          stepTextEl.textContent = "Preparando simulación de faja transportadora...";
        } else if (elapsed < 3900) {
          stepTextEl.textContent = "Iniciando controles PID...";
        } else {
          stepTextEl.textContent = "¡Listo!";
        }
      }

      if (elapsed >= durationMs) {
        finishLogoSpinner();
      }
    }

    function rafLoop() {
      if (finished) return;
      updateSpinnerProgress();
      if (!finished) {
        logoSpinnerFrame = requestAnimationFrame(rafLoop);
      }
    }

    // Doble temporización: rAF suave (60 FPS) + intervalo de reloj real (para pestañas en segundo plano)
    logoSpinnerFrame = requestAnimationFrame(rafLoop);
    logoSpinnerInterval = setInterval(updateSpinnerProgress, 80);
    logoSpinnerSafetyTimer = setTimeout(finishLogoSpinner, durationMs + 60);
  }

  // ------------------------------------------------------------------
  // Ingesta de Telemetría y Sincronización Unificada Backend ↔ Frontend
  // ------------------------------------------------------------------
  function ingestSnapshot(snapshot, opts = {}) {
    if (!snapshot) return;
    const incomingSeq = Number(snapshot.seq || 0);
    if (!opts.force && incomingSeq > 0 && incomingSeq < appState.lastSeq) {
      return; // Ignorar paquetes antiguos fuera de orden
    }
    if (incomingSeq > appState.lastSeq) {
      appState.lastSeq = incomingSeq;
    }

    appState.snapshot = snapshot;
    appState.lastSnapshotTime = performance.now();
    appState.smoothOffsetM = snapshot.kinematics.belt_offset_m;
    appState.smoothItems = (snapshot.items || []).map((it) => Object.assign({}, it));

    updateDashboardDOM();
    if (snapshot.pid) {
      updatePidDOM(snapshot.pid);
      drawPidOscilloscope();
    }
    drawTelemetryChart();
  }

  function ingestBootstrap(bundle) {
    if (!bundle) return;
    if (bundle.snapshot) {
      ingestSnapshot(bundle.snapshot, { force: true });
    }
    if (bundle.rag_overview) {
      renderRagOverview(bundle.rag_overview);
    }
  }

  async function syncFullState(forceReload = false) {
    try {
      const endpoint = forceReload ? "/api/v1/sync" : "/api/v1/bootstrap";
      const method = forceReload ? "POST" : "GET";
      const bundle = await apiFetch(endpoint, { method });
      ingestBootstrap(bundle);
      return bundle;
    } catch (_) {
      try {
        const snap = await apiFetch("/api/v1/status");
        ingestSnapshot(snap, { force: true });
      } catch (_e) {}
      return null;
    }
  }

  function updateDashboardDOM() {
    const snap = appState.snapshot;
    if (!snap) return;

    const { plc, kinematics, motor, production, sensors } = snap;
    const stInfo = STATE_LABELS_ES[plc.state] || { text: plc.state, pillClass: "state-stopped" };

    // Píldora superior y banner de alarma
    const pill = document.getElementById("plcStatePill");
    const pillTxt = document.getElementById("plcStateText");
    pill.className = `status-pill ${stInfo.pillClass}`;
    pillTxt.textContent = stInfo.text;

    const banner = document.getElementById("alarmBanner");
    if (plc.state === "FAULT" || plc.state === "E_STOP") {
      banner.classList.remove("hidden");
      document.getElementById("alarmCodeBadge").textContent = plc.active_fault_code || plc.state;
      document.getElementById("alarmDescText").textContent =
        plc.active_fault_desc || "Sistema detenido por enclavamiento de seguridad.";
    } else {
      banner.classList.add("hidden");
    }

    // KPIs Superiores
    document.getElementById("kpiUptime").textContent = formatDuration(plc.uptime_s);
    const stateLabelEl = document.getElementById("kpiStateLabel");
    stateLabelEl.textContent = stInfo.text;
    stateLabelEl.style.color =
      plc.state === "RUNNING"
        ? "var(--emerald)"
        : plc.state === "PAUSED"
        ? "var(--amber)"
        : plc.state === "STOPPED"
        ? "var(--text-primary)"
        : "var(--crimson)";

    document.getElementById("kpiDirection").textContent =
      plc.direction === "FORWARD" ? "AVANCE →" : "← REVERSA";
    document.getElementById("kpiItemsCount").textContent = `${production.items_on_belt} en faja`;

    document.getElementById("kpiVfdHz").textContent = `${kinematics.vfd_freq_hz.toFixed(1)} Hz`;
    document.getElementById("kpiSpeed").textContent = kinematics.actual_speed_mps.toFixed(2);
    document.getElementById("kpiTargetSpeed").textContent = `${kinematics.target_speed_mps.toFixed(2)} m/s`;
    document.getElementById("kpiRpm").textContent = `${kinematics.pulley_rpm.toFixed(1)} RPM`;

    document.getElementById("kpiThroughput").textContent = `${production.throughput_cpm.toFixed(1)} uds/m`;
    document.getElementById("kpiDispatched").textContent = production.dispatched_count;
    document.getElementById("kpiRejected").textContent = production.rejected_count;
    document.getElementById("kpiTotalKg").textContent = `${production.total_weight_dispatched_kg.toFixed(1)} kg`;

    document.getElementById("kpiLoadPct").textContent = `${production.load_utilization_pct.toFixed(1)}%`;
    document.getElementById("kpiLoadKg").textContent = production.current_load_kg.toFixed(1);
    const loadBar = document.getElementById("kpiLoadBar");
    loadBar.style.width = `${Math.min(100, production.load_utilization_pct)}%`;
    loadBar.style.backgroundColor =
      production.load_utilization_pct > 85
        ? "var(--crimson)"
        : production.load_utilization_pct > 65
        ? "var(--amber)"
        : "var(--primary)";

    document.getElementById("kpiPowerKw").textContent = `${motor.power_kw.toFixed(2)} kW`;
    document.getElementById("kpiCurrent").textContent = motor.current_a.toFixed(2);
    const tempEl = document.getElementById("kpiTemp");
    tempEl.textContent = `${motor.temp_c.toFixed(1)} °C`;
    tempEl.style.color = motor.temp_c > 70 ? "var(--crimson)" : motor.temp_c > 55 ? "var(--amber)" : "var(--text-primary)";
    document.getElementById("kpiVibration").textContent = `${motor.vibration_mms.toFixed(2)} mm/s`;
    document.getElementById("kpiEnergy").textContent = `${motor.energy_kwh.toFixed(3)} kWh`;

    document.getElementById("kpiOee").textContent = production.oee_pct.toFixed(1);
    document.getElementById("kpiOeeDisp").textContent = `D:${production.availability_pct.toFixed(0)}%`;
    document.getElementById("kpiOeePerf").textContent = `R:${production.performance_pct.toFixed(0)}%`;
    document.getElementById("kpiOeeQual").textContent = `C:${production.quality_pct.toFixed(0)}%`;
    const oeeBadge = document.getElementById("kpiOeeBadge");
    if (production.oee_pct >= 85) {
      oeeBadge.textContent = "ÓPTIMO";
      oeeBadge.className = "badge badge-success";
    } else if (production.oee_pct >= 70) {
      oeeBadge.textContent = "ACEPTABLE";
      oeeBadge.className = "badge badge-warn";
    } else {
      oeeBadge.textContent = "BAJO";
      oeeBadge.className = "badge badge-crit";
    }

    // Insignias del Gemelo Digital y Sensores
    document.getElementById("twinTensionBadge").textContent = `Tensión: ${kinematics.belt_tension_pct.toFixed(1)}%`;
    document.getElementById("twinScaleBadge").textContent = `Báscula: ${sensors.LC_02_weight_kg.toFixed(2)} kg`;

    // Entrada
    const cPE = document.getElementById("cardSensorPE01");
    const lPE = document.getElementById("ledPE01");
    cPE.className = `sensor-badge-card ${sensors.PE_01_entry ? "active" : ""}`;
    lPE.className = `led-indicator ${sensors.PE_01_entry ? "on-green" : ""}`;
    document.getElementById("txtSensorPE01").textContent = sensors.PE_01_entry
      ? "Detectado"
      : "Libre";

    // Báscula
    const cLC = document.getElementById("cardSensorLC02");
    const lLC = document.getElementById("ledLC02");
    cLC.className = `sensor-badge-card ${sensors.LC_02_active ? "active" : ""}`;
    lLC.className = `led-indicator ${sensors.LC_02_active ? "on-blue" : ""}`;
    document.getElementById("txtSensorLC02").textContent = `${sensors.LC_02_weight_kg.toFixed(2)} kg`;

    // Control de Calidad
    const cVS = document.getElementById("cardSensorVS03");
    const lVS = document.getElementById("ledVS03");
    if (sensors.VS_03_defect || sensors.DO_diverter) {
      cVS.className = "sensor-badge-card defect";
      lVS.className = "led-indicator on-red";
      document.getElementById("txtSensorVS03").textContent = "Separando defecto";
    } else if (sensors.VS_03_presence) {
      cVS.className = "sensor-badge-card active";
      lVS.className = "led-indicator on-green";
      document.getElementById("txtSensorVS03").textContent = "Correcta";
    } else {
      cVS.className = "sensor-badge-card";
      lVS.className = "led-indicator";
      document.getElementById("txtSensorVS03").textContent = "En espera";
    }

    // Salida
    const cIN = document.getElementById("cardSensorIN04");
    const lIN = document.getElementById("ledIN04");
    cIN.className = `sensor-badge-card ${sensors.IN_04_exit ? "active" : ""}`;
    lIN.className = `led-indicator ${sensors.IN_04_exit ? "on-green" : ""}`;
    document.getElementById("txtSensorIN04").textContent = sensors.IN_04_exit
      ? "Entregando"
      : "Libre";

    // Sincronizar controles si el usuario no los está arrastrando activamente
    const sliderSpeed = document.getElementById("sliderSpeed");
    if (document.activeElement !== sliderSpeed) {
      sliderSpeed.value = kinematics.target_speed_mps;
      document.getElementById("lblSpeedSlider").textContent = `${kinematics.target_speed_mps.toFixed(2)} m/s`;
    }

    document.getElementById("btnDirForward").className = `btn btn-sm ${plc.direction === "FORWARD" ? "btn-active-choice" : ""}`;
    document.getElementById("btnDirReverse").className = `btn btn-sm ${plc.direction === "REVERSE" ? "btn-active-choice" : ""}`;

    const chkAutoFeed = document.getElementById("chkAutoFeed");
    if (document.activeElement !== chkAutoFeed) chkAutoFeed.checked = plc.auto_feed;

    const sliderFeed = document.getElementById("sliderFeedRate");
    if (document.activeElement !== sliderFeed) {
      sliderFeed.value = plc.feed_rate_per_min;
      document.getElementById("lblFeedRate").textContent = Math.round(plc.feed_rate_per_min);
    }

    const chkAutoDivert = document.getElementById("chkAutoDivert");
    if (document.activeElement !== chkAutoDivert) chkAutoDivert.checked = plc.auto_divert_defective;

    // Registro de eventos
    renderEventsTable(snap.events || []);
  }

  function renderEventsTable(events) {
    const tbody = document.getElementById("eventsTableBody");
    if (!tbody) return;
    if (!events.length) {
      tbody.innerHTML = '<tr><td colspan="4">Sin eventos registrados.</td></tr>';
      return;
    }
    const badgeMap = {
      INFO: "badge-info",
      SUCCESS: "badge-success",
      WARNING: "badge-warn",
      CRITICAL: "badge-crit",
    };
    tbody.innerHTML = events
      .slice(0, 18)
      .map((e) => {
        const bCls = badgeMap[e.level] || "badge-info";
        return `<tr>
          <td class="mono">${e.time_short || ""}</td>
          <td><span class="badge ${bCls}">${e.level}</span></td>
          <td class="mono" style="font-weight:600;">${escapeHtml(e.source)}</td>
          <td>${escapeHtml(e.message)}</td>
        </tr>`;
      })
      .join("");
  }

  function escapeHtml(str) {
    return String(str ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  // ------------------------------------------------------------------
  // Renderizador 60 FPS del Gemelo Digital (HTML5 Canvas Modo Claro)
  // ------------------------------------------------------------------
  function renderConveyorLoop(nowPerf) {
    const canvas = document.getElementById("conveyorCanvas");
    if (canvas && appState.snapshot) {
      const dt = Math.min(0.1, Math.max(0, (nowPerf - appState.lastSnapshotTime) / 1000));
      appState.lastSnapshotTime = nowPerf;

      const { plc, kinematics } = appState.snapshot;
      const dirSign = plc.direction === "FORWARD" ? 1 : -1;
      const deltaM = kinematics.actual_speed_mps * dt * dirSign;

      appState.smoothOffsetM = (appState.smoothOffsetM + deltaM) % 1.0;
      for (const it of appState.smoothItems) {
        it.position_m += deltaM;
      }

      drawConveyorTwin(canvas, appState.snapshot);
    }
    requestAnimationFrame(renderConveyorLoop);
  }

  function drawConveyorTwin(canvas, snap) {
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    if (rect.width < 20 || rect.height < 20) return;

    const targetW = Math.round(rect.width * dpr);
    const targetH = Math.round(rect.height * dpr);
    if (canvas.width !== targetW || canvas.height !== targetH) {
      canvas.width = targetW;
      canvas.height = targetH;
    }

    const ctx = canvas.getContext("2d");
    ctx.save();
    ctx.scale(dpr, dpr);

    const W = rect.width;
    const H = rect.height;

    // 1. Fondo Técnico Modo Claro con retícula de ingeniería
    ctx.clearRect(0, 0, W, H);
    ctx.strokeStyle = "#e2e8f0";
    ctx.lineWidth = 1;
    const gridStep = 32;
    for (let gx = 0; gx < W; gx += gridStep) {
      ctx.beginPath();
      ctx.moveTo(gx, 0);
      ctx.lineTo(gx, H);
      ctx.stroke();
    }
    for (let gy = 0; gy < H; gy += gridStep) {
      ctx.beginPath();
      ctx.moveTo(0, gy);
      ctx.lineTo(W, gy);
      ctx.stroke();
    }

    // Geometría principal de la faja (0.0m a 10.0m)
    const padLeft = 82;
    const padRight = 98;
    const beltPxLen = Math.max(200, W - padLeft - padRight);
    const beltYTop = Math.round(H * 0.50);
    const pulleyR = 26;
    const beltYBot = beltYTop + pulleyR * 2;
    const mToX = (m) => padLeft + (m / 10.0) * beltPxLen;

    const { plc, kinematics, motor, sensors } = snap;

    // 2. Bastidor estructural y patas metálicas
    ctx.fillStyle = "#cbd5e1";
    ctx.strokeStyle = "#94a3b8";
    ctx.lineWidth = 1.5;
    [0.8, 3.4, 6.6, 9.2].forEach((mPos) => {
      const lx = mToX(mPos);
      ctx.fillRect(lx - 5, beltYBot - 4, 10, H - beltYBot - 22);
      ctx.strokeRect(lx - 5, beltYBot - 4, 10, H - beltYBot - 22);
      // Zapata de anclaje al piso
      ctx.fillStyle = "#64748b";
      ctx.fillRect(lx - 13, H - 26, 26, 6);
      ctx.fillStyle = "#cbd5e1";
    });

    // Línea de piso industrial
    ctx.strokeStyle = "#cbd5e1";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(16, H - 20);
    ctx.lineTo(W - 16, H - 20);
    ctx.stroke();

    // 3. Tolva de Alimentación (Izquierda)
    const hopX = padLeft - 38;
    const hopY = beltYTop - 76;
    ctx.fillStyle = "#e2e8f0";
    ctx.strokeStyle = "#64748b";
    ctx.lineWidth = 1.8;
    ctx.beginPath();
    ctx.moveTo(hopX - 24, hopY);
    ctx.lineTo(hopX + 36, hopY);
    ctx.lineTo(hopX + 22, hopY + 50);
    ctx.lineTo(hopX - 10, hopY + 50);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();

    ctx.fillStyle = "#334155";
    ctx.font = "700 10px Inter, sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("TOLVA", hopX + 6, hopY - 7);
    ctx.fillStyle = plc.auto_feed ? "#059669" : "#64748b";
    ctx.font = "600 9.5px monospace";
    ctx.fillText(plc.auto_feed ? "AUTO ON" : "MANUAL", hopX + 6, hopY + 24);

    // 4. Rampa de Despacho (Derecha) y Rampa de Rechazo QA (6.8m)
    const dispX = mToX(10.0) + pulleyR + 10;
    ctx.fillStyle = "#eff6ff";
    ctx.strokeStyle = "#93c5fd";
    ctx.lineWidth = 1.5;
    roundRect(ctx, dispX, beltYTop + 18, 66, 62, 6, true, true);
    ctx.fillStyle = "#1d4ed8";
    ctx.font = "700 9.5px Inter, sans-serif";
    ctx.fillText("DESPACHO", dispX + 33, beltYTop + 36);
    ctx.font = "700 13px monospace";
    ctx.fillText(`${snap.production.dispatched_count}`, dispX + 33, beltYTop + 56);
    ctx.font = "600 9px Inter, sans-serif";
    ctx.fillText("unidades", dispX + 33, beltYTop + 70);

    // Contenedor Rechazo (6.8m)
    const rejX = mToX(6.8);
    ctx.fillStyle = sensors.DO_diverter ? "#fee2e2" : "#fff1f2";
    ctx.strokeStyle = sensors.DO_diverter ? "#dc2626" : "#fda4af";
    roundRect(ctx, rejX - 34, beltYBot + 20, 68, 42, 6, true, true);
    ctx.fillStyle = "#b91c1c";
    ctx.font = "700 9px Inter, sans-serif";
    ctx.fillText("RECHAZO", rejX, beltYBot + 36);
    ctx.font = "700 12px monospace";
    ctx.fillText(`${snap.production.rejected_count} uds`, rejX, beltYBot + 52);

    // 5. Báscula en banda (3.3m a 4.7m)
    const lcStart = mToX(3.3);
    const lcEnd = mToX(4.7);
    ctx.fillStyle = sensors.LC_02_active ? "#dbeafe" : "#f1f5f9";
    ctx.strokeStyle = sensors.LC_02_active ? "#2563eb" : "#94a3b8";
    ctx.lineWidth = 1.5;
    roundRect(ctx, lcStart, beltYTop + 6, lcEnd - lcStart, 22, 4, true, true);
    ctx.fillStyle = "#1e40af";
    ctx.font = "700 9.5px monospace";
    ctx.fillText(`Báscula: ${sensors.LC_02_weight_kg.toFixed(1)} kg`, (lcStart + lcEnd) / 2, beltYTop + 20);

    // 6. Viga central del transportador
    ctx.fillStyle = "#e2e8f0";
    ctx.strokeStyle = "#94a3b8";
    ctx.lineWidth = 1.2;
    ctx.fillRect(padLeft, beltYTop + 14, beltPxLen, pulleyR * 2 - 28);
    ctx.strokeRect(padLeft, beltYTop + 14, beltPxLen, pulleyR * 2 - 28);

    // Polines intermedios giratorios
    const wheelAngle = (appState.smoothOffsetM / (Math.PI * 0.32)) * Math.PI * 2;
    for (let m = 1.0; m <= 9.0; m += 1.0) {
      const rx = mToX(m);
      ctx.fillStyle = "#ffffff";
      ctx.strokeStyle = "#64748b";
      ctx.lineWidth = 1.3;
      ctx.beginPath();
      ctx.arc(rx, beltYTop + 9, 6.5, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();

      ctx.beginPath();
      ctx.moveTo(rx + Math.cos(wheelAngle * 2) * 5, beltYTop + 9 + Math.sin(wheelAngle * 2) * 5);
      ctx.lineTo(rx - Math.cos(wheelAngle * 2) * 5, beltYTop + 9 - Math.sin(wheelAngle * 2) * 5);
      ctx.stroke();
    }

    // 7. Banda de Caucho Industrial (Tramo Superior e Inferior + Nervaduras animadas)
    const beltColor =
      plc.state === "FAULT" || plc.state === "E_STOP"
        ? "#991b1b"
        : plc.state === "RUNNING"
        ? "#1e293b"
        : "#475569";

    ctx.strokeStyle = beltColor;
    ctx.lineWidth = 7;
    ctx.beginPath();
    ctx.moveTo(padLeft, beltYTop);
    ctx.lineTo(padLeft + beltPxLen, beltYTop);
    ctx.stroke();

    ctx.lineWidth = 4.5;
    ctx.strokeStyle = "#64748b";
    ctx.beginPath();
    ctx.moveTo(padLeft, beltYBot);
    ctx.lineTo(padLeft + beltPxLen, beltYBot);
    ctx.stroke();

    // Tacos/marcas de movimiento sobre la banda cada 0.5m
    const cleatSpacingM = 0.5;
    let phaseM = ((appState.smoothOffsetM % cleatSpacingM) + cleatSpacingM) % cleatSpacingM;
    ctx.strokeStyle = "#38bdf8";
    ctx.lineWidth = 2.2;
    for (let posM = phaseM; posM <= 10.0; posM += cleatSpacingM) {
      const cx = mToX(posM);
      ctx.beginPath();
      ctx.moveTo(cx, beltYTop - 3.5);
      ctx.lineTo(cx, beltYTop + 3.5);
      ctx.stroke();
    }

    // 8. Polea de Cola (0.0m) y Polea Motriz + Motor VFD (10.0m)
    drawPulley(ctx, padLeft, beltYTop + pulleyR, pulleyR, wheelAngle, "#475569", "COLA 0m");
    const motorHot = motor.temp_c > 70;
    drawPulley(
      ctx,
      padLeft + beltPxLen,
      beltYTop + pulleyR,
      pulleyR,
      wheelAngle,
      motorHot ? "#dc2626" : "#2563eb",
      `MOTRIZ ${kinematics.pulley_rpm.toFixed(0)} RPM`
    );

    // Regla métrica sutil bajo el bastidor
    ctx.fillStyle = "#64748b";
    ctx.font = "600 9.5px monospace";
    for (let m = 0; m <= 10; m += 2) {
      ctx.fillText(`${m}m`, mToX(m), beltYBot + 14);
    }

    // 9. Estaciones de Sensores Superiores
    drawSensorStation(
      ctx,
      mToX(sensors.positions_m.PE_01),
      beltYTop,
      "ENTRADA",
      sensors.PE_01_entry ? "#10b981" : "#94a3b8",
      sensors.PE_01_entry
    );

    drawVisionDiverterStation(
      ctx,
      mToX(sensors.positions_m.VS_03),
      beltYTop,
      sensors.VS_03_presence,
      sensors.VS_03_defect,
      sensors.DO_diverter
    );

    drawSensorStation(
      ctx,
      mToX(sensors.positions_m.IN_04),
      beltYTop,
      "SALIDA",
      sensors.IN_04_exit ? "#2563eb" : "#94a3b8",
      sensors.IN_04_exit
    );

    // 10. Cajas / Unidades sobre la Banda Transportadora
    for (const item of appState.smoothItems) {
      if (item.position_m < -0.2 || item.position_m > 10.25) continue;
      const boxW = Math.max(28, (item.length_m / 10.0) * beltPxLen);
      const boxH = item.category === "heavy" ? 36 : item.category === "light" ? 26 : 31;
      const bx = mToX(item.position_m) - boxW / 2;
      const by = beltYTop - boxH - 3.5;

      // Sombra sutil
      ctx.fillStyle = "rgba(15, 23, 42, 0.10)";
      roundRect(ctx, bx + 2, by + 3, boxW, boxH, 5, true, false);

      // Cuerpo de la caja
      ctx.fillStyle = item.color || "#059669";
      ctx.strokeStyle = "rgba(15, 23, 42, 0.25)";
      ctx.lineWidth = 1.2;
      roundRect(ctx, bx, by, boxW, boxH, 5, true, true);

      // Franja técnica superior
      ctx.fillStyle = "rgba(255, 255, 255, 0.25)";
      ctx.fillRect(bx + 3, by + 3, boxW - 6, 4);

      // Etiqueta de peso encima de la caja
      ctx.fillStyle = "#ffffff";
      ctx.strokeStyle = "#cbd5e1";
      ctx.lineWidth = 1;
      const pillW = 48;
      roundRect(ctx, bx + boxW / 2 - pillW / 2, by - 18, pillW, 14, 4, true, true);
      ctx.fillStyle = "#0f172a";
      ctx.font = "700 9.5px monospace";
      ctx.textAlign = "center";
      ctx.fillText(`${item.weight_kg.toFixed(1)}kg`, bx + boxW / 2, by - 8);

      // Código corto dentro de la caja
      ctx.fillStyle = "#ffffff";
      ctx.font = "700 9px monospace";
      const shortCode = item.is_defective ? "QA!" : item.id.replace("PKG-", "#");
      ctx.fillText(shortCode, bx + boxW / 2, by + boxH / 2 + 4);
    }

    // 11. Indicador superior de velocidad y dirección
    ctx.fillStyle = "#ffffff";
    ctx.strokeStyle = "#cbd5e1";
    ctx.lineWidth = 1;
    roundRect(ctx, W / 2 - 105, 10, 210, 26, 13, true, true);
    ctx.fillStyle = "#0f172a";
    ctx.font = "700 11.5px monospace";
    ctx.textAlign = "center";
    const stateMapEs = {
      RUNNING: "EN MARCHA",
      STOPPED: "DETENIDO",
      PAUSED: "EN PAUSA",
      FAULT: "FALLA",
      E_STOP: "EMERGENCIA",
    };
    const arrow = plc.direction === "FORWARD" ? "───►" : "◄───";
    ctx.fillText(`${arrow}  ${kinematics.actual_speed_mps.toFixed(2)} m/s  (${stateMapEs[plc.state] || plc.state})`, W / 2, 27);

    ctx.restore();
  }

  function drawPulley(ctx, cx, cy, r, angle, accentColor, caption) {
    ctx.save();
    ctx.fillStyle = "#ffffff";
    ctx.strokeStyle = accentColor;
    ctx.lineWidth = 4;
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();

    // Radios rotativos
    ctx.strokeStyle = "#94a3b8";
    ctx.lineWidth = 2;
    for (let i = 0; i < 4; i++) {
      const a = angle + (i * Math.PI) / 2;
      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.lineTo(cx + Math.cos(a) * (r - 4), cy + Math.sin(a) * (r - 4));
      ctx.stroke();
    }

    // Eje central
    ctx.fillStyle = accentColor;
    ctx.beginPath();
    ctx.arc(cx, cy, 6, 0, Math.PI * 2);
    ctx.fill();

    ctx.fillStyle = "#334155";
    ctx.font = "700 9.5px monospace";
    ctx.textAlign = "center";
    ctx.fillText(caption, cx, cy + r + 26);
    ctx.restore();
  }

  function drawSensorStation(ctx, x, beltYTop, code, beamColor, active) {
    ctx.save();
    const topY = beltYTop - 68;
    // Soporte
    ctx.strokeStyle = "#64748b";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(x, topY + 18);
    ctx.lineTo(x, topY + 26);
    ctx.stroke();

    // Cabezal del sensor
    ctx.fillStyle = active ? "#ecfdf5" : "#ffffff";
    ctx.strokeStyle = active ? beamColor : "#94a3b8";
    ctx.lineWidth = 1.6;
    roundRect(ctx, x - 27, topY, 54, 18, 4, true, true);
    ctx.fillStyle = "#0f172a";
    ctx.font = "700 9px monospace";
    ctx.textAlign = "center";
    ctx.fillText(code, x, topY + 12.5);

    // Haz láser vertical
    ctx.setLineDash([4, 3]);
    ctx.strokeStyle = active ? beamColor : "rgba(148, 163, 184, 0.55)";
    ctx.lineWidth = active ? 2.4 : 1.3;
    ctx.beginPath();
    ctx.moveTo(x, topY + 18);
    ctx.lineTo(x, beltYTop - 3);
    ctx.stroke();
    ctx.restore();
  }

  function drawVisionDiverterStation(ctx, x, beltYTop, presence, defect, diverterOn) {
    ctx.save();
    const topY = beltYTop - 76;
    const strokeCol = defect || diverterOn ? "#dc2626" : presence ? "#059669" : "#2563eb";
    ctx.fillStyle = defect || diverterOn ? "#fef2f2" : "#ffffff";
    ctx.strokeStyle = strokeCol;
    ctx.lineWidth = 1.8;
    roundRect(ctx, x - 28, topY, 56, 22, 5, true, true);

    ctx.fillStyle = "#0f172a";
    ctx.font = "700 9.5px monospace";
    ctx.textAlign = "center";
    ctx.fillText("CALIDAD", x, topY + 14);

    // Cono de cámara de visión
    ctx.fillStyle =
      defect || diverterOn
        ? "rgba(220, 38, 38, 0.16)"
        : presence
        ? "rgba(16, 185, 129, 0.16)"
        : "rgba(37, 99, 235, 0.07)";
    ctx.beginPath();
    ctx.moveTo(x - 8, topY + 22);
    ctx.lineTo(x + 8, topY + 22);
    ctx.lineTo(x + 22, beltYTop - 3);
    ctx.lineTo(x - 22, beltYTop - 3);
    ctx.closePath();
    ctx.fill();

    // Pistón neumático desviador
    const pistonExt = diverterOn ? 24 : 6;
    ctx.fillStyle = diverterOn ? "#dc2626" : "#64748b";
    ctx.fillRect(x - 5, topY + 22, 10, pistonExt);
    ctx.fillRect(x - 12, topY + 22 + pistonExt, 24, 5);
    ctx.restore();
  }

  function roundRect(ctx, x, y, w, h, r, fill, stroke) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
    if (fill) ctx.fill();
    if (stroke) ctx.stroke();
  }

  // ------------------------------------------------------------------
  // Gráfica Multivariable Normalizada en Modo Claro (#telemetryChart)
  // ------------------------------------------------------------------
  function drawTelemetryChart() {
    const canvas = document.getElementById("telemetryChart");
    if (!canvas || !appState.snapshot) return;

    const history = appState.snapshot.history || [];
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    if (rect.width < 20 || rect.height < 20) return;

    const targetW = Math.round(rect.width * dpr);
    const targetH = Math.round(rect.height * dpr);
    if (canvas.width !== targetW || canvas.height !== targetH) {
      canvas.width = targetW;
      canvas.height = targetH;
    }

    const ctx = canvas.getContext("2d");
    ctx.save();
    ctx.scale(dpr, dpr);

    const W = rect.width;
    const H = rect.height;
    ctx.clearRect(0, 0, W, H);

    const pad = { top: 28, right: 18, bottom: 28, left: 42 };
    const plotW = W - pad.left - pad.right;
    const plotH = H - pad.top - pad.bottom;

    // Líneas de escala porcentual 0%..100% del rango nominal
    ctx.strokeStyle = "#e2e8f0";
    ctx.fillStyle = "#64748b";
    ctx.font = "600 10px monospace";
    ctx.textAlign = "right";
    for (let i = 0; i <= 4; i++) {
      const ratio = i / 4;
      const py = pad.top + plotH - ratio * plotH;
      ctx.beginPath();
      ctx.moveTo(pad.left, py);
      ctx.lineTo(pad.left + plotW, py);
      ctx.stroke();
      ctx.fillText(`${Math.round(ratio * 100)}%`, pad.left - 6, py + 3);
    }

    if (history.length < 2) {
      ctx.restore();
      return;
    }

    const xForIdx = (idx) => pad.left + (idx / (history.length - 1)) * plotW;

    // Etiquetas de tiempo en eje X
    ctx.textAlign = "center";
    const stepX = Math.max(1, Math.floor(history.length / 5));
    for (let i = 0; i < history.length; i += stepX) {
      ctx.fillText(history[i].timestamp || "", xForIdx(i), H - 8);
    }

    // Dibujar cada serie activa
    let headerOffset = pad.left;
    appState.activeSeries.forEach((key) => {
      const meta = SERIES_META[key];
      if (!meta) return;

      ctx.strokeStyle = meta.color;
      ctx.lineWidth = 2.2;
      ctx.beginPath();
      history.forEach((pt, idx) => {
        const val = Number(pt[key] ?? 0);
        const norm = Math.min(1, Math.max(0, (val - meta.min) / (meta.max - meta.min)));
        const px = xForIdx(idx);
        const py = pad.top + plotH - norm * plotH;
        if (idx === 0) ctx.moveTo(px, py);
        else ctx.lineTo(px, py);
      });
      ctx.stroke();

      // Lectura actual en la cabecera superior del gráfico
      const latestVal = Number(history[history.length - 1][key] ?? 0);
      ctx.fillStyle = meta.color;
      ctx.font = "700 11px monospace";
      ctx.textAlign = "left";
      const txt = `● ${meta.label}: ${latestVal.toFixed(2)} ${meta.unit}`;
      ctx.fillText(txt, headerOffset, 15);
      headerOffset += ctx.measureText(txt).width + 18;
    });

    // Crosshair interactivo si el usuario pasa el cursor
    if (appState.chartHoverIndex !== null && history[appState.chartHoverIndex]) {
      const idx = appState.chartHoverIndex;
      const hx = xForIdx(idx);
      const pt = history[idx];

      ctx.strokeStyle = "#94a3b8";
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 3]);
      ctx.beginPath();
      ctx.moveTo(hx, pad.top);
      ctx.lineTo(hx, pad.top + plotH);
      ctx.stroke();
      ctx.setLineDash([]);

      // Caja tooltip
      const lines = [
        `Hora: ${pt.timestamp}`,
        `Vel: ${pt.speed_mps} m/s`,
        `Corr: ${pt.current_a} A`,
        `Temp: ${pt.temp_c} °C`,
        `Carga: ${pt.load_kg} kg`,
      ];
      const boxW = 128;
      const boxH = 84;
      const bx = hx + 138 > W ? hx - boxW - 10 : hx + 10;
      const by = pad.top + 8;

      ctx.fillStyle = "rgba(255, 255, 255, 0.96)";
      ctx.strokeStyle = "#cbd5e1";
      roundRect(ctx, bx, by, boxW, boxH, 6, true, true);
      ctx.fillStyle = "#0f172a";
      ctx.font = "600 10.5px monospace";
      ctx.textAlign = "left";
      lines.forEach((ln, li) => {
        ctx.fillText(ln, bx + 8, by + 16 + li * 15);
      });
    }

    ctx.restore();
  }

  // ------------------------------------------------------------------
  // Sincronización DOM y Osciloscopio 10 Hz del Controlador PID
  // ------------------------------------------------------------------
  function updatePidDOM(pid) {
    const signFmt = (v, dec = 2) => `${v >= 0 ? "+" : ""}${Number(v).toFixed(dec)}`;

    const miniMode = document.getElementById("miniPidMode");
    if (miniMode) {
      miniMode.textContent = pid.mode === "AUTO" ? "AUTO" : "MANUAL";
      miniMode.style.color = pid.mode === "AUTO" ? "var(--emerald)" : "var(--amber)";
    }
    const miniCv = document.getElementById("miniPidCv");
    if (miniCv) miniCv.textContent = `${pid.cv_pct.toFixed(1)}%`;

    const pTermEl = document.getElementById("lblPidPTerm");
    if (!pTermEl) return;
    pTermEl.textContent = `${signFmt(pid.p_term, 2)} %`;
    document.getElementById("barPidPTerm").style.width = `${Math.min(100, Math.max(0, 50 + pid.p_term * 0.8))}%`;

    document.getElementById("lblPidITerm").textContent = `${signFmt(pid.i_term, 2)} %`;
    document.getElementById("barPidITerm").style.width = `${Math.min(100, Math.max(0, pid.i_term))}%`;

    document.getElementById("lblPidDTerm").textContent = `${signFmt(pid.d_term, 2)} %`;
    document.getElementById("barPidDTerm").style.width = `${Math.min(100, Math.max(0, 50 + pid.d_term * 1.2))}%`;

    const syncVal = (id, val) => {
      const el = document.getElementById(id);
      if (el && document.activeElement !== el) el.value = val;
    };
    const syncChk = (id, checked) => {
      const el = document.getElementById(id);
      if (el && document.activeElement !== el) el.checked = !!checked;
    };

    syncChk("chkPidPEnabled", pid.p_enabled);
    syncVal("sliderPidKp", pid.kp);
    syncVal("numPidKp", pid.kp);

    syncChk("chkPidIEnabled", pid.i_enabled);
    syncVal("sliderPidKi", pid.ki);
    syncVal("numPidKi", pid.ki);

    syncChk("chkPidDEnabled", pid.d_enabled);
    syncVal("sliderPidKd", pid.kd);
    syncVal("numPidKd", pid.kd);

    syncVal("sliderPidTf", pid.filter_tf);
    document.getElementById("lblPidTf").textContent = `${pid.filter_tf.toFixed(2)} s`;

    syncVal("sliderPidSp", pid.setpoint_mps);
    syncVal("numPidSp", pid.setpoint_mps);
    document.getElementById("lblPidSpVal").textContent = `${pid.setpoint_mps.toFixed(2)} m/s`;

    syncVal("numPidCvMin", pid.cv_min);
    syncVal("numPidCvMax", pid.cv_max);

    const isAuto = pid.mode === "AUTO";
    document.getElementById("btnPidModeAuto").className = `btn btn-sm ${isAuto ? "btn-active-choice" : ""}`;
    document.getElementById("btnPidModeManual").className = `btn btn-sm ${!isAuto ? "btn-active-choice" : ""}`;
    const manWrap = document.getElementById("manualCvContainer");
    const manSlider = document.getElementById("sliderPidManualCv");
    manWrap.style.opacity = isAuto ? "0.5" : "1";
    manSlider.disabled = isAuto;
    syncVal("sliderPidManualCv", pid.manual_cv);
    document.getElementById("lblPidManualCv").textContent = `${pid.manual_cv.toFixed(1)}%`;

    syncVal("sliderDisturbance", pid.disturbance_pct);
    document.getElementById("lblDisturbancePct").textContent = `${pid.disturbance_pct.toFixed(1)}%`;

    if (pid.active_preset) {
      syncVal("selectPidPreset", pid.active_preset);
    }
  }

  function drawPidOscilloscope() {
    const canvas = document.getElementById("pidOscilloscope");
    if (!canvas || !appState.snapshot || !appState.snapshot.pid) return;

    const pid = appState.snapshot.pid;
    const hist = pid.history || [];
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    if (rect.width < 20 || rect.height < 20) return;

    const targetW = Math.round(rect.width * dpr);
    const targetH = Math.round(rect.height * dpr);
    if (canvas.width !== targetW || canvas.height !== targetH) {
      canvas.width = targetW;
      canvas.height = targetH;
    }

    const ctx = canvas.getContext("2d");
    ctx.save();
    ctx.scale(dpr, dpr);

    const W = rect.width;
    const H = rect.height;
    ctx.clearRect(0, 0, W, H);

    const pad = { top: 28, right: 44, bottom: 26, left: 46 };
    const plotW = W - pad.left - pad.right;
    const plotH = H - pad.top - pad.bottom;
    const maxSpeedScale = 3.2;

    ctx.strokeStyle = "#e2e8f0";
    ctx.lineWidth = 1;
    ctx.font = "600 10px monospace";
    for (let i = 0; i <= 4; i++) {
      const ratio = i / 4;
      const py = pad.top + plotH - ratio * plotH;
      ctx.beginPath();
      ctx.moveTo(pad.left, py);
      ctx.lineTo(pad.left + plotW, py);
      ctx.stroke();

      ctx.fillStyle = "#2563eb";
      ctx.textAlign = "right";
      ctx.fillText(`${(ratio * maxSpeedScale).toFixed(1)}`, pad.left - 6, py + 3);

      ctx.fillStyle = "#059669";
      ctx.textAlign = "left";
      ctx.fillText(`${Math.round(ratio * 100)}%`, pad.left + plotW + 6, py + 3);
    }

    if (hist.length < 2) {
      ctx.restore();
      return;
    }

    const xAt = (idx) => pad.left + (idx / (hist.length - 1)) * plotW;
    const ySpeed = (mps) => pad.top + plotH - Math.min(1, Math.max(0, mps / maxSpeedScale)) * plotH;
    const yPct = (pct) => pad.top + plotH - Math.min(1, Math.max(0, pct / 100.0)) * plotH;

    ctx.fillStyle = "rgba(37, 99, 235, 0.07)";
    ctx.beginPath();
    ctx.moveTo(xAt(0), pad.top + plotH);
    hist.forEach((pt, idx) => ctx.lineTo(xAt(idx), ySpeed(pt.pv)));
    ctx.lineTo(xAt(hist.length - 1), pad.top + plotH);
    ctx.closePath();
    ctx.fill();

    ctx.strokeStyle = "#10b981";
    ctx.lineWidth = 1.9;
    ctx.beginPath();
    hist.forEach((pt, idx) => {
      const px = xAt(idx);
      const py = yPct(pt.cv_pct);
      if (idx === 0) ctx.moveTo(px, py);
      else ctx.lineTo(px, py);
    });
    ctx.stroke();

    ctx.strokeStyle = "#dc2626";
    ctx.lineWidth = 2.0;
    ctx.setLineDash([6, 4]);
    ctx.beginPath();
    hist.forEach((pt, idx) => {
      const px = xAt(idx);
      const py = ySpeed(pt.sp);
      if (idx === 0) ctx.moveTo(px, py);
      else ctx.lineTo(px, py);
    });
    ctx.stroke();
    ctx.setLineDash([]);

    ctx.strokeStyle = "#2563eb";
    ctx.lineWidth = 2.5;
    ctx.beginPath();
    hist.forEach((pt, idx) => {
      const px = xAt(idx);
      const py = ySpeed(pt.pv);
      if (idx === 0) ctx.moveTo(px, py);
      else ctx.lineTo(px, py);
    });
    ctx.stroke();

    ctx.fillStyle = "#64748b";
    ctx.textAlign = "center";
    const stepT = Math.max(1, Math.floor(hist.length / 5));
    for (let i = 0; i < hist.length; i += stepT) {
      ctx.fillText(hist[i].timestamp || "", xAt(i), H - 7);
    }

    ctx.fillStyle = "#0f172a";
    ctx.font = "700 11px monospace";
    ctx.textAlign = "left";
    ctx.fillText(
      `Meta: ${pid.setpoint_mps.toFixed(2)} m/s  |  Real: ${pid.pv_mps.toFixed(2)} m/s  |  Potencia: ${pid.cv_pct.toFixed(1)}%`,
      pad.left,
      16
    );

    ctx.restore();
  }

  // ------------------------------------------------------------------
  // Conexión WebSocket Bidireccional + Latido Ping/Pong + Respaldo HTTP
  // ------------------------------------------------------------------
  function connectRealtimeTelemetry() {
    const wsProto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${wsProto}//${window.location.host}/ws/telemetry`;
    let socket;

    if (appState.wsPingTimer) {
      clearInterval(appState.wsPingTimer);
      appState.wsPingTimer = null;
    }

    try {
      socket = new WebSocket(wsUrl);
      appState.wsSocket = socket;
    } catch (e) {
      appState.wsConnected = false;
      setTimeout(connectRealtimeTelemetry, 2500);
      return;
    }

    socket.onopen = () => {
      appState.wsConnected = true;
      document.getElementById("wsDot").style.background = "#10b981";
      document.getElementById("wsStatusText").textContent = "En línea";
      appState.wsPingTimer = setInterval(() => {
        if (socket.readyState === WebSocket.OPEN) {
          try {
            socket.send(JSON.stringify({ type: "ping", client_ts: Date.now() }));
          } catch (_) {}
        }
      }, 15000);
    };

    socket.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        if (msg.type === "bootstrap") {
          ingestBootstrap(msg);
        } else if (msg.type === "telemetry" && msg.snapshot) {
          ingestSnapshot(msg.snapshot);
        } else if (msg.type === "rag_overview" && msg.overview) {
          renderRagOverview(msg.overview);
        }
      } catch (_) {}
    };

    socket.onclose = () => {
      appState.wsConnected = false;
      if (appState.wsPingTimer) {
        clearInterval(appState.wsPingTimer);
        appState.wsPingTimer = null;
      }
      document.getElementById("wsDot").style.background = "#f59e0b";
      document.getElementById("wsStatusText").textContent = "Conectando";
      setTimeout(connectRealtimeTelemetry, 2500);
    };

    socket.onerror = () => {
      try {
        socket.close();
      } catch (_) {}
    };
  }

  // Respaldo HTTP automático únicamente mientras el WebSocket se reconecta
  setInterval(async () => {
    if (!appState.wsConnected) {
      await syncFullState(false);
    }
  }, 1500);

  // ------------------------------------------------------------------
  // Eventos de Interfaz e Interactividad Completa
  // ------------------------------------------------------------------
  function focusPidStation() {
    const scadaPanel = document.getElementById("view-scada");
    document.querySelectorAll(".view-panel").forEach((p) => p.classList.remove("active"));
    if (scadaPanel) scadaPanel.classList.add("active");
    const pidBox = document.getElementById("pidStationContainer");
    if (pidBox) {
      pidBox.scrollIntoView({ block: "start" });
      pidBox.style.boxShadow = "0 0 0 3px rgba(37, 99, 235, 0.35)";
      setTimeout(() => {
        pidBox.style.boxShadow = "";
      }, 1400);
    }
    drawPidOscilloscope();
  }

  function bindEvents() {
    // Cambio de pestañas
    document.querySelectorAll(".nav-tab").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll(".nav-tab").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        const viewId = btn.dataset.view;
        if (viewId === "pid") {
          focusPidStation();
          return;
        }
        document.querySelectorAll(".view-panel").forEach((p) => p.classList.remove("active"));
        const panel = document.getElementById(`view-${viewId}`);
        if (panel) panel.classList.add("active");
        if (viewId === "scada") window.scrollTo(0, 0);
        if (viewId === "rag") loadRagOverview();
        drawTelemetryChart();
        drawPidOscilloscope();
      });
    });

    // Maniobras de motor y seguridad
    document.getElementById("btnStart").addEventListener("click", () => sendPlcCommand("start"));
    document.getElementById("btnPause").addEventListener("click", () => sendPlcCommand("pause"));
    document.getElementById("btnStop").addEventListener("click", () => sendPlcCommand("stop"));
    document.getElementById("btnEstop").addEventListener("click", () => {
      sendPlcCommand("emergency_stop");
      showToast("¡Parada de emergencia activada!", "error");
    });
    document.getElementById("btnTopEstop").addEventListener("click", () => {
      sendPlcCommand("emergency_stop");
      showToast("¡Parada de emergencia activada!", "error");
    });
    document.getElementById("btnResetFault").addEventListener("click", () => {
      sendPlcCommand("reset_fault");
      showToast("Seguridades rearmadas. Sistema listo.", "success");
    });
    document.getElementById("btnBannerReset").addEventListener("click", () => {
      sendPlcCommand("reset_fault");
      showToast("Alarma rearmada correctamente.", "success");
    });
    document.getElementById("btnBannerRestart").addEventListener("click", async () => {
      await sendPlcCommand("reset_fault");
      await sendPlcCommand("start");
      showToast("Sistema rearmado y puesto en marcha.", "success");
    });

    // Velocidad VFD con sincronización en tiempo real al arrastrar
    const sliderSpeed = document.getElementById("sliderSpeed");
    const syncSpeedLive = throttle((v) => sendPlcCommand("set_speed", v), 120);
    sliderSpeed.addEventListener("input", () => {
      const val = Number(sliderSpeed.value);
      document.getElementById("lblSpeedSlider").textContent = `${val.toFixed(2)} m/s`;
      syncSpeedLive(val);
    });
    sliderSpeed.addEventListener("change", () => {
      sendPlcCommand("set_speed", Number(sliderSpeed.value));
    });
    document.querySelectorAll(".speed-preset").forEach((b) => {
      b.addEventListener("click", () => {
        const v = Number(b.dataset.speed);
        sliderSpeed.value = v;
        document.getElementById("lblSpeedSlider").textContent = `${v.toFixed(2)} m/s`;
        sendPlcCommand("set_speed", v);
      });
    });

    // Dirección y Alimentador
    document.getElementById("btnDirForward").addEventListener("click", () => sendPlcCommand("set_direction", "FORWARD"));
    document.getElementById("btnDirReverse").addEventListener("click", () => sendPlcCommand("set_direction", "REVERSE"));

    document.getElementById("chkAutoFeed").addEventListener("change", (e) => {
      sendPlcCommand("set_auto_feed", e.target.checked);
    });
    const sliderFeed = document.getElementById("sliderFeedRate");
    const syncFeedLive = throttle((v) => sendPlcCommand("set_feed_rate", v), 140);
    sliderFeed.addEventListener("input", () => {
      document.getElementById("lblFeedRate").textContent = sliderFeed.value;
      syncFeedLive(Number(sliderFeed.value));
    });
    sliderFeed.addEventListener("change", () => {
      sendPlcCommand("set_feed_rate", Number(sliderFeed.value));
    });
    document.getElementById("chkAutoDivert").addEventListener("change", (e) => {
      sendPlcCommand("set_auto_divert", e.target.checked);
    });

    // Inyección de cajas y fallas
    document.querySelectorAll(".spawn-btn").forEach((b) => {
      b.addEventListener("click", () => {
        sendPlcCommand("spawn_item", b.dataset.cat);
      });
    });
    document.querySelectorAll(".fault-btn").forEach((b) => {
      b.addEventListener("click", () => {
        sendPlcCommand("inject_fault", b.dataset.fault);
        showToast("Prueba de falla activada.", "error");
      });
    });
    document.getElementById("btnClearBelt").addEventListener("click", () => sendPlcCommand("clear_belt"));
    document.getElementById("btnResetCounters").addEventListener("click", () => sendPlcCommand("reset_counters"));

    // Series de gráfica y hover
    document.querySelectorAll(".series-toggle").forEach((btn) => {
      btn.addEventListener("click", () => {
        const key = btn.dataset.series;
        if (appState.activeSeries.has(key)) {
          if (appState.activeSeries.size > 1) {
            appState.activeSeries.delete(key);
            btn.classList.remove("active");
          }
        } else {
          appState.activeSeries.add(key);
          btn.classList.add("active");
        }
        drawTelemetryChart();
      });
    });

    const chartCanvas = document.getElementById("telemetryChart");
    chartCanvas.addEventListener("mousemove", (ev) => {
      if (!appState.snapshot || !appState.snapshot.history) return;
      const hist = appState.snapshot.history;
      if (hist.length < 2) return;
      const rect = chartCanvas.getBoundingClientRect();
      const relX = ev.clientX - rect.left - 42;
      const plotW = rect.width - 60;
      const ratio = Math.min(1, Math.max(0, relX / plotW));
      appState.chartHoverIndex = Math.round(ratio * (hist.length - 1));
      drawTelemetryChart();
    });
    chartCanvas.addEventListener("mouseleave", () => {
      appState.chartHoverIndex = null;
      drawTelemetryChart();
    });

    // --- CONTROLES INDIVIDUALES DEL REGULADOR PID ---
    const jumpPidBtn = document.getElementById("btnJumpToPid");
    if (jumpPidBtn) jumpPidBtn.addEventListener("click", () => focusPidStation());

    // 1. Proporcional Individual (Switch P + Slider Kp + Input Kp)
    const syncPidLive = throttle((payload) => sendPidUpdate(payload), 120);
    document.getElementById("chkPidPEnabled").addEventListener("change", (e) => {
      sendPidUpdate({ p_enabled: e.target.checked });
    });
    document.getElementById("sliderPidKp").addEventListener("input", (e) => {
      document.getElementById("numPidKp").value = e.target.value;
      syncPidLive({ kp: Number(e.target.value) });
    });
    document.getElementById("sliderPidKp").addEventListener("change", (e) => {
      sendPidUpdate({ kp: Number(e.target.value) });
    });
    document.getElementById("numPidKp").addEventListener("change", (e) => {
      sendPidUpdate({ kp: Number(e.target.value) });
    });

    // 2. Integral Individual (Switch I + Slider Ki + Input Ki + Reset Integral)
    document.getElementById("chkPidIEnabled").addEventListener("change", (e) => {
      sendPidUpdate({ i_enabled: e.target.checked });
    });
    document.getElementById("sliderPidKi").addEventListener("input", (e) => {
      document.getElementById("numPidKi").value = e.target.value;
      syncPidLive({ ki: Number(e.target.value) });
    });
    document.getElementById("sliderPidKi").addEventListener("change", (e) => {
      sendPidUpdate({ ki: Number(e.target.value) });
    });
    document.getElementById("numPidKi").addEventListener("change", (e) => {
      sendPidUpdate({ ki: Number(e.target.value) });
    });
    document.getElementById("btnResetIntegral").addEventListener("click", () => {
      sendPidUpdate({ reset_integral: true });
      showToast("Memoria del control Integral reiniciada.", "info");
    });

    // 3. Derivativo Individual (Switch D + Slider Kd + Input Kd + Filtro Tf)
    document.getElementById("chkPidDEnabled").addEventListener("change", (e) => {
      sendPidUpdate({ d_enabled: e.target.checked });
    });
    document.getElementById("sliderPidKd").addEventListener("input", (e) => {
      document.getElementById("numPidKd").value = e.target.value;
      syncPidLive({ kd: Number(e.target.value) });
    });
    document.getElementById("sliderPidKd").addEventListener("change", (e) => {
      sendPidUpdate({ kd: Number(e.target.value) });
    });
    document.getElementById("numPidKd").addEventListener("change", (e) => {
      sendPidUpdate({ kd: Number(e.target.value) });
    });
    document.getElementById("sliderPidTf").addEventListener("input", (e) => {
      document.getElementById("lblPidTf").textContent = `${Number(e.target.value).toFixed(2)} s`;
      syncPidLive({ filter_tf: Number(e.target.value) });
    });
    document.getElementById("sliderPidTf").addEventListener("change", (e) => {
      sendPidUpdate({ filter_tf: Number(e.target.value) });
    });

    // Botones de ajuste fino (- / +) para Kp, Ki, Kd
    document.querySelectorAll(".pid-step-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const param = btn.dataset.param;
        const delta = Number(btn.dataset.delta);
        const curPid = (appState.snapshot && appState.snapshot.pid) || { kp: 36, ki: 26, kd: 4.2 };
        const nextVal = Math.max(0, Number((Number(curPid[param] || 0) + delta).toFixed(2)));
        sendPidUpdate({ [param]: nextVal });
      });
    });

    // Modo AUTO / MANUAL, Velocidad Meta, Salida Manual y Límites
    document.getElementById("btnPidModeAuto").addEventListener("click", () => {
      sendPidUpdate({ mode: "AUTO" });
      showToast("Modo Automático activado.", "success");
    });
    document.getElementById("btnPidModeManual").addEventListener("click", () => {
      sendPidUpdate({ mode: "MANUAL" });
      showToast("Modo Manual activado. Ajuste la potencia directamente.", "info");
    });

    document.getElementById("sliderPidSp").addEventListener("input", (e) => {
      const val = Number(e.target.value);
      document.getElementById("numPidSp").value = val;
      document.getElementById("lblPidSpVal").textContent = `${val.toFixed(2)} m/s`;
      syncPidLive({ setpoint_mps: val });
    });
    document.getElementById("sliderPidSp").addEventListener("change", (e) => {
      sendPidUpdate({ setpoint_mps: Number(e.target.value) });
    });
    document.getElementById("numPidSp").addEventListener("change", (e) => {
      sendPidUpdate({ setpoint_mps: Number(e.target.value) });
    });

    document.getElementById("sliderPidManualCv").addEventListener("input", (e) => {
      const val = Number(e.target.value);
      document.getElementById("lblPidManualCv").textContent = `${val.toFixed(1)}%`;
      syncPidLive({ manual_cv: val });
    });
    document.getElementById("sliderPidManualCv").addEventListener("change", (e) => {
      sendPidUpdate({ manual_cv: Number(e.target.value) });
    });

    document.getElementById("numPidCvMin").addEventListener("change", (e) => {
      sendPidUpdate({ cv_min: Number(e.target.value) });
    });
    document.getElementById("numPidCvMax").addEventListener("change", (e) => {
      sendPidUpdate({ cv_max: Number(e.target.value) });
    });

    // Modos recomendados y pruebas rápidas
    document.getElementById("selectPidPreset").addEventListener("change", (e) => {
      if (e.target.value === "custom") return;
      sendPidUpdate({ preset: e.target.value });
      showToast("Modo de control aplicado.", "success");
    });

    document.getElementById("btnStepUp").addEventListener("click", () => {
      const curSp = (appState.snapshot && appState.snapshot.pid && appState.snapshot.pid.setpoint_mps) || 1.4;
      const nextSp = Math.min(3.0, Number((curSp + 0.6).toFixed(2)));
      sendPidUpdate({ setpoint_mps: nextSp });
      showToast(`Velocidad meta ajustada a ${nextSp.toFixed(2)} m/s`, "info");
    });

    document.getElementById("btnStepDown").addEventListener("click", () => {
      const curSp = (appState.snapshot && appState.snapshot.pid && appState.snapshot.pid.setpoint_mps) || 1.4;
      const nextSp = Math.max(0.3, Number((curSp - 0.6).toFixed(2)));
      sendPidUpdate({ setpoint_mps: nextSp });
      showToast(`Velocidad meta ajustada a ${nextSp.toFixed(2)} m/s`, "info");
    });

    document.getElementById("btnPulseDisturbance").addEventListener("click", () => {
      sendPidUpdate({ pulse_disturbance: true });
      showToast("Carga extra temporal (30% · 4 s) aplicada en la faja.", "info");
    });

    document.getElementById("sliderDisturbance").addEventListener("input", (e) => {
      const val = Number(e.target.value);
      document.getElementById("lblDisturbancePct").textContent = `${val.toFixed(1)}%`;
      syncPidLive({ disturbance_pct: val });
    });
    document.getElementById("sliderDisturbance").addEventListener("change", (e) => {
      sendPidUpdate({ disturbance_pct: Number(e.target.value) });
    });

    document.getElementById("btnResetPidMetrics").addEventListener("click", () => {
      sendPidUpdate({ reset_metrics: true });
      showToast("Contadores de respuesta reiniciados.", "info");
    });

    window.addEventListener("resize", () => {
      drawTelemetryChart();
      drawPidOscilloscope();
    });

    const refreshWithLoader = async () => {
      runLogoSpinner5s();
      await syncFullState(true);
    };

    const brandLogo = document.getElementById("brandLogoContainer");
    if (brandLogo) {
      brandLogo.addEventListener("click", refreshWithLoader);
    }
    const replayLogoBtn = document.getElementById("btnReplayLogoLoader");
    if (replayLogoBtn) {
      replayLogoBtn.addEventListener("click", refreshWithLoader);
    }

    bindRagEvents();
  }

  // ------------------------------------------------------------------
  // AGENTE RAG MULTIAGENTE (.md + OpenAI -> Groq -> Gemini -> Ollama)
  // ------------------------------------------------------------------
  function escapeHtmlSafe(str) {
    return String(str || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function formatAnswerMarkdown(text) {
    const escaped = escapeHtmlSafe(text);
    const withInline = escaped
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/\*(.+?)\*/g, "<em>$1</em>")
      .replace(/`([^`]+)`/g, '<code class="font-mono text-[11px] bg-slate-100 px-1 py-0.5 rounded">$1</code>');
    return withInline
      .split(/\n{2,}/)
      .map((para) => `<p class="mb-2 last:mb-0 leading-relaxed">${para.replace(/\n/g, "<br/>")}</p>`)
      .join("");
  }

  function renderCleanDocumentHtml(rawText) {
    let txt = String(rawText || "").trim();
    // Omitir bloque YAML superior si existe
    if (txt.startsWith("---")) {
      const parts = txt.split("---");
      if (parts.length >= 3) {
        txt = parts.slice(2).join("---").trim();
      }
    }
    return txt
      .split(/\n/)
      .map((line) => {
        const trimmed = line.trim();
        if (!trimmed) return '<div class="h-2"></div>';
        if (trimmed.startsWith("### ")) {
          return `<h4 class="text-xs font-bold text-slate-800 mt-3 mb-1">${escapeHtmlSafe(trimmed.slice(4))}</h4>`;
        }
        if (trimmed.startsWith("## ")) {
          return `<h3 class="text-sm font-bold text-blue-700 mt-3.5 mb-1">${escapeHtmlSafe(trimmed.slice(3))}</h3>`;
        }
        if (trimmed.startsWith("# ")) {
          return `<h2 class="text-base font-extrabold text-slate-900 mb-2">${escapeHtmlSafe(trimmed.slice(2))}</h2>`;
        }
        if (trimmed.startsWith("- ")) {
          const itemTxt = escapeHtmlSafe(trimmed.slice(2)).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
          return `<div class="pl-3 py-0.5 text-xs text-slate-700">• ${itemTxt}</div>`;
        }
        const cleanLine = escapeHtmlSafe(trimmed)
          .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
          .replace(/\*(.+?)\*/g, "<em>$1</em>");
        return `<p class="text-xs text-slate-700 leading-relaxed mb-1.5">${cleanLine}</p>`;
      })
      .join("");
  }

  async function openRagModal(docKey, displayTitle) {
    const modal = document.getElementById("ragDocModal");
    const titleEl = document.getElementById("ragModalTitle");
    const bodyEl = document.getElementById("ragModalBody");
    if (!modal || !titleEl || !bodyEl) return;
    try {
      const res = await apiFetch(`/api/v1/rag/documents/${encodeURIComponent(docKey)}`);
      titleEl.textContent = displayTitle || "Documento";
      bodyEl.innerHTML = renderCleanDocumentHtml(res.content || "");
      modal.classList.remove("hidden");
      modal.classList.add("flex");
    } catch (err) {
      showToast("No se pudo abrir el documento.", "error");
    }
  }

  function renderRagOverview(data) {
    if (!data) return;
    const agents = data.agents || [];
    const docs = data.documents || [];

    const badgeSync = document.getElementById("badgeRagSyncTime");
    if (badgeSync) {
      badgeSync.textContent = "En línea";
    }
    const docsCountLbl = document.getElementById("lblRagDocsCount");
    if (docsCountLbl) {
      docsCountLbl.textContent = `${docs.length} ${docs.length === 1 ? "documento" : "documentos"}`;
    }

    if (data.llm && data.llm.providers) {
      const p = data.llm.providers;
      const setProvUi = (idSuffix, provObj, defaultLabel) => {
        const lbl = document.getElementById(`lblStatus${idSuffix}`);
        if (lbl && provObj) {
          lbl.textContent = provObj.configured ? "Conectado" : defaultLabel;
          lbl.className = `badge ${provObj.configured ? "badge-success" : "badge-info"}`;
        }
      };
      setProvUi("Openai", p.openai, "Opcional");
      setProvUi("Groq", p.groq, "Opcional");
      setProvUi("Gemini", p.gemini, "Opcional");
      setProvUi("Ollama", p.ollama, "Disponible");

      const selProv = document.getElementById("selectRagProvider");
      if (selProv && data.llm.preferred_provider) {
        selProv.value = data.llm.preferred_provider;
      }
      const selWeb = document.getElementById("selectWebSearchMode");
      if (selWeb && document.activeElement !== selWeb && data.llm.web_search_mode) {
        selWeb.value = data.llm.web_search_mode;
      }

      if (data.llm.web_search) {
        const tav = data.llm.web_search.tavily;
        const lblTav = document.getElementById("lblStatusTavily");
        if (lblTav) {
          lblTav.textContent = tav && tav.configured ? "Conectada" : "Activa";
          lblTav.className = "badge badge-success";
        }
      }

      if (p.ollama) {
        const m = document.getElementById("inputOllamaModel");
        if (m && document.activeElement !== m) m.value = p.ollama.model || "llama3.2";
      }
    }

    // Tarjetas limpias de especialidades (sin nombres de archivo ni datos técnicos)
    const agentsGrid = document.getElementById("ragAgentsGrid");
    if (agentsGrid) {
      agentsGrid.innerHTML = agents
        .map(
          (ag) => `
          <div class="bg-slate-50 border border-slate-200 rounded-xl p-3 flex flex-col justify-between gap-1.5">
            <div class="flex items-center justify-between gap-2">
              <span class="text-xs font-extrabold text-slate-900">${escapeHtmlSafe(ag.icon)} ${escapeHtmlSafe(ag.name)}</span>
              <button type="button" data-agent-md="${escapeHtmlSafe(ag.filename)}" data-agent-name="${escapeHtmlSafe(ag.name)}" class="btn-view-agent-md text-[11px] font-semibold text-blue-600 hover:underline cursor-pointer">
                Ver rol
              </button>
            </div>
            <div class="text-[11px] text-slate-500">${escapeHtmlSafe(ag.role)}</div>
          </div>`
        )
        .join("");

      agentsGrid.querySelectorAll(".btn-view-agent-md").forEach((btn) => {
        btn.addEventListener("click", () => {
          openRagModal(`agent:${btn.dataset.agentMd}`, btn.dataset.agentName);
        });
      });
    }

    // Lista limpia de Documentos (sin extensiones .md ni conteo de fragmentos)
    const docsList = document.getElementById("ragDocsList");
    if (docsList) {
      if (!docs.length) {
        docsList.innerHTML = `<div class="text-xs text-slate-500 text-center py-4">No hay documentos guardados aún.</div>`;
      } else {
        docsList.innerHTML = docs
          .map(
            (d) => `
            <div class="border border-slate-200 bg-slate-50/70 hover:bg-white rounded-xl p-3 flex items-start justify-between gap-2.5 transition-colors">
              <div class="min-w-0 flex-1">
                <div class="flex items-center gap-1.5 flex-wrap">
                  <span class="text-xs font-bold text-slate-900 truncate">${escapeHtmlSafe(d.title)}</span>
                  ${
                    d.builtin
                      ? '<span class="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-blue-50 text-blue-700 border border-blue-200">Guía</span>'
                      : '<span class="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-emerald-50 text-emerald-700 border border-emerald-200">Agregado</span>'
                  }
                </div>
                <p class="text-[11px] text-slate-500 mt-1 line-clamp-2">${escapeHtmlSafe(d.preview || "")}</p>
              </div>
              <div class="flex items-center gap-1 shrink-0">
                <button type="button" data-doc-view="${escapeHtmlSafe(d.filename)}" data-doc-title="${escapeHtmlSafe(d.title)}" class="btn btn-sm btn-view-rag-doc">Ver</button>
                ${
                  d.builtin
                    ? ""
                    : `<button type="button" data-doc-del="${escapeHtmlSafe(d.filename)}" class="btn btn-sm text-red-600 hover:bg-red-50 btn-del-rag-doc" title="Eliminar documento">✕</button>`
                }
              </div>
            </div>`
          )
          .join("");

        docsList.querySelectorAll(".btn-view-rag-doc").forEach((b) => {
          b.addEventListener("click", () => openRagModal(b.dataset.docView, b.dataset.docTitle));
        });
        docsList.querySelectorAll(".btn-del-rag-doc").forEach((b) => {
          b.addEventListener("click", async () => {
            const fname = b.dataset.docDel;
            try {
              const res = await apiFetch(`/api/v1/rag/documents/${encodeURIComponent(fname)}`, { method: "DELETE" });
              renderRagOverview(res.overview);
              showToast("Documento eliminado.", "info");
            } catch (err) {
              showToast(err.message, "error");
            }
          });
        });
      }
    }

    // Sincronizar historial de conversación con el backend (sin duplicar mensajes)
    if (Array.isArray(data.history)) {
      const box = document.getElementById("ragChatMessages");
      if (box) {
        if (!appState.welcomeChatHtml) {
          appState.welcomeChatHtml = box.innerHTML;
        }
        if (data.history.length === 0 && appState.renderedTurnIds.size > 0) {
          appState.renderedTurnIds.clear();
          box.innerHTML = appState.welcomeChatHtml;
        } else {
          data.history.forEach((turn) => appendRagChatTurn(turn));
        }
      }
    }
  }

  async function loadRagOverview() {
    try {
      const ov = await apiFetch("/api/v1/rag/overview");
      renderRagOverview(ov);
    } catch (_) {}
  }

  function appendRagChatTurn(turn) {
    const box = document.getElementById("ragChatMessages");
    if (!box || !turn) return;

    if (!appState.welcomeChatHtml) {
      appState.welcomeChatHtml = box.innerHTML;
    }

    const turnKey = turn.turn_id || `${turn.timestamp || ""}:${turn.query || ""}`;
    if (appState.renderedTurnIds.has(turnKey)) {
      return;
    }
    appState.renderedTurnIds.add(turnKey);

    const webInfo = turn.web_search || {};
    const webResults = webInfo.results || [];

    const agentsHtml = (turn.active_agents || [])
      .map(
        (a) =>
          `<span class="inline-flex items-center gap-1 text-[10.5px] font-semibold px-2 py-0.5 rounded-full bg-violet-50 text-violet-700 border border-violet-200">${escapeHtmlSafe(a.icon)} ${escapeHtmlSafe(a.name)}</span>`
      )
      .join("");

    // Mostrar títulos únicos de documentos sin nombres técnicos de archivo
    const seenDocs = new Set();
    const uniqueSources = (turn.sources || []).filter((s) => {
      if (seenDocs.has(s.document)) return false;
      seenDocs.add(s.document);
      return true;
    });

    const sourcesHtml = uniqueSources
      .map(
        (s) =>
          `<button type="button" data-src-doc="${escapeHtmlSafe(s.document)}" data-src-title="${escapeHtmlSafe(s.title || s.section)}" class="rag-cite-pill inline-flex items-center gap-1 text-[10.5px] font-medium px-2 py-0.5 rounded bg-blue-50 hover:bg-blue-100 text-blue-700 border border-blue-200 cursor-pointer">📄 ${escapeHtmlSafe(s.title || s.section)}</button>`
      )
      .join("");

    const webCardsHtml = webResults
      .map(
        (w) => `
          <a href="${escapeHtmlSafe(w.url)}" target="_blank" rel="noopener noreferrer" class="block bg-slate-50 hover:bg-cyan-50/60 border border-slate-200 hover:border-cyan-300 rounded-xl p-2.5 no-underline transition-colors">
            <div class="flex items-center justify-between gap-2">
              <span class="text-xs font-bold text-blue-700 truncate">${escapeHtmlSafe(w.title)}</span>
              <span class="text-[10px] text-slate-500 shrink-0">Abrir ↗</span>
            </div>
            ${
              w.snippet
                ? `<p class="text-[11px] text-slate-600 mt-1 line-clamp-2">${escapeHtmlSafe(w.snippet)}</p>`
                : ""
            }
          </a>`
      )
      .join("");

    const wrapper = document.createElement("div");
    wrapper.className = "space-y-2";
    wrapper.innerHTML = `
      <div class="flex justify-end">
        <div class="bg-blue-600 text-white rounded-2xl rounded-tr-sm px-4 py-2.5 max-w-[85%] text-xs shadow-2xs">
          ${escapeHtmlSafe(turn.query)}
        </div>
      </div>
      <div class="bg-white border border-slate-200 rounded-2xl rounded-tl-sm p-4 shadow-2xs space-y-2.5">
        <div class="flex items-center gap-1.5 flex-wrap">${agentsHtml}</div>
        <div class="text-xs text-slate-800">${formatAnswerMarkdown(turn.answer)}</div>
        ${
          sourcesHtml
            ? `<div class="pt-2 border-t border-slate-100 flex items-center gap-1.5 flex-wrap"><span class="text-[10.5px] font-semibold text-slate-400">Documentos:</span>${sourcesHtml}</div>`
            : ""
        }
        ${
          webCardsHtml
            ? `<div class="pt-2.5 border-t border-slate-100 space-y-2">
                <div class="flex items-center justify-between gap-2">
                  <span class="text-[11px] font-bold text-slate-700">🌐 Enlaces relacionados</span>
                  <button type="button" class="btn-save-web-rag text-[11px] font-semibold text-emerald-700 hover:underline cursor-pointer">📥 Guardar en Mis Documentos</button>
                </div>
                <div class="grid grid-cols-1 md:grid-cols-2 gap-2">${webCardsHtml}</div>
               </div>`
            : ""
        }
      </div>
    `;
    wrapper.querySelectorAll(".rag-cite-pill").forEach((pill) => {
      pill.addEventListener("click", () => openRagModal(pill.dataset.srcDoc, pill.dataset.srcTitle));
    });
    const btnSaveWeb = wrapper.querySelector(".btn-save-web-rag");
    if (btnSaveWeb && webResults.length) {
      btnSaveWeb.addEventListener("click", async () => {
        const mdBody = [
          `# Consulta: ${turn.query}`,
          "",
          ...webResults.map(
            (w, i) => `## ${i + 1}. ${w.title}\n- Enlace: ${w.url}\n- Resumen: ${w.snippet || ""}\n`
          ),
        ].join("\n");
        try {
          const res = await apiFetch("/api/v1/rag/documents/text", {
            method: "POST",
            body: JSON.stringify({ title: `Consulta · ${turn.query.slice(0, 42)}`, content: mdBody }),
          });
          renderRagOverview(res.overview);
          btnSaveWeb.textContent = "✓ Guardado";
          btnSaveWeb.disabled = true;
          showToast("Información guardada en Mis Documentos.", "success");
        } catch (err) {
          showToast(err.message, "error");
        }
      });
    }
    box.appendChild(wrapper);
    box.scrollTop = box.scrollHeight;
  }

  async function autoSyncPendingConfigInputs() {
    const kOpenai = (document.getElementById("inputOpenaiKey")?.value || "").trim();
    const kGroq = (document.getElementById("inputGroqKey")?.value || "").trim();
    const kGemini = (document.getElementById("inputGeminiKey")?.value || "").trim();
    const kTavily = (document.getElementById("inputTavilyKey")?.value || "").trim();
    if (!kOpenai && !kGroq && !kGemini && !kTavily) return;

    const selProv = document.getElementById("selectRagProvider");
    const selWeb = document.getElementById("selectWebSearchMode");
    await apiFetch("/api/v1/rag/llm-config", {
      method: "POST",
      body: JSON.stringify({
        preferred_provider: selProv ? selProv.value : "auto",
        web_search_mode: selWeb ? selWeb.value : "always",
        openai_api_key: kOpenai,
        openai_model: document.getElementById("inputOpenaiModel")?.value,
        openai_base_url: document.getElementById("inputOpenaiBaseUrl")?.value,
        groq_api_key: kGroq,
        groq_model: document.getElementById("inputGroqModel")?.value,
        gemini_api_key: kGemini,
        gemini_model: document.getElementById("inputGeminiModel")?.value,
        ollama_base_url: document.getElementById("inputOllamaUrl")?.value,
        ollama_model: document.getElementById("inputOllamaModel")?.value,
        tavily_api_key: kTavily,
        tavily_search_depth: document.getElementById("selectTavilyDepth")?.value,
      }),
    });
    if (kOpenai) document.getElementById("inputOpenaiKey").value = "";
    if (kGroq) document.getElementById("inputGroqKey").value = "";
    if (kGemini) document.getElementById("inputGeminiKey").value = "";
    if (kTavily) document.getElementById("inputTavilyKey").value = "";
    await loadRagOverview();
  }

  async function submitRagQuestion(questionText, forceWebMode = null) {
    const q = (questionText || "").trim();
    if (!q) return;
    const inputEl = document.getElementById("inputRagQuery");
    const sendBtn = document.getElementById("btnSendRagQuery");
    const webBtn = document.getElementById("btnDirectWebSearch");
    const provSel = document.getElementById("selectRagProvider");
    const webSel = document.getElementById("selectWebSearchMode");
    if (inputEl) inputEl.value = "";
    if (sendBtn) {
      sendBtn.disabled = true;
      sendBtn.textContent = "Buscando...";
    }
    if (webBtn) webBtn.disabled = true;
    try {
      await autoSyncPendingConfigInputs();
      const turn = await apiFetch("/api/v1/rag/ask", {
        method: "POST",
        body: JSON.stringify({
          query: q,
          preferred_provider: provSel ? provSel.value : "auto",
          web_search_mode: forceWebMode || (webSel ? webSel.value : "always"),
        }),
      });
      appendRagChatTurn(turn);
    } catch (err) {
      showToast(`Error en consulta RAG: ${err.message}`, "error");
    } finally {
      if (sendBtn) {
        sendBtn.disabled = false;
        sendBtn.textContent = "Enviar ➤";
      }
      if (webBtn) webBtn.disabled = false;
    }
  }

  function bindRagEvents() {
    const btnSync = document.getElementById("btnSyncRagLlm");
    if (btnSync) {
      btnSync.addEventListener("click", async () => {
        btnSync.disabled = true;
        btnSync.textContent = "🔄 Sincronizando...";
        try {
          await autoSyncPendingConfigInputs();
          const res = await apiFetch("/api/v1/rag/sync", { method: "POST" });
          renderRagOverview(res.overview);
          showToast("Asistente y documentos sincronizados.", "success");
        } catch (err) {
          showToast(err.message, "error");
        } finally {
          btnSync.disabled = false;
          btnSync.textContent = "🔄 Sincronizar";
        }
      });
    }

    const btnToggleCfg = document.getElementById("btnToggleLlmConfig");
    const cfgPanel = document.getElementById("ragLlmConfigPanel");
    if (btnToggleCfg && cfgPanel) {
      btnToggleCfg.addEventListener("click", () => {
        cfgPanel.classList.toggle("hidden");
      });
    }

    const selProv = document.getElementById("selectRagProvider");
    const selWeb = document.getElementById("selectWebSearchMode");
    const syncQuickSelects = async () => {
      try {
        await apiFetch("/api/v1/rag/llm-config", {
          method: "POST",
          body: JSON.stringify({
            preferred_provider: selProv ? selProv.value : "auto",
            web_search_mode: selWeb ? selWeb.value : "always",
          }),
        });
      } catch (_) {}
    };
    if (selWeb) selWeb.addEventListener("change", syncQuickSelects);

    const btnSaveCfg = document.getElementById("btnSaveLlmConfig");
    if (btnSaveCfg) {
      btnSaveCfg.addEventListener("click", async () => {
        try {
          const payload = {
            preferred_provider: selProv ? selProv.value : "auto",
            web_search_mode: selWeb ? selWeb.value : "always",
            openai_api_key: document.getElementById("inputOpenaiKey").value,
            openai_model: document.getElementById("inputOpenaiModel").value,
            openai_base_url: document.getElementById("inputOpenaiBaseUrl").value,
            groq_api_key: document.getElementById("inputGroqKey").value,
            groq_model: document.getElementById("inputGroqModel").value,
            gemini_api_key: document.getElementById("inputGeminiKey").value,
            gemini_model: document.getElementById("inputGeminiModel").value,
            ollama_base_url: document.getElementById("inputOllamaUrl").value,
            ollama_model: document.getElementById("inputOllamaModel").value,
            tavily_api_key: document.getElementById("inputTavilyKey").value,
            tavily_search_depth: document.getElementById("selectTavilyDepth").value,
          };
          await apiFetch("/api/v1/rag/llm-config", {
            method: "POST",
            body: JSON.stringify(payload),
          });
          document.getElementById("inputOpenaiKey").value = "";
          document.getElementById("inputGroqKey").value = "";
          document.getElementById("inputGeminiKey").value = "";
          document.getElementById("inputTavilyKey").value = "";
          const syncRes = await apiFetch("/api/v1/rag/sync", { method: "POST" });
          renderRagOverview(syncRes.overview);
          showToast("Conexiones guardadas y sincronizadas.", "success");
        } catch (err) {
          showToast(err.message, "error");
        }
      });
    }

    const tabUp = document.getElementById("tabAddDocUpload");
    const tabWr = document.getElementById("tabAddDocWrite");
    const panelUp = document.getElementById("panelDocUpload");
    const panelWr = document.getElementById("panelDocWrite");
    if (tabUp && tabWr && panelUp && panelWr) {
      tabUp.addEventListener("click", () => {
        panelUp.classList.remove("hidden");
        panelWr.classList.add("hidden");
        tabUp.className = "px-2.5 py-1 rounded-md font-semibold bg-white text-blue-700 shadow-2xs cursor-pointer";
        tabWr.className = "px-2.5 py-1 rounded-md font-semibold text-slate-600 cursor-pointer";
      });
      tabWr.addEventListener("click", () => {
        panelWr.classList.remove("hidden");
        panelUp.classList.add("hidden");
        tabWr.className = "px-2.5 py-1 rounded-md font-semibold bg-white text-blue-700 shadow-2xs cursor-pointer";
        tabUp.className = "px-2.5 py-1 rounded-md font-semibold text-slate-600 cursor-pointer";
      });
    }

    const fileInput = document.getElementById("inputRagFile");
    const lblFile = document.getElementById("lblSelectedRagFile");
    if (fileInput && lblFile) {
      fileInput.addEventListener("change", () => {
        const f = fileInput.files && fileInput.files[0];
        lblFile.textContent = f ? `Seleccionado: ${f.name}` : "Haz clic aquí para elegir un documento";
      });
    }

    const btnUpload = document.getElementById("btnUploadRagFile");
    if (btnUpload && fileInput) {
      btnUpload.addEventListener("click", () => {
        const file = fileInput.files && fileInput.files[0];
        if (!file) {
          showToast("Elige primero un documento para guardar.", "info");
          return;
        }
        const reader = new FileReader();
        reader.onload = async () => {
          try {
            const dataUrl = String(reader.result || "");
            const base64Part = dataUrl.includes(",") ? dataUrl.split(",", 2)[1] : dataUrl;
            btnUpload.disabled = true;
            btnUpload.textContent = "Guardando documento...";
            const res = await apiFetch("/api/v1/rag/documents/upload", {
              method: "POST",
              body: JSON.stringify({
                filename: file.name,
                content_base64: base64Part,
              }),
            });
            renderRagOverview(res.overview);
            fileInput.value = "";
            if (lblFile) lblFile.textContent = "Haz clic aquí para elegir un documento";
            showToast(`Documento '${file.name}' guardado.`, "success");
          } catch (err) {
            showToast(`No se pudo guardar el documento: ${err.message}`, "error");
          } finally {
            btnUpload.disabled = false;
            btnUpload.textContent = "📤 Guardar Documento";
          }
        };
        reader.readAsDataURL(file);
      });
    }

    const btnSaveMd = document.getElementById("btnSaveRagMarkdown");
    if (btnSaveMd) {
      btnSaveMd.addEventListener("click", async () => {
        const titleEl = document.getElementById("inputRagDocTitle");
        const contentEl = document.getElementById("textareaRagDocContent");
        const title = (titleEl ? titleEl.value : "").trim();
        const content = (contentEl ? contentEl.value : "").trim();
        if (!content) {
          showToast("Escribe el contenido de la nota antes de guardar.", "info");
          return;
        }
        try {
          const res = await apiFetch("/api/v1/rag/documents/text", {
            method: "POST",
            body: JSON.stringify({ title: title || "Nota Operativa", content }),
          });
          renderRagOverview(res.overview);
          if (titleEl) titleEl.value = "";
          if (contentEl) contentEl.value = "";
          showToast("Nota guardada en Mis Documentos.", "success");
        } catch (err) {
          showToast(err.message, "error");
        }
      });
    }

    const formAsk = document.getElementById("formRagAsk");
    if (formAsk) {
      formAsk.addEventListener("submit", (e) => {
        e.preventDefault();
        const inputEl = document.getElementById("inputRagQuery");
        submitRagQuestion(inputEl ? inputEl.value : "");
      });
    }

    const btnDirectWeb = document.getElementById("btnDirectWebSearch");
    if (btnDirectWeb) {
      btnDirectWeb.addEventListener("click", () => {
        const inputEl = document.getElementById("inputRagQuery");
        const q = (inputEl ? inputEl.value : "").trim();
        if (!q) {
          showToast("Escribe un tema en la caja de texto para buscar en internet.", "info");
          if (inputEl) inputEl.focus();
          return;
        }
        submitRagQuestion(q, "always");
      });
    }

    const btnTestWeb = document.getElementById("btnTestWebSearch");
    if (btnTestWeb) {
      btnTestWeb.addEventListener("click", async () => {
        btnTestWeb.textContent = "⏳ Probando...";
        try {
          await autoSyncPendingConfigInputs();
          const res = await apiFetch("/api/v1/rag/web-search", {
            method: "POST",
            body: JSON.stringify({ query: "mantenimiento preventivo fajas transportadoras", save_to_rag: false }),
          });
          const ws = res.web_search || {};
          const count = (ws.results || []).length;
          if (count > 0) {
            showToast(`✓ Búsqueda en internet activa (${count} resultados).`, "success");
          } else {
            showToast("No se obtuvieron resultados en este momento.", "error");
          }
        } catch (err) {
          showToast("No se pudo completar la prueba de búsqueda.", "error");
        } finally {
          btnTestWeb.textContent = "🔍 Probar Búsqueda Web";
        }
      });
    }

    document.querySelectorAll(".rag-quick-q").forEach((chip) => {
      chip.addEventListener("click", () => {
        submitRagQuestion(chip.textContent || "");
      });
    });

    const btnClear = document.getElementById("btnClearRagChat");
    if (btnClear) {
      btnClear.addEventListener("click", async () => {
        try {
          await apiFetch("/api/v1/rag/clear-history", { method: "POST" });
          appState.renderedTurnIds.clear();
          const box = document.getElementById("ragChatMessages");
          if (box) {
            box.innerHTML =
              appState.welcomeChatHtml ||
              `<div class="text-xs text-slate-500 text-center py-6">Conversación limpiada. Realiza una nueva consulta cuando gustes.</div>`;
          }
        } catch (_) {}
      });
    }

    // Cerrar modal visor de documentos
    const modal = document.getElementById("ragDocModal");
    const btnCloseModal = document.getElementById("btnCloseRagModal");
    if (modal && btnCloseModal) {
      btnCloseModal.addEventListener("click", () => {
        modal.classList.add("hidden");
        modal.classList.remove("flex");
      });
      modal.addEventListener("click", (ev) => {
        if (ev.target === modal) {
          modal.classList.add("hidden");
          modal.classList.remove("flex");
        }
      });
    }
  }

  // Inicialización sincronizada con el backend modular
  async function bootstrap() {
    runLogoSpinner5s();
    bindEvents();
    await syncFullState(false);
    connectRealtimeTelemetry();
    requestAnimationFrame(renderConveyorLoop);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bootstrap);
  } else {
    bootstrap();
  }
})();
