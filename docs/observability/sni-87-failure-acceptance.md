# SNI-87 — Ensayos de fallas y evidencia de recuperación

Preparación al 09/11/2026. **NOT_EXECUTED**: no se interrumpieron VMs/servicios,
no se crearon incidentes ni se envió una notificación. SNI-86 sigue Todo en Linear;
no se puede acreditar detección/aviso antes de disponer de sus alertas y workflow.
Esta guía conserva el alcance del ticket; no elige umbrales, SLO ni canal móvil.

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
registrar la preparación faltante. Para separar consumidor y publicador, verificar
el mecanismo real de operación de SNI-83 y el despliegue: si comparten proceso,
no parar Snippets completo y afirmar que sólo cayó el consumidor. Acordar un
control específico o un entorno aislado que conserve el resto activo.

En el alta fallida, una respuesta incierta de red no autoriza repetir una mutación
con una clave nueva: seguir el contrato de idempotencia existente. El alta sana de
recuperación es una intención nueva identificada; no reemplaza la conciliación de
una operación cuyo resultado sea incierto.

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
