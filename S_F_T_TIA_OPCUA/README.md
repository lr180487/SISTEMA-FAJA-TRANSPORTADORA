# SCADA PID · Simulación de Faja Transportadora y Control PID

Sistema web en **Modo Claro Profesional** con motor físico en tiempo real en **Python (FastAPI)**, persistencia relacional **PostgreSQL con fallback automático a SQLite**, configuración mediante **`.env`**, **Controlador PID con controles individuales (P · I · D)**, **Ayuda HTML integrada** y **Asistente IA con consulta de documentos y búsqueda en internet**.

## Variables de Entorno (`.env`)

El backend carga automáticamente `/home/user/.env` (ver plantilla `.env.example`):
- **Servidor**: `APP_NAME`, `APP_VERSION`, `HOST`, `PORT`
- **Base de Datos (`PostgreSQL -> SQLite Fallback`)**:
  - `DB_PREFERRED_ENGINE=postgres`
  - `DB_AUTO_FALLBACK_SQLITE=true`
  - `DATABASE_URL` o `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_SSLMODE`, `POSTGRES_CONNECT_TIMEOUT`
  - `SQLITE_DB_PATH=/home/user/data/scada_pid.db`
- **Asistente y Búsqueda Web**: `OPENAI_API_KEY`, `GROQ_API_KEY`, `GEMINI_API_KEY`, `OLLAMA_BASE_URL`, `TAVILY_API_KEY`, `WEB_SEARCH_MODE`

## Arquitectura Modular del Backend (`/backend`)

- `backend/config.py`: Carga de `.env` (`python-dotenv` + parser nativo de respaldo) y `AppSettings`.
- `backend/database.py`: `DatabaseManager` con **SQLAlchemy 2.0** intentando conectar a **PostgreSQL** (`psycopg`) y conmutando automáticamente a **SQLite (`WAL`)** si PostgreSQL no está disponible al arrancar o durante la operación. Persiste estado operativo/PID (`scada_runtime_state`), telemetría histórica (`scada_telemetry_log`), eventos (`scada_events_log`), documentos (`rag_documents_store`), historial de chat (`rag_chat_history`) y configuración (`app_kv_settings`).
- `backend/schemas.py`: Esquemas de validación Pydantic v2.
- `backend/ws_hub.py`: Concentrador WebSocket bidireccional (`RealtimeHub`).
- `backend/state.py`: Contenedor `ApplicationState` con secuencia monotónica `seq` y persistencia asíncrona.
- `backend/routers/`:
  - `system.py`: `/api/v1/health`, `/api/v1/bootstrap`, `/api/v1/sync`
  - `database.py`: `/api/v1/db/status`, `/api/v1/db/reconnect`, `/api/v1/db/telemetry`, `/api/v1/db/events`
  - `scada.py`: `/api/v1/status`, `/api/v1/sensors`, `/api/v1/history`, `/api/v1/export/csv`, `/api/v1/control`
  - `pid.py`: `/api/v1/pid`, `/api/v1/pid/presets`
  - `rag.py`: `/api/v1/rag/*`
  - `ws.py` y `pages.py`

## Ejecución

```bash
python3 start.py
```


## Arquitectura reorganizada

La implementación se agrupó por responsabilidad manteniendo rutas de compatibilidad para
no romper imports existentes:

```text
backend/
├── core/                 # Configuración y carga de entorno
├── domain/               # Simulación y reglas del proceso industrial
├── infrastructure/       # Persistencia SQLAlchemy / SQLite / PostgreSQL
├── ai/                   # RAG multiagente y proveedores
├── realtime/             # Hub WebSocket
├── api/
│   ├── schemas.py        # Contratos Pydantic
│   └── routers/          # Endpoints HTTP y WebSocket
├── routers/              # Adaptadores de compatibilidad
├── main.py               # Composición FastAPI y ciclo de vida
└── state.py               # Contenedor de servicios (pendiente de inyección)
```

Los directorios `frontend/`, `agents/`, `knowledge_base/` y `data/` se mantienen como
recursos de aplicación. El archivo `.env` real no se distribuye; cree uno local copiando
`.env.example` y configure credenciales seguras.

## Inicio

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python start.py
```

En Windows PowerShell, use `Copy-Item .env.example .env` en lugar de `cp`.

## Alcance de esta reorganización

Esta entrega reorganiza físicamente módulos y conserva imports antiguos mediante adaptadores.
No representa una certificación de seguridad, una validación de hardware/PLC real ni una
prueba de aceptación industrial. Antes de exponer el sistema a una red, implemente autenticación,
autorización por rol, validación de comandos y controles de acceso para HTTP y WebSocket.\n\n## Instalación con `pyproject.toml`\n\nInstalación del proyecto y sus dependencias:\n\n```bash\npython -m pip install .\n```\n\nInstalación para desarrollo (incluye pytest y Ruff):\n\n```bash\npython -m pip install -e ".[dev]"\n```\n\nTambién se conserva `requirements.txt` para instalaciones tradicionales.\n

## ORM SQLAlchemy y migraciones Alembic

Los modelos declarativos se encuentran en `backend/infrastructure/models.py`.
El acceso y persistencia del sistema SCADA se mantiene en
`backend/infrastructure/database.py`, que utiliza SQLAlchemy 2.x y sesiones
transaccionales. Los nombres de las tablas existentes se conservan.

Las migraciones se encuentran en `backend/infrastructure/migrations/` y el
archivo de configuración es `alembic.ini`. El gestor de base de datos aplica
automáticamente las revisiones pendientes al seleccionar PostgreSQL o SQLite,
incluido el fallback. La revisión inicial adopta tablas existentes sin
recrearlas y registra `alembic_version`.

Comandos manuales (desde la raíz del proyecto):

```bash
# Ver la revisión aplicada
alembic current

# Ver el historial
alembic history

# Aplicar migraciones pendientes
alembic upgrade head

# Crear una nueva migración después de modificar modelos ORM
alembic revision --autogenerate -m "describe el cambio"

# Volver una revisión atrás (solo tras backup y revisión)
alembic downgrade -1
```

Antes de ejecutar migraciones en producción, realizar una copia de seguridad.
Para bases nuevas, configure `.env` y ejecute `alembic upgrade head`; en el
arranque normal, `DatabaseManager` también aplica las revisiones pendientes.


## Reorganización modular v2

La implementación canónica se organiza por responsabilidades:

```text
backend/
├── core/                       # Configuración
├── domain/                     # Simulación y reglas industriales
├── application/services/       # Destino de casos de uso (extracción gradual)
├── ai/multiagent/
│   ├── __init__.py
│   └── system.py               # Implementación MultiAgentRAGSystem
├── api/
│   ├── schemas.py
│   └── routers/
├── infrastructure/
│   ├── models.py               # ORM SQLAlchemy
│   ├── database.py             # Persistencia y failover
│   └── migrations/             # Alembic
├── realtime/                   # Hub WebSocket
├── main.py
└── state.py                    # Contenedor de runtime heredado
```

Los imports antiguos (`backend.rag_multiagent`, `backend.ai.rag_multiagent`,
`backend.database`, `backend.simulation`, `backend.ws_hub`, `backend.schemas`,
`backend.config` y `backend.routers`) se mantienen como adaptadores de compatibilidad.
El código interno utiliza las rutas canónicas nuevas.

## Multiagent: agentes y políticas Markdown

- `agents/*.md`: definiciones de agentes especialistas con frontmatter simple.
- `agents/policies/*.md`: políticas globales inyectadas en cada prompt; no se enrutan como agentes.
- `knowledge_base/*.md`: documentos técnicos que se fragmentan e indexan para RAG.

El orquestador selecciona hasta tres especialistas además del agente coordinador.
El conjunto de políticas globales incluye seguridad, fidelidad documental, uso web,
resistencia a prompt injection, formato de respuesta, enrutamiento y evaluación.
La sincronización `/api/v1/rag/sync` recarga agentes, políticas y documentos.

Consulte `backend/ARCHITECTURE.md`, `agents/README.md` y `agents/policies/README.md`.


### Alcance real de la orquestación

La implementación actual realiza enrutamiento por keywords y evidencia para
seleccionar perfiles especialistas Markdown, y consolida sus instrucciones
en un único contexto de consulta enviado a la cadena de proveedores LLM.
Esto es una orquestación basada en roles/prompts; no representa todavía agentes
autónomos ejecutándose en paralelo con memoria, herramientas y ciclos de
validación independientes.


## Monitor Node-RED en tiempo real

La HMI incorpora la vista **Node-RED**. Node-RED envía heartbeat (10 s), cambios de estado y errores a `POST /api/v1/node-red/events`; FastAPI autentica la ingesta con `X-Node-RED-Token` y distribuye los eventos a los navegadores por `WS /api/v1/node-red/ws`.

Configura `NODE_RED_MONITOR_TOKEN` y `NODE_RED_STALE_AFTER_S` en `.env`, usa el mismo secreto en el entorno de Node-RED (`SFT_MONITOR_TOKEN`) y define `SFT_MONITOR_URL`. Importa `node-red/flows-monitor-example.json` o usa el flujo completo incluido. Consulta `node-red/README.md` para Docker/Windows y pruebas.

El monitor registra actividad instrumentada (heartbeat, eventos de estado emitidos por nodos y errores capturados); no representa un trace automático de cada mensaje que atraviesa cada nodo. El historial reside en memoria (últimos 200 eventos) y se reinicia al reiniciar FastAPI. No controla el PLC ni sustituye la validación de comunicación industrial.
