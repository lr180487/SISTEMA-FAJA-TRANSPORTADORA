# Manual de Operación · SCADA PID

## Descripción General del Sistema
**SCADA PID** es el panel de control y supervisión de la faja transportadora con regulación automática de velocidad y clasificación de cajas. Permite operar la banda en tiempo real, supervisar el paso de unidades y ajustar el comportamiento de velocidad.

## Controles Principales de Operación
- **Iniciar**: pone en movimiento la faja transportadora hacia la dirección seleccionada (*Avance* o *Reversa*).
- **Pausar**: detiene temporalmente la banda conservando las cajas en su posición actual para reanudar cuando se indique.
- **Detener**: realiza una parada normal controlada de la faja.
- **E-STOP (Parada de Emergencia)**: corta de inmediato el movimiento ante cualquier riesgo. Para volver a operar se debe pulsar primero **Restablecer** y luego **Iniciar**.
- **Actualizar**: ejecuta el indicador de actualización alrededor del logo durante 5 segundos y sincroniza los datos actuales del panel.

## Estaciones de la Faja Transportadora
1. **Entrada**: detecta cada caja apenas ingresa desde la tolva de alimentación.
2. **Báscula**: mide en kilogramos el peso de cada caja mientras avanza sobre la banda.
3. **Control de Calidad**: identifica unidades defectuosas y activa el separador automático hacia el contenedor de rechazo cuando la opción *Separar defectuosas* está activa.
4. **Salida / Despacho**: contabiliza las unidades conformes entregadas al final del recorrido de 10 metros.

## Tipos de Cajas en Simulación
- **Ligera**: peso reducido (aprox. 2 a 5 kg), color azul.
- **Estándar**: peso medio de trabajo normal (aprox. 6 a 12 kg), color verde.
- **Pesada**: carga exigente para el motor y el control de velocidad (aprox. 15 a 25 kg), color ámbar.
- **Defectuosa**: unidad marcada para prueba de separación en la estación de calidad, color rojo.
