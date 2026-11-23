# Guía Práctica de Ajuste del Control PID

## ¿Para qué sirve el Control PID en la Faja?
El controlador **PID** mantiene la velocidad real de la faja igual a la **Velocidad Meta** (en `m/s`), ajustando automáticamente la potencia entregada al motor incluso cuando entran cajas muy pesadas o cambia la carga sobre la banda.

## Controles Individuales (P · I · D)
Cada componente puede encenderse, apagarse o regularse de manera independiente en la pantalla principal:

### 1. Control Proporcional (P)
- Actúa de inmediato según qué tan lejos esté la velocidad actual de la velocidad meta.
- **Cuándo subirlo**: si la faja tarda demasiado en alcanzar la velocidad deseada.
- **Cuándo bajarlo**: si notas que la velocidad sube y baja repetidamente (oscilaciones).

### 2. Control Integral (I)
- Corrige pequeñas diferencias acumuladas con el paso de los segundos para clavar la velocidad exacta.
- **Cuándo usarlo**: indispensable cuando la faja lleva carga pesada y con solo `P` se queda un poco por debajo de la meta.
- **Botón Reiniciar I**: limpia la memoria acumulada del control integral si hubo un cambio brusco o una parada larga.

### 3. Control Derivativo (D)
- Actúa como un amortiguador suave que frena cambios bruscos antes de que la velocidad se pase de largo.
- Incluye un control de **Suavizado** para evitar tirones innecesarios en el motor.

## Modos Recomendados Disponibles
- **Equilibrado (Recomendado)**: balance ideal entre rapidez y suavidad para trabajo continuo (`P=36`, `I=26`, `D=4.2`).
- **Rápido**: respuesta enérgica para cambios frecuentes de carga pesada.
- **Suave (Sin picos)**: prioriza arranques progresivos sin sobrepasar nunca la velocidad meta.
- **Solo Proporcional (P)**: útil para demostraciones básicas sin corrección acumulada.
- **Proporcional + Integral (PI)**: regulación clásica estable sin acción derivativa.
