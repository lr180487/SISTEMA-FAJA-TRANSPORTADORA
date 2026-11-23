# Arquitectura del backend S_F_T

## Capas y dependencias

```text
backend/
├── core/                 # Configuración, entorno y constantes técnicas
├── domain/               # Modelo del proceso, simulación y reglas PID
├── application/          # Casos de uso y coordinación de servicios
│   └── services/
├── ai/
│   └── multiagent/
│       ├── system.py     # Servicio RAG, routing y proveedores
│       └── markdown.py   # Parser, tokenización y extracción PDF/DOCX
├── api/                  # Contratos HTTP/WebSocket y routers FastAPI
├── infrastructure/       # SQLAlchemy, repositorios y migraciones Alembic
├── realtime/             # Hub y difusión de telemetría
├── main.py               # Composición de la aplicación y lifespan
└── state.py              # Composición/estado de runtime (transición pendiente)
```

## Reglas de dependencia

1. `domain` no importa FastAPI, SQLAlchemy ni proveedores LLM.
2. `api` valida entrada/salida y delega; no contiene reglas de negocio.
3. `application` coordina casos de uso y depende de contratos, no de detalles HTTP.
4. `infrastructure` implementa persistencia y adaptadores externos.
5. `ai/multiagent` consume documentos, estado SCADA y proveedores; no debe ejecutar maniobras industriales.
6. `main.py` compone dependencias y ciclo de vida.
7. Los módulos históricos (`backend.database`, `backend.simulation`, `backend.rag_multiagent`, etc.) se conservan como adaptadores para evitar romper imports.

## Estado de la reorganización

La implementación multiagente se trasladó a `backend.ai.multiagent.system`.
La simulación, persistencia, routers y hub ya se encuentran en paquetes separados.
`backend/state.py` todavía actúa como contenedor global; migrarlo a inyección de dependencias debe ser una fase separada con pruebas de regresión.


## Límite actual del Multiagent

El router selecciona hasta tres perfiles especialistas y el orquestador. Sus
instrucciones se ensamblan en un único prompt LLM. La ejecución autónoma,
paralela y con estado/checkpoints por agente queda fuera del alcance actual.
