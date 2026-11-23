# Servicios de aplicación

Este paquete es el destino de la extracción gradual de casos de uso desde
`backend/state.py` y los routers. No se duplican servicios ni se crean
implementaciones ficticias en esta reorganización.

Servicios candidatos:
- `scada_service.py`: comandos y consultas de la faja.
- `pid_service.py`: configuración y diagnóstico PID.
- `rag_service.py`: consultas, sincronización documental y proveedores.
- `telemetry_service.py`: histórico, eventos y difusión.
