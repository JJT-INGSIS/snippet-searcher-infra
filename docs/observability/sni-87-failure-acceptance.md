# SNI-87 — Ensayos de fallas y evidencia de recuperación

Actualización al 18/11/2026. **ACEPTACIÓN DE ALERTAS PENDIENTE**: SNI-83 ya verificó
en DEV la pausa/reanudación y sus señales; esa prueba no acredita el aviso de SNI-87.
El [registro de entrada](../evidence/sni87-readiness-2026-11-18.json) distingue esa
entrega de las condiciones y notificaciones todavía pendientes de SNI-85/86.
Esta guía conserva el alcance del ticket; no elige umbrales, SLO ni canal móvil.

La revisión de New Relic de hoy encontró sólo tres condiciones: disponibilidad de
API, disponibilidad de UI y certificado. No había una condición de atraso del
consumidor ni del listado 200 sin fixture. SNI-85 y SNI-86 siguen Todo en Linear;
DEV se observó detenido/desasignado. No se encendió ni se provocó un corte para
repetir la prueba técnica sin su detector. Esto no es un ensayo de caída de VM.

## Condiciones de entrada

1. Registrar autorización/ventana DEV, operador y persona que recibe el aviso.
   Acordar con SNI-86 el tiempo máximo de detección y entrega, y cómo tratar
   mantenimiento. No excluir el ensayo de la condición que se quiere demostrar.
2. Relevar release efectiva, digests, tareas, redes y proveedor activo. Los archivos
   bootstrap del repo no certifican lo que corre hoy. Diferenciar storage local,
   Asset y su backend, así como workers habilitados de un Redis sólo instalado.
3. Tener acceso a New Relic, consultas/condiciones desplegadas, destino móvil probado
   y forma de recuperar la VM fuera de SSH. La credencial de ingesta no permite
   administrar políticas; no intercambiarlas.
4. Elegir fixtures exclusivos del ensayo y guardar IDs/estado inicial. No incluir
   snippets reales, JWT, claves ni contenido de usuarios en la evidencia.
5. Registrar un control sano por el mismo recorrido. Preparar y revisar la acción
   inversa del corte antes de provocarlo; abortar si no se conoce cómo restaurar.
6. Ensayar una falla por vez. Los cortes de VM, red, storage o disco requieren la
   ventana y alcance explícitos; no forman parte de ejecutar pruebas unitarias.

## Evidencia común

La [plantilla](sni-87-evidence-template.json) contiene campos vacíos y escenarios
NOT_EXECUTED. Copiarla a un registro fechado, completar fuente/ambiente/versiones y
cambiar estado sólo después de ejecutar y revisar el caso. No sustituir un caso
omitido por PASS ni cerrar el ticket con sólo alertas creadas.

Registrar tiempos UTC ISO-8601: inicio del corte, primera señal, apertura del
incidente, recepción en el dispositivo, inicio/fin de restauración y recuperación
funcional. Conservar zona horaria de visualización y sincronización de relojes.
Distinguir demora de muestreo, evaluación de alerta y entrega del canal; no atribuir
todo el intervalo al componente que falló. Si no hubo aviso, registrar el tiempo
límite vencido, la brecha, el cambio y el reensayo; no inventar una hora de detección.

Adjuntar ID/enlace de incidente, consulta y rango temporal, capturas del aviso y de
la recuperación, operación de corte exacta y la inversa ejecutada. Para el alta,
conservar Trace ID y request ID disponibles, sin confundirlos. Para jobs, conservar
job/event/item IDs presentes en el contrato y la consulta de correlación. El 200 de
un healthcheck no reemplaza la verificación funcional tras restaurar.

## Tres casos principales

| Caso | Control y falla | Evidencia mínima para PASS |
| --- | --- | --- |
| PrintScript inaccesible durante un alta | Alta sintácticamente válida de fixture; después interrumpir sólo el camino Snippets → PrintScript y repetir otra intención identificada | Error técnico del alta, sin éxito ficticio; trace/request ID; dependencia fallida identificada en New Relic; incidente/aviso en ventana; restauración y alta nueva confirmada |
| Listado HTTP 200 sin fixture conocido | Verificar primero que la identidad de prueba tenga acceso y que filtros/página deban incluir su ID; producir la ausencia en un entorno controlado con la misma condición funcional | El check falla por contenido, no por status HTTP; incidente/aviso; restauración del conjunto esperado y cierre/recuperación del monitor. No borrar datos reales ni presentar un filtro legítimo como falla |
| Consumidor detenido con Redis/publicador operativos | Worker activo y fixture de trabajo pendiente; detener sólo el consumidor sin detener Redis ni el publicador | Publicación confirmada, consumidor sin avance y atraso observable; correlación job/event; incidente/aviso en ventana; recuperación de avance/ACK sin duplicación lógica |

No decidir aquí cómo inyectar el 200 incorrecto: usar el mecanismo controlado que
entregue SNI-85, manteniendo monitor/condición equivalentes a DEV. Si no existe,
registrar la preparación faltante. Para separar consumidor y publicador usar el
mecanismo de SNI-83 documentado abajo: ambos comparten Snippets y detener todo el
servicio también eliminaría el muestreador. La pausa lógica conserva publicador,
Redis y señales, aunque el cambio de flags reinicie Snippets y PrintScript.

En el alta fallida, una respuesta incierta de red no autoriza repetir una mutación
con una clave nueva: seguir el contrato de idempotencia existente. El alta sana de
recuperación es una intención nueva identificada; no reemplaza la conciliación de
una operación cuyo resultado sea incierto.

## Consumidor detenido: procedimiento entregado por SNI-83

La [verificación DEV de SNI-83](sni-83-background-signals.md#dev-18112026-utc)
documenta el corte del 18/11 entre 01:54 y 02:44 UTC: con el consumidor apagado,
`lag = 1`, el outbox permaneció en 0 y la edad elegible creció cada minuto. Al
reanudar, el trabajo terminó y lag, PEL, outbox y edad elegible volvieron a 0.
Se reutiliza como evidencia de la señal; **no es evidencia de incidente ni aviso**.

Usar CD **v0.6.8**, cuyo `INFRA_REVISION` es
`cbd30f98224f82919fc5b12211aed49c36aef308`. `v0.6.7` no sirve para estos cortes:
su revisión exigía callers v0.6.6 y el gate fallaba antes de aplicar. Conservar los
tags inmutables; no resolverlo omitiendo la comprobación ni reaplicando un stack.

El operador debe confirmar primero que `background.publisher` y
`background.consumer` están en `true`, no hay operación pendiente, los cuatro
callers usan v0.6.8 y no hay despliegues activos. Registrar el release sano y la
condición/canal de SNI-86 antes de preparar el corte. No ejecutar estos comandos
contra el manifiesto de bootstrap ni mientras falten esas condiciones.

Como `azureuser`, con directorio de ensayo nuevo y privado ya preparado:

```sh
sni87_bundle=/home/azureuser/.local/share/snippet-searcher/cd/cbd30f98224f82919fc5b12211aed49c36aef308
sni87_release=/home/azureuser/.local/state/snippet-searcher/dev/release.json
sni87_run=/home/azureuser/sni87-ENSAYO-UNICO

cp "$sni87_release" "$sni87_run/before.json"
python3 -B "$sni87_bundle/scripts/bootstrap_swarm.py" plan \
  "$sni87_release" --consumer off > "$sni87_run/consumer-off.json"
sudo -n python3 -B "$sni87_bundle/scripts/bootstrap_swarm.py" deploy \
  "$sni87_run/consumer-off.json" --infrastructure --background-only
```

El alcance sólo admite cambiar `background` y despliega Snippets/PrintScript;
conserva imágenes, Auth0, APM, UI, bases y Redis. Revisar el candidato antes de
aplicarlo. Después de confirmar la pausa, producir un cambio de reglas exclusivo
con la identidad autenticada de prueba y conservar sus request/event/job IDs.

Para restaurar el estado inicial activo, usar el release **confirmado vigente**:

```sh
python3 -B "$sni87_bundle/scripts/bootstrap_swarm.py" plan \
  "$sni87_release" --consumer on > "$sni87_run/consumer-on.json"
sudo -n python3 -B "$sni87_bundle/scripts/bootstrap_swarm.py" deploy \
  "$sni87_run/consumer-on.json" --infrastructure --background-only
```

Confirmar finalización del job, recuperación de la UI, ACK/PEL y lag/outbox sin
atraso, además de cierre del incidente. El reinicio deja aproximadamente un minuto
sin muestra: no tratarlo como prueba de ausencia sostenida ni usar `consumers`
como contador de workers vivos, porque Redis conserva nombres de reinicios.

### Cuota necesaria para pausar y restaurar

Cada corte manual hace unas 30 consultas anónimas a GitHub desde la IP de la VM,
con cupo de 60 por hora. **Como máximo dos cortes por hora**, sumando pausa,
restauración y operaciones de otros integrantes. La cantidad real puede variar;
no suponer que dos cortes siempre entran ni gastar el cupo en reintentos.

Antes de pausar, revisar el cupo/reset y reservar la restauración. Si no alcanza,
posponer o acordar una pausa cerca del reset y una reanudación después. En SNI-83
la espera prolongó la pausa unos 45 minutos: no prometer recuperación inmediata
sin cupo disponible. Un 403 del gate requiere revisar journal/estado y esperar la
renovación; no pasar una credencial a la VM ni saltarse la validación.

La consulta de seguimiento está en SNI-83: `stream.lag` y edad de jobs `PENDING`
crecientes con outbox=0 distinguen el consumidor detenido de publicación atrasada.
PEL con idle creciente es otro caso. El umbral de cinco muestras es una propuesta
de SNI-83 para SNI-86; SNI-87 debe registrar la condición y ventana efectivamente
aplicadas, no declarar un aviso por observar cinco valores en una gráfica.

## Matriz adicional

| Escenario | Qué se debe distinguir | Verificación de recuperación |
| --- | --- | --- |
| NGINX | Ingreso perdido frente a upstream caído; no atribuirlo sólo a UI | Hostname/TLS/ruta pública y servicio funcional |
| UI | Documento/bundle inaccesible frente a API caída | Navegación y consulta del fixture |
| Snippets | API caída frente a una dependencia suya | Alta/lectura y ausencia de datos ficticios |
| Permissions | Dependencia inaccesible, sin convertirlo en ausencia de permisos/lista vacía | Owner/lector/tercero con acceso correcto |
| Una base | Identidad específica snippets-db o permissions-db | Conexión y operación de su aplicación, datos conservados |
| Redis | Conectividad/autenticación/AOF/capacidad según señal entregada | Persistencia, backlog y avance; un PING aislado no basta |
| Storage activo | Local o Asset/backend, sin atribuir al proveedor inactivo | Fixture exacto leído tras restaurar y limpieza acotada |
| VM | Pérdida de host/telemetría frente a pérdida de una tarea | Agente y tareas presentes más recorrido funcional |
| Capacidad/disco | Recursos o volumen aislados; no llenar el disco compartido de DEV | Espacio/capacidad restablecidos y escritura verificada |
| Dependencia externa | Falla controlada sin atacar ni modificar al proveedor real | Cliente recuperado, error correctamente clasificado |
| Sin tráfico | Diferenciar ausencia de solicitudes de host/monitor perdido | Sin alarma de tasa de errores ficticia; heartbeat/pérdida de señal según política |
| Respuesta válida de negocio | Resultado esperado del contrato, sin disparar urgencia técnica | Sin aviso espurio y con operación control sana posterior |

Los nombres identifican escenarios, no el número de alertas esperadas: una caída
puede tener síntomas correlacionados. Capturar agrupación/causa que entregue SNI-86,
no crear otra ruta de ingesta ni políticas duplicadas para hacer pasar este ensayo.

## Diagnóstico y restauración

Desde New Relic: ubicar ambiente/servicio/versión, revisar el incidente y luego
host/tarea, upstream, dependencia y saturación correspondientes. Abrir la traza del
alta o el job correlacionado cuando exista. Copiar en la evidencia las consultas
reales de SNI-80/81/82/83/84/85/86 y su rango; esta guía no inventa nombres de eventos
ni campos todavía no entregados.

Desde el inventario operativo: recuperar las réplicas/flags/redes originales,
verificar tareas/imágenes vigentes y repetir el mismo control funcional. Comprobar
señal histórica y recuperación del incidente/aviso. Si la restauración falla,
registrar escalamiento/responsable y mantener el caso FAIL/BLOCKED; no ejecutar una
limpieza destructiva como sustituto de recuperación.

El [probe Asset existente](../../scripts/asset_probe.py) y sus verificadores sirven
para integridad de fixtures; las aceptaciones anteriores acreditan sus revisiones,
no prueban New Relic ni aviso al dispositivo. Los comandos de inventario/release y
recuperación siguen en [SNI-24](../sni-24-bootstrap.md),
[Redis SNI-56](../sni-56-redis.md) y [Asset SNI-33](../sni-33-asset.md).
No reaplicar un stack viejo para restaurar una sola tarea ni cambiar CD durante el
ensayo. PROD se trata separadamente en SNI-88.
