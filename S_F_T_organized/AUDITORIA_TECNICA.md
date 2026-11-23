# Informe de auditoría técnica — S_F_T

## 1. Alcance
Inspección estática del ZIP original: inventario de 38 archivos (18 módulos Python), revisión de
puntos de entrada, configuración, routers, estado global, persistencia SQLite, RAG y frontend.
No se ejecutaron pruebas de aceptación con PLC físico ni pruebas de penetración.

## 2. Resumen ejecutivo
El proyecto contiene un backend FastAPI funcionalmente organizado por routers, simulación de
faja transportadora, controlador PID, persistencia PostgreSQL/SQLite, WebSocket y asistente RAG.
La principal deuda técnica es la concentración de responsabilidades en módulos grandes y el
acoplamiento al objeto global `app_state`.

## 3. Hallazgos priorizados

### P0 — Seguridad antes de despliegue
- No se observó middleware ni dependencia de autenticación en los routers revisados.
- El endpoint WebSocket `/ws/telemetry` acepta comandos `command` y `pid` sin autenticar.
- CORS está configurado con `allow_origins=["*"]`. Aunque `allow_credentials=False`,
  debe restringirse a los orígenes reales de la HMI.
- El ZIP original incluía `.env`; el artefacto reorganizado lo excluye y conserva `.env.example`.
- La plantilla de entorno debe usar secretos propios y no contraseñas por defecto.

### P1 — Fiabilidad y seguridad operacional
- `_simulation_loop()` en `backend/main.py` absorbe excepciones generales con `pass`;
  esto oculta fallos de simulación y persistencia.
- La cola de eventos en `backend/state.py` tiene capacidad finita y descarta eventos cuando
  está llena; se requiere contador, alarma y política de backpressure/DLQ.
- Los comandos HTTP y WebSocket llaman directamente al simulador. Conviene centralizar
  validación, autorización, interlocks y auditoría en un servicio de aplicación.
- Debe definirse una estrategia de parada segura y límites operacionales antes de conectar PLC real.

### P1 — Arquitectura y mantenibilidad
- `backend/rag_multiagent.py`, `backend/database.py` y `backend/simulation.py` concentran
  múltiples responsabilidades.
- `backend/state.py` crea servicios globales al importar el módulo.
- Los routers dependen directamente de `app_state`.
- `frontend/app.js` tiene aproximadamente 90 KB y unas 350 declaraciones detectadas
  por búsqueda estática; requiere separación gradual por módulos.

### P2 — Calidad y pruebas
- No se identificó una carpeta de tests en el ZIP.
- Se recomienda agregar pruebas unitarias del PID/simulador, pruebas de repositorios,
  contratos API, WebSocket, RAG y pruebas de integración con SQLite temporal.
- Añadir lint, type checking, cobertura y CI.
- No se debe declarar validada la integración con PLC sin evidencia reproducible de protocolo,
  direcciones, estados, watchdog e interlocks.

## 4. Base de datos
La SQLite contiene seis tablas: `scada_runtime_state`, `scada_telemetry_log`,
`scada_events_log`, `rag_documents_store`, `rag_chat_history` y `app_kv_settings`.
En la copia de trabajo se consolidó el WAL en el archivo principal antes de retirar
los archivos auxiliares `-wal` y `-shm`.

## 5. Nueva organización

```text
S_F_T/
├── backend/
│   ├── core/
│   ├── domain/
│   ├── infrastructure/
│   ├── ai/
│   ├── realtime/
│   ├── api/
│   │   └── routers/
│   ├── routers/          # adaptadores de compatibilidad
│   ├── main.py
│   └── state.py
├── frontend/
├── agents/
├── knowledge_base/
├── data/
├── tests/                # siguiente fase
├── .env.example
├── .gitignore
├── requirements.txt
├── start.py
└── README.md
```

## 6. Cambios realizados en el paquete reorganizado
- Movidos los módulos de configuración, simulación, base de datos, RAG y WebSocket a paquetes
  `core`, `domain`, `infrastructure`, `ai` y `realtime`.
- Movidos los routers y esquemas a `backend/api/`.
- Conservados adaptadores en las rutas antiguas para compatibilidad de imports.
- Excluido `.env` del paquete final y creado `.gitignore`.
- Actualizado `.env.example` con placeholders y configuración local segura por defecto.
- Consolidada la base SQLite para que los datos del WAL no se pierdan al excluir archivos auxiliares.
- No se alteraron deliberadamente algoritmos PID, ecuaciones de simulación ni contratos de API.

## 7. Validación y limitaciones
La validación estática de sintaxis Python debe ejecutarse sobre el paquete reorganizado.
La ejecución real depende de instalar `requirements.txt` y de configurar el entorno.
No se afirma que el backend haya superado pruebas de integración, carga, seguridad o PLC físico.

## 8. Plan recomendado
1. P0: autenticación, RBAC, CORS, autorización WebSocket y protección de comandos.
2. P1: extraer `SimulationService`, `PidService`, `RagService` y repositorios.
3. P1: logging estructurado, health checks de dependencias, política de errores y cola durable.
4. P2: pruebas automatizadas y CI.
5. P2: modularizar frontend por vistas, API client, WebSocket client y componentes.
6. P3: pruebas hardware-in-the-loop y aprobación técnica con evidencia.


## Actualización: ORM SQLAlchemy y Alembic

Se incorporó una capa ORM y gestión de esquema versionada:

- `backend/infrastructure/models.py`: modelos declarativos centralizados (`Base`) y las seis entidades/tablas existentes.
- `backend/infrastructure/database.py`: `DatabaseManager`, sesiones y operaciones de persistencia; ahora aplica las migraciones pendientes en el motor que haya quedado activo.
- `backend/infrastructure/migrations/`: entorno Alembic y revisiones.
- `backend/infrastructure/migrations/versions/0001_initial_schema.py`: revisión inicial idempotente que adopta el metadata actual y conserva nombres de tablas/columnas.
- `backend/infrastructure/migrations_runner.py`: ejecuta `alembic upgrade head` sobre el `Engine` activo.
- `alembic.ini`: configuración de Alembic.

Se añadieron `alembic>=1.13.0` a `pyproject.toml` y `requirements.txt`.

### Validaciones ejecutadas

- Parseo sintáctico de los archivos Python: correcto.
- Lectura de `pyproject.toml`: correcta.
- Migración inicial sobre una base SQLite temporal: correcta.
- Verificación de las siete tablas resultantes (seis tablas de aplicación y `alembic_version`): correcta.
- Segunda ejecución de `upgrade head`: idempotente.

No se ejecutó una migración contra PostgreSQL de producción ni se modificó la base de datos real incluida en `data/`. Antes de desplegar, realizar backup y revisar el destino de conexión.


## Reorganización modular v2 y expansión Multiagent

### Backend
- La implementación de `MultiAgentRAGSystem` se movió a `backend/ai/multiagent/system.py`.
- `backend/state.py` ahora importa los módulos canónicos de `core`, `domain`, `infrastructure`, `realtime` y `ai.multiagent`.
- `backend/main.py` registra los routers desde `backend.api.routers`.
- Los módulos históricos se mantienen como adaptadores para compatibilidad.
- Se agregó `backend/ARCHITECTURE.md` con reglas de dependencia y responsabilidades.
- Se creó el paquete `backend/application/services/` como destino para extraer casos de uso en una fase posterior; aún no se movió lógica a servicios sin pruebas de regresión.

### Multiagent Markdown
Se agregaron especialistas: diagnóstico SCADA, seguridad industrial, mantenimiento electromecánico,
calidad y producción, instrumentación, energía, integración PLC e informes/trazabilidad.

Se añadieron políticas compartidas en `agents/policies/` para principios globales, seguridad,
fidelidad RAG, búsqueda web, prompt injection, formato, enrutamiento, evaluación y mantenimiento.

El runtime ahora carga `agents/*.md` como especialistas y `agents/policies/*.md` como directrices
globales, inyectando estas últimas en el prompt del sistema. Las políticas no se contabilizan
ni se enrutan como especialistas. El endpoint de overview expone los nombres de las políticas.


### Precisión sobre el nivel multiagente

Los especialistas Markdown se seleccionan por keywords y evidencia y sus
instrucciones se consolidan en un prompt para una única ejecución de la cadena
LLM. La entrega no afirma que existan agentes autónomos paralelos ni
comunicación independiente entre agentes. Esa evolución requeriría separar
ejecución, estado, herramientas, checkpoints y evaluación por agente.
