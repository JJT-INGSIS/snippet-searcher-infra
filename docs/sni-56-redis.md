# SNI-56 — Redis para trabajos asíncronos

Decisión del 02/11/2026. Redis Streams es un componente optativo del stack de cada
ambiente. PostgreSQL conserva eventos, trabajos, progreso y resultados. Instalarlo
no habilita publicadores, workers ni handlers. No se crean VMs, Sentinel, Cluster
ni servicios de aplicación. Una réplica implica interrupción durante reemplazos;
no ofrece alta disponibilidad.

## Configuración

- Redis 7.4.7 Alpine por digest, una réplica, volumen
  `snippet-searcher-<ambiente>_redis_data`, placement `node.labels.database == true`.
  Mover la tarea a otro nodo no transporta los datos del volumen local.
- Red interna `redis_internal`, sin puertos publicados; sólo Redis y Snippets.
- `stop-first` sólo para Redis, Snippets y PrintScript. `x-app-deploy` permanece
  intacto y Permissions conserva `start-first`. El corte inicial envía únicamente
  esos tres servicios a stack deploy, sin `--prune`, preservando los demás.
- `maxmemory 128mb`, `noeviction`, contenedor limitado a 384 MiB y 0,5 CPU. El
  margen contempla buffers/fork, pero no garantiza sobrevivir a cualquier carga:
  el límite del contenedor puede terminar el proceso por OOM.
- AOF `everysec`, sin RDB periódico; snapshots explícitos para backup.
  `aof-load-truncated no` impide aceptar silenciosamente una cola truncada.
  Un corte abrupto puede perder escrituras recientes; AOF no sustituye al outbox.
- Sin trimming, TTL de eventos, `KEYS *`, `FLUSHDB` ni limpieza de pendientes.

## Credenciales y uso local

Desde la raíz de infra:

```sh
python scripts/prepare_redis_secret.py secrets/redis_password
docker compose -f compose.yaml -f compose.redis.yaml up -d redis
```

El generador produce 64 caracteres hexadecimales aleatorios sin salto de línea,
no imprime ni sobrescribe credenciales. Usa 0600/0700 en Linux; en Windows proteger
también las ACL de la cuenta. `secrets/` está ignorado. No poner contraseñas en
`.env`, YAML, manifests, URLs, argv `-a`, logs ni Config.Env de Docker.

Después de aprobar el remoto, generar el archivo en la VM y crear el secret con
`docker secret create redis_password secrets/redis_password`, sin imprimirlo.
Snippets lo recibe como `spring.data.redis.password` por su configtree existente.
El entrypoint genera una ACL SHA-256 en tmpfs, modo 0600, y baja privilegios con
el entrypoint oficial. El healthcheck usa REDISCLI_AUTH sólo en el proceso de
redis-cli; no aparece en argv, Config.Env ni salida del healthcheck. Un
administrador del host/daemon puede leer secretos; no se promete aislarlos de él.
No usar shell tracing. Permissions y PrintScript no reciben credenciales Redis.

## Transición del CD: orden obligatorio

`v0.6.2` fija infra `9fcc49204260566667171cdde320eea8f81c965d`: su lector rechaza
releases con Redis. `tests/legacy/v0.6.2-stack_release.txt` conserva ese código
exacto y prueba la incompatibilidad. Un tag nuevo con el mismo pin tampoco sirve.

1. Revisar e integrar esta implementación. Obtener el SHA completo del commit
   integrado; no usar una rama móvil ni inventar el SHA antes del merge.
2. Cambiar `INFRA_REVISION` de `github-workflows/.github/workflows/cd.yml` a ese
   commit revisado, comprobar que la descarga de herramientas usa ese pin y
   publicar `v0.6.4` después de sus checks. No mover los tags publicados.
3. Actualizar `.github/workflows/pipeline.yml` de Snippets, PrintScript,
   Permissions y UI a `v0.6.4`, incluidas las dos referencias de UI. Mantener
   entradas y contratos. Todavía se despliega el release sin Redis en esta fase.
4. Esperar todos los CD push/manual activos del ambiente. La instalación verifica
   callers, ausencia de ejecuciones activas y que el pin central contiene el
   contrato Redis/despliegue selectivo; falla de forma cerrada si no puede comprobarlo.
5. Sólo después de aprobación expresa para dev: obtener su registro confirmado
   actual y generar el candidato con `bootstrap_swarm.py plan <registro.json>
   --install-redis`. Guardar y revisar ese JSON; no combinar imágenes nuevas,
   cambios de UI, proxy ni storage con este corte.
6. Ejecutar `preflight` y `deploy <candidato.json> --infrastructure` mediante el
   procedimiento SNI-25, lock y journal del ambiente. Verificar convergencia,
   health, volumen y conservación de servicios. Mantener workers deshabilitados
   hasta tener handlers funcionales.

Durante la implementación local no se cambiaron tags, callers ni VMs. La transición
y el despliegue autorizado de dev se completaron después del merge: ver
[evidencia SNI-56 en dev](sni-56-dev-verification.md). No hay placeholders
ejecutables en el workflow central. No aplicar el overlay a mano en la VM: omitiría el protocolo
de registro, verificación y recuperación. Se acepta una breve interrupción de
Snippets/PrintScript durante sus reemplazos, preservando Permissions y los demás.

## Memoria, disco y AOF lleno

### Corrección del bundle SSH

El primer CD de aplicación posterior a instalar Redis detectó que el archivo
tar de `v0.6.3` no incluía `redis_runtime.py` y sus dependencias/recursos. El
checkout completo y el despliegue manual sí los tenían, por lo que las pruebas
anteriores no cubrían esta frontera. El fallo ocurrió al validar el registro
previo, antes de actualizar la aplicación o crear su journal de operación.

La corrección incorpora módulos Redis, validador NGINX, overlay y configs al
bundle explícito. Las pruebas abren el tar real, comprueban imports locales
incluidos los condicionales y ejecutan validación/render desde una extracción
aislada, sin importar desde el repositorio ni usar el daemon Docker. Para
distribuirla se requiere un nuevo pin revisado y `v0.6.4`: reejecutar el run viejo
con `v0.6.3` no sustituye sus herramientas inmutables. Actualizar los cuatro
callers antes de otra operación manual de infraestructura que exija el gate.

El preflight exige 384 MiB de RAM disponible y 512 MiB libres en el filesystem
Docker. Son mínimos de admisión, no cuota de disco ni capacidad garantizada.
El volumen Docker local no tiene aquí un límite portable. Revisar `df -h` sobre
DockerRootDir, tamaño y tendencia del AOF antes del corte y durante QA/operación;
reservar margen adicional para rewrites, snapshots y las demás aplicaciones.
Ampliar disco o mover backups externos antes del mínimo; no borrar eventos.

`noeviction` rechaza nuevas escrituras al alcanzar maxmemory. Con disco lleno,
Redis puede rechazar escrituras AOF; el healthcheck falla si
`aof_last_write_status != ok`. El publicador conserva la intención en PostgreSQL y
reintenta con sus límites existentes. Swarm puede reiniciar tareas no saludables:
reiniciar no libera disco ni repara AOF. No usar reparación con truncado automático.

Ante una falla: pausar publicación/consumo/admisión, preservar volumen y BD,
liberar espacio ajeno a los datos pendientes o ampliar disco, revisar persistencia
y reanudar cuando sea apto. Si AOF está corrupto, conservar copia para diagnóstico
y restaurar en otro volumen; nunca borrar el original ni sus pendientes.

## Backup y recuperación

En el nodo que aloja Redis; `<contenedor>` es su task local, no el servicio Swarm:

```sh
python scripts/redis_storage.py backup <contenedor> /ruta-privada/redis-20261102.rdb
python scripts/redis_storage.py restore /ruta-privada/redis-20261102.rdb <volumen-nuevo> secrets/redis_password
```

Proteger los archivos y copiarlos fuera de la VM. El backup solicita BGSAVE nuevo,
espera su confirmación y exporta RDB con checksum/imagen sin sobrescribir archivos.
Es un snapshot puntual; no respalda PostgreSQL ni las escrituras posteriores.
Se evita copiar AOF multipart mientras se reescribe. Restore valida checksum,
rechaza volúmenes existentes, carga RDB sin AOF y genera AOF nuevo antes de parar.
Conserva el volumen nuevo incluso ante fallos; no lo conecta automáticamente al
servicio. Conectarlo requiere un cambio operativo revisado, preservando el volumen
anterior y la identidad del stack.

Tras pérdida/restauración de Redis, seguir `snippets-service/docs/background-outbox.md`
y `background-consumer.md`: pausar procesos, ejecutar internamente
`OutboxRecovery.requeueBatch(1..100)` para trabajos incompletos elegibles y repetir
cuando expiren reservas/diferidos. Recrear el Consumer Group idempotentemente
desde el historial retenido y reanudar. La capacidad existe, pero requiere un
contexto Spring autorizado conectado a PostgreSQL; no hay nuevo endpoint/CLI
público. No inventar SQL que borre estado ni liberar reservas remotas sólo por edad.
Una ejecución `UNKNOWN` se reconcilia antes de iniciar otra en PrintScript.

Reconstruir desde BD difiere de recuperar PEL mediante XAUTOCLAIM. Ambas vías
conservan IDs de dominio y admiten duplicados; la idempotencia de SNI-57/58 protege
los efectos confirmados. Los trabajos terminados no necesitan ejecutarse de nuevo.

## Evidencia local y límites

```sh
python -B -m unittest discover -s scripts -p 'test_*.py' -v
python -B scripts/validate_redis.py
python -B scripts/verify_redis_persistence.py
```

Se cubren renders dev/prod y comparación íntegra de servicios ajenos; lector
histórico; CD independiente; límites y guards; Redis real autenticado sin puertos,
reinicio AOF, PEL/Consumer Group, OOM y filesystem tmpfs acotado lleno; health
fallido y recuperación; backup restaurado en volumen nuevo y reiniciado con AOF.
Snippets agrega integración PostgreSQL/Redis que conserva outbox/pendientes con
disco lleno y publica después de recuperar espacio.

Swarm/unit tests requieren Linux. Localmente se usó runner sin red, secretos ni
socket Docker para unit tests y Python/Java nativos con Docker Desktop para las
integraciones. CI incorpora también estos checks en su runner aislado.
Verificación local del 02/11: 204 unit tests de infra aprobados; renders Compose,
Swarm dev/prod y validadores anteriores aprobados; aceptación Redis real aprobada.
Build completo de Snippets aprobado: 545 casos, 529 ejecutados sin fallos y 16
omitidos por integraciones opcionales; el nuevo caso de disco lleno sí se ejecutó.
Tras la aprobación explícita se completó el corte real de Swarm en dev y se
verificaron autenticación, AOF/PEL y preservación de servicios y datos. La
[evidencia remota](sni-56-dev-verification.md) registra el alcance y sus límites.

Alternativas descartadas: anchor global por impacto en Permissions; start-first
en coordinadores por solapamiento; contraseña en environment/puerto público por
exposición; eviction/trimming por pérdida de entregas; replicación/Cluster por
alcance y recursos; confiar sólo en AOF por su ventana de pérdida. Se acepta el
trabajo operativo de espacio, backups y recuperación. No se agregan handlers,
OAuth, dashboards ni políticas de retención en SNI-56.


## Durable PrintScript operations (SNI-78, 2026-11-05)

The opt-in Redis overlays now connect PrintScript to the private Redis network
and mount the existing password via configtree, never a command-line argument.
`PRINTSCRIPT_OPERATIONS_ENABLED` defaults to false. Enable it only with the new
provider image and `PRINTSCRIPT_OPERATIONS_DEPLOYMENT_MODE=single-stop-first`.
The Swarm namespace includes `DEPLOY_ENV`; retain one PrintScript replica and
stop-first replacement. Terminal operation inputs/results have seven-day TTL;
active records do not expire. Redis persistence/noeviction and memory limits
remain applicable; storage exhaustion is an explicit error, not silent eviction.

Deploy/enable the provider before the new Snippets workers, verify the operations
API and matching execution budget, and drain/independently verify legacy held
permits first. The new application preserves UNKNOWN for legacy synchronous
attempts without identity. This is not a horizontal/multiple-provider recovery
protocol. See PrintScript `docs/durable-operations.md` and Snippets
`docs/durable-processing.md` for the approved lifecycle and verification.

This change supplies runtime wiring only. It does not edit CD workflows, enable
features on a VM, deploy an image or create Azure resources.
