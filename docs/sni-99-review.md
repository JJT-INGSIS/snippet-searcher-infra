# SNI-99 — Revisión de runtime y reemplazo de coordinadores

Revisión del 23/11/2026 sobre infra `cfe4956824f232285abea499c4189451b490504d`.
No se desplegó este cambio, reinició una VM ni modificó una red o credencial.

## Defecto confirmado y decisión

`swarm/stack.yaml` asignaba `start-first` a las tres aplicaciones. El overlay
Redis lo corregía para Snippets y PrintScript, pero los releases sin Redis
seguían permitiendo una tarea nueva antes de detener la anterior. `replicas: 1`
no evita ese solapamiento transitorio. La prueba de regresión falló en ocho
combinaciones: dos ambientes, dos coordinadores y dos topologías sin Redis.

Esto contradice el contrato de un coordinador activo de
[`execution-contract.md`](architecture/execution-contract.md): las sesiones de
ejecución no pueden tratarse como procesos intercambiables con memoria compartida.
Una petición posterior podría llegar a otra instancia que desconozca la sesión.

Se comparte la configuración base mediante anchors y se sobrescribe únicamente
el orden de actualización para Snippets y PrintScript a `stop-first`. Conserva
límites, placement, reinicios, monitor de actualización y rollback. Permissions,
UI y NGINX conservan su política; las bases y sus mounts no cambian.

| Alternativa | Beneficio | Costo que implica aquí |
| --- | --- | --- |
| `start-first` | Puede reducir la pausa durante el reemplazo | Solapa coordinadores que no cumplen un contrato de ejecución distribuida |
| `stop-first`, elegido | Evita solapar las tareas administradas por Swarm | Pausa de servicio y posible interrupción de ejecuciones en memoria |
| Distribuir las sesiones y coordinar varias instancias | Permitiría revisar la restricción | Cambia el protocolo de ejecución y recuperación; fuera de esta corrección |

No se promete migrar sesiones ni conservar procesos en ejecución. Debe aplicarse
en una ventana sin ejecuciones activas mediante el procedimiento operativo
revisado. `Swarm.update()` cambia sólo la imagen: un CD de aplicación no instala
por sí mismo esta política nueva sobre un servicio antiguo. Hay que reconciliar
la definición del stack y comprobar `Spec.UpdateConfig.Order` de ambos servicios.
No se cambió el CD de Juanfran en esta PR.

El análisis de alternativas es nuestro. Como marco de documentación se usa el
análisis de trade-offs y registro de decisiones del libro de Richards/Ford,
*Fundamentals of Software Architecture*, 2.ª ed., capítulos 2, 21 y 27 según el
[índice editorial](https://www.oreilly.com/library/view/fundamentals-of-software/9781098175504/).
El comportamiento de actualización se verifica en la
[especificación de Docker](https://docs.docker.com/reference/compose-file/deploy/#update_config).

## Recorrido y cobertura de la revisión

| Tramo revisado | Dónde y garantía observada | Límite o riesgo |
| --- | --- | --- |
| Imagen PrintScript | Dockerfile, Gradle/settings y application.properties de PrintScript `70533f7`: build JDK 21, runtime no root, dependencia `printscript-v1:1.2.0` | La dependencia del código fuente no demuestra la de una imagen vieja desplegada |
| Local | `compose.yaml`, `compose.redis.yaml`: builds hermanos, secretos de build separados del runtime, volúmenes y perfil optativo | Renderizar no acredita que las tres aplicaciones hayan arrancado |
| Stack | Base y overlays UI, ingress, TLS, Asset, Redis, background, APM y observability | Tener un archivo de overlay no significa que esté activo |
| Selección | `stack_release.py`, `stack_runtime.py`: digest exacto, ambiente, overlays explícitos, proveedor y referencias de secretos | Los manifiestos de bootstrap son ejemplos históricos; no son inventario actual |
| Preparación | `prepare_swarm_vm.sh`, preflight de `bootstrap_swarm.py`: nodo/ambiente, secretos y volúmenes antes de aplicar | Un único nodo no tolera pérdida de VM/disco |
| Operación interrumpida | `deploy_infrastructure`, `reconcile_infrastructure`: diario pendiente, referencias anteriores/candidatas y recuperación acotada | Rollback de infraestructura no revierte datos ni migraciones |
| Convergencia | `wait_for_stack.py`: digest deseado, tareas running y estabilidad 60 s; falla si Swarm pausó la actualización | Convergencia de tareas no prueba por sí sola el negocio |
| Disponibilidad | `verify_stack.py`: healthchecks, SQL autenticado, migraciones y permisos del storage local, probe interno | HTTP de Snippets no certifica su conexión a PostgreSQL |

`verify_stack.py` además exige el mensaje JDBC de arranque entre las últimas 200
líneas de Snippets incluso en algunos despliegues acotados. Es una dependencia
frágil de evidencia histórica: puede faltar por actividad normal. No se eliminó
para evitar sustituir silenciosamente evidencia de conexión de la aplicación por
un mero `SELECT` directo a la base. Requiere acordar con Runtime/CD qué prueba
estable la reemplaza antes de cambiar ese contrato.

## Inventario: qué sabemos y qué falta contrastar

`docs/sni-20-acceso-vms.md` y `docs/sni-21-docker-swarm.md` registran dos VMs y
dos Swarms independientes, cada uno con un nodo manager. Los puertos internos de
Swarm y las bases no necesitan exposición pública para esa topología. Las reglas
efectivas de Azure pueden haber cambiado: no se certificaron de nuevo aquí.

Los JSON `swarm/{dev,prod}-release.json` corresponden al bootstrap de octubre.
El registro `docs/evidence/sni88-inventory-2026-11-19.json` declara explícitamente
PROD local, sin Redis/Asset y rollout todavía no aplicado **en esa fecha**. No
se presenta como estado del 23/11 ni se reemplaza por una suposición posterior.

Para completar la aceptación operativa, recoger en lectura por ambiente:
hostname/manager, `service ls`, digests y políticas mediante campos seleccionados
de `service inspect`, nombres/mounts de volúmenes y el release confirmado en
`/home/azureuser/.local/state/snippet-searcher/{dev,prod}/release.json`. Contrastar
con `pending.json` y la versión del bundle usado. No volcar variables completas
ni el contenido de secretos. Coordinar la revisión de convergencia con Juanfran
y la de ingreso/NSG con Juanchi. Esta PR pide su revisión, no afirma que ocurrió.

## Evidencia local

- Python 3.13: **338 pruebas aprobadas**, incluida la matriz de seis renders del
  nuevo `test_execution_rollout.py` (legacy/ampliado/Redis por DEV y PROD).
- `docker compose --env-file /dev/null config --quiet`, sin credenciales reales.
- `validate_stack.py`, `validate_expanded_stack.py`, `validate_asset_config.py`
  y `validate_redis.py`: aprobados; `bash -n prepare_swarm_vm.sh`: aprobado.
- Python 3.11.0 del host no soporta el filtro seguro usado por `tarfile`; se usó
  Python 3.13 en vez de debilitar la validación de archivos del bundle.
- No se ejecutó un rolling update real ni se acredita inventario fresco de VM.
  SNI-99 sigue en curso hasta el contraste operativo y la revisión cruzada.
