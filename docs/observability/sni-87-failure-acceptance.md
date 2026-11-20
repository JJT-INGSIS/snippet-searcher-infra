# SNI-87 — Ensayos de fallas y evidencia de recuperación

Actualización al 19/11/2026. **EVIDENCIA TÉCNICA COMPLETA; RECEPCIÓN HUMANA PENDIENTE**. SNI-85 y SNI-86
están Done: hay chequeo autenticado, condiciones y workflows desplegados.
Los tres casos principales produjeron fallo, incidente, envío de correo/push
y recuperación. PrintScript devolvió `502` y luego una nueva alta `201`. El job
del consumidor terminó con tres items y tres claves distintas, sin duplicación lógica;
se restauraron las reglas de la identidad de prueba. La [evidencia fechada](../evidence/sni87-dev-2026-11-19.json)
separa los hechos comprobados de lo pendiente. La recepción humana en el teléfono
queda pendiente por indicación de Thiago; `Sent to 1 devices` no la reemplaza.

El [registro del 18/11](../evidence/sni87-readiness-2026-11-18.json) es histórico:
entonces faltaban SNI-85/86 y no se ejecutaron cortes. No usarlo como inventario actual.
Las condiciones, ventanas y responsables efectivos están en
[SNI-86](sni-86-alerts-dashboards.md). No se cambian sus umbrales para aprobar el ensayo.

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
PEL con idle creciente es otro caso. SNI-86 desplegó la condición `69984639`:
lag conocido positivo y edad elegible mayor que 300 s durante cinco ventanas
consecutivas de un minuto, con dos minutos de demora de agregación. Reservar unos
doce minutos desde el trabajo pendiente, más entrega y restauración; observar cinco
valores en una gráfica no acredita el incidente. PrintScript usa `69984637`, con
dos ventanas de un minuto y la misma demora de agregación.

## Operaciones autenticadas repetibles

[El runner DEV](../../scripts/run_dev_drill.py) reutiliza el login de SNI-85 y su
imagen Cypress fijada. Ejecutar como root en `vm-snippet-dev`, con el árbol
`scripts/` y `observability/` de esta revisión en una carpeta propia del ensayo.
No reemplazar el runner de SNI-85 ni copiar sus credenciales. El archivo existente
`/etc/snippet-observability/dev/functional-auth0.json` se monta sólo en lectura;
la licencia de New Relic no entra en el contenedor. JWT y credenciales permanecen
en memoria del navegador; no hay capturas, videos ni logs de Cypress persistidos.
La salida admite sólo estados HTTP, UUID, request ID y tipos estables.

```sh
python3 -B scripts/run_dev_drill.py healthy-create
python3 -B scripts/run_dev_drill.py enqueue-format
python3 -B scripts/run_dev_drill.py job-status --job-id UUID_DEL_TRABAJO
python3 -B scripts/run_dev_drill.py restore-format
```

`healthy-create` deja un snippet de prueba `SNI-87 ...` con descripción dedicada.
`enqueue-format` afecta exclusivamente las reglas de esa identidad de prueba,
conserva el original en `/var/tmp/sni87-20261119-rules-before.json` y rechaza
sobrescribirlo. Restaurar las reglas después de acreditar el trabajo original;
esa restauración puede generar otro trabajo legítimo. No borrar el snapshot
para forzar un reintento ni ejecutar la operación con una cuenta personal.

Para el alta con PrintScript caído, primero comprobar estado sano y preparar
el temporizador de restauración, con el nombre que exige esta revisión:

```sh
systemd-run --unit=sni87-printscript-restore-20261119b --on-active=8min \
  /usr/bin/docker service scale --detach=true snippet-searcher-dev_printscript-service=1
python3 -B scripts/run_dev_drill.py printscript-unavailable --inject-printscript
```

El navegador inicia sesión y confirma el listado antes de solicitar el corte;
el host espera ese aviso, comprueba la réplica original y detiene sólo PrintScript.
El contenedor de Cypress no recibe socket Docker ni privilegios. Tras comprobar
incidente/envío, restaurar a una réplica y repetir `healthy-create`; el timer es
la recuperación de respaldo. Si falla la prueba, restaurar inmediatamente.
El 19/11 el timer alcanzó a ejecutar la restauración; intentar detener después
una unidad transitoria ya eliminada devolvió `5`, aunque la nueva alta fue `201`.
Comprobar servicio y operación real antes de clasificar un error de limpieza.

El primer intento detuvo PrintScript antes de iniciar sesión y el navegador
falló antes de comprobar el alta. Se restauró y se repitió con sesión previa;
el intento fallido no se cuenta como PASS. Se eligió este orden para aislar la
creación de los pasos de entrada de la UI. Su costo es un pequeño protocolo de
coordinación navegador/host; operar manualmente sería más simple, pero menos
repetible y sin los mismos controles. Es análisis propio del proyecto con el marco
de decisiones y trade-offs de capítulos 2/21 del
[índice de Fundamentals of Software Architecture, 2e](https://www.oreilly.com/library/view/fundamentals-of-software/9781098175504/).

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

### Cortes secuenciales de réplicas

[`run_dev_replica_matrix.py`](../../scripts/run_dev_replica_matrix.py) exige DEV,
réplicas originales 1/1, publicador/consumidor activos, sin deploy pendiente ni
jobs/outbox/permisos de ejecución pendientes. Toma el lock del despliegue por cada
caso. El primer preflight del 19/11 abortó sin cortar nada porque contaba el colector
como aplicación; son ocho servicios de aplicación y un colector. Quedó registrado
como intento abortado, no PASS.

```sh
python3 -B scripts/run_dev_replica_matrix.py \
  --components nginx ui snippets-service permissions-service snippets-db redis \
  --hold-seconds 420 --execute
```

Cada caso tiene un timer independiente de restauración a la réplica original,
`finally` y recibo privado en `/var/tmp/sni87-matrix-<UTC>/`. Después espera salud
de las aplicaciones, compara la plantilla original y ejecuta una nueva alta real.
No borra volúmenes ni modifica las imágenes. Su estado final es
`RESTORED_AWAITING_ALERT_EVIDENCE`: debe correlacionarse con la señal, incidente,
envío y cierre de New Relic. Un proceso `Type=oneshot` largo figura `activating`
mientras trabaja; consultar el journal/recibos y no reiniciarlo por ese estado.
Al lanzarlo con `systemd-run`, usar `--no-block` para no confundir el timeout del
comando de Azure con la finalización del ensayo.

Las réplicas se restauran sin gastar la cuota de los cortes de infraestructura CD.
Se acepta una ventana sin servicio a cambio de una falla reversible que conserva
la plantilla; matar procesos en un loop produciría reinicios menos deterministas.
Las alertas de disponibilidad pública pueden permanecer abiertas entre cortes
contiguos de componentes distintos. Los incidentes facetados de Swarm y los tiempos
de los recibos identifican la causa; no contar cada síntoma como una falla distinta.

### Storage activo y fixtures aislados

[`run_dev_storage_drill.py`](../../scripts/run_dev_storage_drill.py) prepara un
corte de siete minutos de la **vista del colector** sobre el volumen local activo,
haciéndola sólo lectura. Verifica `up=0` real, prepara la inversa con timer y
restaura escritura/lectura/contenido; finalmente ejecuta otra alta real. No cambia
el montaje de Snippets ni los bytes de usuarios. Rechaza PROD, otro volumen y una
vista que ya fuese sólo lectura.

```sh
python3 -B scripts/run_dev_storage_drill.py --execute
```

Esto ensaya el probe y su alerta sobre el proveedor activo; **no demuestra una
interrupción de escritura de la aplicación ni daño del backend**. Una mala
configuración del observador puede alertar aunque la aplicación siga escribiendo:
es una limitación de separar el probe de su proceso consumidor, no una licencia
para presentar un falso outage de la aplicación. El recibo distingue ese alcance. En el ensayo actual, Snippets confirmó otra alta
`201` a las 02:01:13 UTC mientras el probe reportaba `up=0`; no se infiere una
caída de la aplicación a partir del estado del observador.
No ejecutar en paralelo con otro corte; usa el mismo lock de despliegue.

La comparación cruda del ensayo devolvió `originalTemplatePreserved: false` y se
conserva ese resultado. La auditoría observó reordenamiento de montajes, campos
vacíos y dos defaults explicitados por CLI: DNS `{}` y apagado de diez segundos
([default documentado por Docker](https://docs.docker.com/reference/cli/docker/service/create/)).
La restauración restituyó la vista escribible y la aplicación volvió a confirmar
un alta. La versión entregada compara esos defaults de forma equivalente y conserva
sus hashes; un DNS no vacío, otro timeout, volumen o imagen siguen siendo drift.
El hash de la versión realmente ejecutada se registra separado de la corregida;
no se cambió retrospectivamente el recibo del ensayo.

La [aceptación Docker aislada repetida](../evidence/sni87-isolated-faults-2026-11-19.json)
comprobó falta de espacio AOF en tmpfs, escritura local sólo lectura y falla de
transporte de Asset, con recuperación. Sus recursos y credenciales son exclusivos
del proyecto QA; los contenedores propios se detuvieron al finalizar. No ingresa
muestras a New Relic ni demuestra recepción de avisos DEV por esos casos.

### Corte de VM con recuperación desde Azure

Antes de detener DEV, esperar que los ensayos anteriores hayan restaurado sus
componentes, no queden timers de restauración ni despliegues activos y los jobs
estén ociosos. [`dev_drill_state.py`](../../scripts/dev_drill_state.py) rechaza PROD,
Docker remoto, journal pendiente y réplicas incompletas; conserva sólo hashes,
imágenes y nombres públicos, sin environment ni secretos.

```sh
python3 -B scripts/dev_drill_state.py before
```

Usar **Detener** sobre `vm-snippet-dev` en el portal Azure y conservar el estado
observado y los tiempos UTC. El operador debe mantener abierto el control Azure
fuera de la VM: un timer alojado dentro no puede recuperar una máquina apagada.
Tras una pausa acotada para observar pérdida de SystemSample y aviso, usar **Iniciar**.
No cambiar IP, NSG, discos, credenciales ni reaplicar el stack. Esperar la convergencia
antes de ejecutar la comparación:

```sh
python3 -B scripts/dev_drill_state.py after
python3 -B scripts/run_dev_drill.py healthy-create
python3 -B /opt/snippet-observability/dev/functional/run.py
```

La comparación acredita conservación del release/plantillas y réplicas; imprime
`functionalRecoveryVerified: false` deliberadamente. Las operaciones reales
posteriores y las muestras/cierre en New Relic completan la recuperación. Una
recepción `SUCCESS` del proveedor de push todavía requiere confirmación humana.
El snapshot fechado no se sobrescribe para forzar otro intento; preparar otro
recibo revisado si se repite la ventana.

En el arranque del 20/11 apareció un contenedor PostgreSQL de una tarea vieja,
además del vigente sano. El primer control de estado abortó antes de las operaciones
funcionales. Se inspeccionaron los task IDs: el viejo estaba `shutdown/failed` y
`unhealthy`, y el vigente `running/healthy`. Se detuvo sólo el contenedor obsoleto,
sin eliminarlo ni tocar volúmenes, y se repitió la verificación. No seleccionar un
contenedor arbitrario ni detener una réplica vigente para resolver ese síntoma.

### Controles sin falla

El 20/11 UTC, entre 00:15 y 00:30, hubo quince muestras del host y cero solicitudes
API elegibles; no se abrieron incidentes. Se verificó con consultas de eventos,
no haciendo fallar un cociente con denominador cero. Las tres respuestas esperadas
400/422/404 del 19/11 aparecen en logs de ingreso y aportan cero fallas técnicas
al predicado `status >= 500 AND status < 600` de SNI-86. No equivale a garantizar
que nunca habrá un aviso de otra causa durante una respuesta de negocio.

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


## Resultado del cierre técnico — 19/11 Argentina, 20/11 UTC

Los tres casos principales y los seis cortes de réplicas tienen detección,
recuperación y evidencia fechada. Storage produjo el incidente `6338cb4f-4adc-4fd7-89da-0413dc0c597a`
y recuperó el probe; su alcance fue la vista del observador. La VM se detuvo a las
02:19 UTC y se solicitó iniciar a las 02:25:38; el incidente de host abrió a las
02:24:01 y cerró a las 02:31:02. Los incidentes públicos de API/UI también cerraron.

El host sano no acreditó por sí mismo la recuperación de negocio: después del
arranque, el listado quedó esperando y el navegador abortó (499 en ingreso).
Las conexiones TCP a las bases/Permissions funcionaban; no se aisló la causa exacta
de la espera. Se renovó sólo Snippets con `docker service update --force --no-resolve-image`,
conservando imagen, variables, secretos, montajes, configs, usuario y redes.
Después, el alta devolvió 201 a las 02:46:14 y el chequeo autenticado del fixture y
su contenido terminó SUCCESS, con reconocimiento de New Relic. Es una mitigación
manual verificada, no una afirmación de recuperación automática ni de causa raíz.
La plantilla completa cambia por ForceUpdate/defaults; no se la presenta como idéntica
byte a byte tras esa mitigación. No se modificó código de los servicios ni de compañeros.

DEV quedó encendido y con nueve servicios en 1/1; PROD quedó desasignado sin rollout.
Pasaron 324 tests locales y la QA Docker aislada. La recepción humana de los pushes
sigue pendiente por decisión del usuario: el ticket no se declara Done sólo con
`Sent to 1 devices`. El registro JSON conserva los intentos fallidos y las
normalizaciones auditadas, además de las operaciones que sí se verificaron.
