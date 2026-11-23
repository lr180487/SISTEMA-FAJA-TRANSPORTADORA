# Monitor Node-RED para S_F_T

## 1. Configurar FastAPI

En `.env`, define un secreto largo (mínimo 32 caracteres recomendado):

```env
NODE_RED_MONITOR_TOKEN=CAMBIA_POR_UN_SECRETO_LARGO
NODE_RED_STALE_AFTER_S=30
```

Reinicia FastAPI. El endpoint de recepción queda en `POST /api/v1/node-red/events`; el monitor de navegador usa `WS /api/v1/node-red/ws`.

## 2. Configurar Node-RED

Importa `flows-monitor-example.json` desde menú → Import → select a file. Define estas variables en el entorno del proceso Node-RED y reinícialo:

```env
SFT_MONITOR_URL=http://127.0.0.1:8000/api/v1/node-red/events
SFT_MONITOR_TOKEN=EL_MISMO_SECRETO_CONFIGURADO_EN_FASTAPI
```

Si Node-RED corre en Docker y FastAPI corre en Windows host, usa `http://host.docker.internal:8000/api/v1/node-red/events`. Si ambos están en Docker, usa el nombre DNS del servicio FastAPI dentro de la misma red Docker. No uses `localhost` para alcanzar otro contenedor.

El flujo de ejemplo envía heartbeat cada 10 segundos, cambios de estado reportados por el nodo `status` (scope all) y errores capturados por `catch` (scope all). El nodo `status` solo informa estados que los nodos emiten; no es un trace completo de cada mensaje que atraviesa cada nodo. Para registrar pasos de negocio, añade Function/Change nodes que emitan eventos explícitos al mismo endpoint.

## 3. Verificación

1. Inicia FastAPI y Node-RED.
2. Abre la HMI y selecciona **Node-RED**.
3. El estado debe pasar a `ONLINE` tras el primer heartbeat y permanecer online mientras la separación entre eventos sea menor al umbral.
4. Provoca un error de prueba en un nodo o cambia el estado de un nodo; debe aparecer en el registro.
5. Comprueba `GET /api/v1/node-red/status` y `GET /api/v1/node-red/events`.

## Seguridad y límites

- El endpoint de ingesta exige `X-Node-RED-Token`; si el token no está configurado, responde 503.
- El historial es en memoria y conserva los últimos 200 eventos; se reinicia al reiniciar FastAPI.
- El WebSocket de monitor es independiente de `/ws/telemetry` y no envía comandos a PLC/SCADA.
- No se expone el editor ni la Admin API de Node-RED.


## 4. Integración real con TIA Portal / S7-1200 mediante OPC UA (solo lectura)

El flujo de gateway original consultaba `GET /api/v1/status`; eso es un snapshot de FastAPI/simulador, no una lectura física del DB100. Se agregó una pestaña separada `10 · TIA PORTAL S7-1200 · OPC UA`.

### Requisitos Node-RED

En el directorio de usuario de Node-RED: `npm install node-red-contrib-opcua`. Reinicia Node-RED e importa `NodeRED_TIA_PORTAL_S7_1200_OPCUA_READONLY.json` (o usa el flujo completo actualizado).

### TIA Portal V17 / CPU S7-1200

1. Verifica que el modelo y firmware de la CPU soporten OPC UA Server.
2. En propiedades de dispositivo de la CPU, habilita OPC UA Server.
3. En `OPC UA communication > Server interfaces`, crea una interfaz de servidor y agrega explícitamente las variables que Node-RED podrá leer, incluidas las variables requeridas de DB100.
4. Configura roles/usuarios y certificados; descarga la configuración al PLC.
5. Obtén el endpoint OPC UA real desde la configuración/diagnóstico de la CPU y sustituye el endpoint de ejemplo `opc.tcp://192.168.0.10:4840` en el nodo de configuración.
6. Obtén el NodeId real de una variable de DB100 desde la interfaz OPC UA/Browser. Configura `SFT_DB100_NODEID` en el entorno del proceso Node-RED. No se inventan namespace, nombres ni tipos.
7. En Node-RED ejecuta `Explorar espacio OPC UA`, luego `Leer variable DB100` y finalmente `Suscribir variable DB100`. Los resultados aparecen en Debug. `Cancelar suscripción` detiene el monitoreo.

Variables de entorno de ejemplo (definir en el entorno de Node-RED, no en el `.env` de FastAPI si ambos procesos están separados):

```env
SFT_DB100_NODEID=ns=REEMPLAZAR;s=REEMPLAZAR_CON_NODEID_REAL
FASTAPI_BASE_URL=http://127.0.0.1:8000
SFT_MONITOR_TOKEN=EL_MISMO_TOKEN_DE_FASTAPI
```

El endpoint se edita en el nodo `S7-1200 · OPC UA (CAMBIAR IP/SEGURIDAD)`. Si el servidor exige autenticación o `SignAndEncrypt`, configura la política, modo, usuario y certificados en ese nodo; no rebajes la seguridad del PLC para hacer funcionar la conexión.

**Límite deliberado:** esta integración no incluye escritura OPC UA, arranque/parada, consignas PID ni control de salidas. Esas operaciones requieren mapa de variables aprobado, interlocks PLC, autorización y pruebas con PLCSIM/PLC en condiciones seguras.
