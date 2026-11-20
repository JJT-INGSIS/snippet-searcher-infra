## Activación retomada — 20/11/2026

El administrador confirmó la SPA `snippet-searcher-prod-ui`, Client ID público
`3WzM34S00lsCGU0p4hYImgs2xCuPgejW`, y la API con audience
`https://jjt-snippets-prod.duckdns.org/api`, URLs PROD y acceso delegado.
La sesión del dashboard venció; esta confirmación del administrador todavía no
es una prueba de login. SNI-87 fue cerrado por aceptación técnica de Thiago.

El inventario se volvió a verificar: siete servicios 1/1, release sin cambios,
sin journal pendiente, Auth0/APM apagados y JVM sin launcher de APM. Se generaron
respaldos root-only de ambas bases, contenido y release en la VM antes de promover.
Se verificó que se pueden listar los archivos; no se afirma un restore probado.

La promoción usa las imágenes verificadas de DEV mediante PRs dev → main; no se
reconstruye para PROD ni se editan implementaciones de compañeros. Incluye el
contenido acumulado de DEV, no sólo el agente. Snippets agrega migraciones de
funcionalidades ya verificadas; rollback de imagen no revierte su esquema.
No se habilitan Redis, Asset, publicador ni consumidor como efecto del corte.

### Aplicación acotada y recuperación

`bootstrap_swarm.py plan <release-confirmado> --auth0-prod` arma un candidato con
los parámetros públicos confirmados. `deploy <candidato> --infrastructure --auth-only`
cambia sólo Snippets/UI bajo el mismo lock/journal, conservando APM, imágenes,
bases y volúmenes. Rechaza client/audience DEV, hostname distinto, HTTP sin TLS y
cambios ajenos a identidad. El estado deshabilitado anterior sigue siendo destino
de recuperación. La regla usa el ambiente real al inspeccionar Snippets, también
al reanudar un corte interrumpido. La actualización de imágenes sigue pasando por CD.

El gate manual exige los cuatro callers v0.6.8, incluido PROD sin Redis. Mantener
v0.6.2 bloqueaba un corte después de promover los callers actuales; esto no
publica ni mueve tags centrales. La nueva dependencia `auth_rollout.py` y el
contrato público PROD viajan en el bundle para recuperación independiente de SSH.

`production_observability_runtime.py` separa `stage`, `provision`, `verify` y
`start`. Está restringido a root en el manager PROD x86-64, siete servicios sanos,
la topología local sin Redis, UID de contenido 10001 y ausencia de pending. Usa
el lock del CD; provisión exige además SHA-256 del release revisado. Rechaza
colisiones de runtime, roles, secretos y licencia: un fallo parcial se inspecciona,
no se reintenta para rotar credenciales. No reinicia bases ni agrega aliases.

Antes de `provision`/`start` se requiere autorización de la instalación concreta:
agente oficial privilegiado con socket Docker; dos roles `nri_monitor` limitados
a `CONNECT`/`pg_read_all_stats`, sin SELECT a tablas; dos secretos nuevos sólo
para el colector; ingesta en la cuenta 8718557 con configuración PROD. No copiar
credenciales DEV. La licencia entra por stdin y se guarda root-only. `verify`
exige métricas nativas presentes y probe de contenido/capacidad exitoso; no confunde
salida 0 sin métricas con salud ni acredita ingesta por un render local.

Se conserva el split aprobado en DEV: simplifica operar el mismo empaquetado y
separa las contraseñas de bases del agente, a costo del acceso amplio del agente al
host y de mantener un instalador PROD restringido. La alternativa de abrir las
barreras DEV mediante sustitución de nombres se descarta porque permitiría ejecutar
operaciones sobre una topología no revisada. Marco de análisis: capítulos 2/21 del
[índice de Fundamentals of Software Architecture, 2e](https://www.oreilly.com/library/view/fundamentals-of-software/9781098175504/);
la elección concreta es del proyecto.

**Lo anterior describe preparación y controles; aún no acredita corte Auth0,
recepción de telemetría, Browser, checks, alertas ni SLO PROD.** El estado histórico
de abajo se conserva como antecedente, no como bloqueo Auth0 actual.

---

# SNI-88 — Preparación de cobertura PROD

Estado al 19/11/2026: **INVENTARIO ACTUAL VERIFICADO; COBERTURA PROD SIN APLICAR**.
SNI-85/86 están Done. Los tres ensayos principales DEV de SNI-87 produjeron
incidentes y envíos; su recepción humana y la matriz restante siguen pendientes.

PROD se encendió para inspección autorizada, conservando sus imágenes y datos:
siete servicios saludables, dos bases y storage local; sin Redis, Asset ni Azurite.
Auth0/APM y workers están deshabilitados. Las tres imágenes JVM existentes carecen
del launcher New Relic: activar solamente una variable no las instrumenta.
Registro: [inventario actual](../evidence/sni88-inventory-2026-11-19.json).

La sesión Auth0 recuperada corresponde al tenant correcto, pero su rol es
`Editor - Specific Apps` y sólo muestra las dos aplicaciones DEV. El
[contrato público PROD](../../auth0/production.public.json) deja preparados nombre,
issuer, audience, callback y orígenes; client ID, conexión y TTL requieren
confirmación/configuración de un administrador. No contiene secretos ni habilita
OAuth por sí mismo. También debe revisarse la promoción de imágenes instrumentadas,
con sus migraciones, mediante CD y evidencia DEV; no reemplazar las imágenes a mano.

El renderer candidato usa los aliases de servicio que ya ofrece Swarm para ambas bases.
Esto evita agregar alias y reiniciar bases durante la instalación de colectores;
a cambio depende de esos aliases y de la red aislada de PROD. No se agregan Redis ni workers
para justificar una señal. La instalación operativa, credenciales/permisos,
Browser/check, políticas y recepción siguen pendientes; este documento no los
presenta como aplicados.

## Candidato y topología

La inspección histórica previa era del 09/11, en la
[base común](../architecture/observability-baseline.md#consulta-de-prod--09112026):
NGINX, UI, tres JVM, dos PostgreSQL y storage local; no aparecían Redis, Asset ni
Azurite. La inspección actual del 19/11 confirma esa topología. El bootstrap `swarm/prod-release.json`
es una selección histórica, no el inventario efectivo ni un candidato de aplicación
listo para promover.

[`config.prod-local.example.json`](../../observability/config.prod-local.example.json)
prepara sólo esas dependencias: dos bases con aliases existentes `snippets-db`/`permissions-db`, storage
local y capacidad de sus tres volúmenes. Redis es `null`; no se agrega infraestructura
de aplicación para justificar un monitor. Si el inventario efectivo cambió, revisar
el candidato antes de instalarlo. Asset reemplaza el probe local cuando sea el
proveedor seleccionado; Azurite se mide sólo si es su backend efectivo.

Se puede validar/renderizar el **colector genérico** localmente, sin credenciales,
Docker, conexión a PROD ni archivos de licencia:

```sh
python3 scripts/observability_config.py \
  --config observability/config.prod-local.example.json \
  --runtime-config /etc/snippet-observability/prod/config.json \
  --scripts-path /opt/snippet-observability/prod/probes \
  > /tmp/sni88-integrations-prod.json
```

Ese resultado tiene cinco integraciones y sólo referencias de secretos. No instala
el agente ni resuelve redes, montaje de volúmenes o transporte de muestras. Los
nombres de secretos coinciden con el contrato de los colectores, pero sus valores
y almacenamiento deben pertenecer a PROD; no copiar archivos de DEV.

## Por qué no se copia el runtime DEV

La separación agente de host/colector privado fue aprobada para DEV. Sus archivos
son deliberadamente específicos:

| Pieza | Configuración que exige revisión PROD |
| --- | --- |
| `observability/runtime/agent.compose.yaml` | VM, etiquetas, nombre/estado del agente y rutas `/dev/` |
| `collector.stack.yaml` | UID/GID del volumen real, nodo, redes, volúmenes, secretos y montajes; actualmente exige Redis |
| `dispatch.sh` y `swarm.sh` | Stack/colector DEV y alcance permitido; no seleccionar tareas de otro ambiente |
| `scripts/observability_runtime.py` | La entrada DEV conserva su rechazo de PROD; el renderer compartido se usa sólo desde el candidato PROD que comprueba su topología |
| `prepare/provision/start/verify_observability_dev.py` | Host, paths y operaciones DEV; no ejecutar en PROD ni reemplazar nombres con `sed` |
| `scripts/observability_deployment.py` | Compatibilidad de CD verificada sólo con el marcador DEV; PROD necesita reconciliación equivalente antes de instalar aliases/ACL |

Se reutiliza el renderer genérico y los binarios fijados, conservando el rechazo de
un despliegue no revisado. La alternativa de convertir todos los instaladores DEV en flags reduciría
duplicación, pero ampliaría el alcance de operaciones que hoy sólo están verificadas
en DEV. Se comparte el renderer puro y se agrega una entrada PROD restringida al
inventario comprobado; los instaladores operativos DEV conservan sus barreras.
Es análisis del proyecto con el marco de trade-offs/decisiones de los capítulos
2/21 del [índice de Fundamentals of Software Architecture, 2e](https://www.oreilly.com/library/view/fundamentals-of-software/9781098175504/),
no una prescripción de tecnología atribuida al libro.

## Bundle público para revisión

[`production_observability_candidate.py`](../../scripts/production_observability_candidate.py)
produce un candidato offline, sin ejecutar Docker, conceder permisos ni leer una
licencia. Genera configuración del agente, stack del colector, dispatcher privado
PROD y seis integraciones (dos bases, tres probes de storage/disco y Swarm).
Rechaza DEV, Redis, Asset y destinos que no coincidan con el inventario. No copia
el runtime ni modifica el release de aplicación.

```sh
python3 scripts/production_observability_candidate.py > /tmp/sni88-prod-candidate.json
```

El colector tiene UID/GID 10001, filesystem raíz de lectura, capacidades eliminadas,
sin socket Docker, licencia ni puertos publicados. Sólo monta los dos secretos de
monitoreo PostgreSQL; las bases se observan en lectura. El volumen de contenido es
escribible únicamente para comprobar el fixture acotado del probe existente.
El agente de host requiere privilegios y socket Docker, con acceso efectivo alto
al host: `/:ro` no elimina ese riesgo. La separación deja las credenciales de base
fuera del agente, pero no lo vuelve una frontera frente a un administrador del host.
Debe revisarse y autorizarse esa instalación antes de aplicarla.

Los topes 384/256 MiB y 0.5 CPU por contenedor provienen del piloto; no son consumo
PROD medido. Tampoco hay roles, secretos, binarios, recepción o licencia instalados
por emitir este JSON. Su estado explícito es `REVIEW_ONLY_NOT_APPLIED`.
Validaciones locales: **309 tests**, `docker compose config --quiet` del agente y
`docker stack config` del colector correctos. Son validaciones de configuración,
no recepción de telemetría ni pruebas contra las bases de PROD.

Los cuatro callers de `main` consultados el 20/11 UTC usan **v0.6.2**, compatible
con el gate actual de PROD sin Redis. No hay un bloqueo de versión comprobado allí;
revalidar al promover. La VM se dejó **Detenida (desasignada)** después del inventario.

## Secuencia de promoción y aceptación

1. Obtener la evidencia de SNI-87, incluyendo los tres ensayos principales y aviso
   recibido. Recoger de SNI-81/83/85/86 las señales, consultas, SLO y condiciones
   efectivas; una clave de ingesta no permite administrar esos recursos.
2. Acordar la ventana y registrar operador, receptor del aviso y recuperación por
   Azure. Encender sólo la VM necesaria; consultar release confirmado y candidatos
   mediante el procedimiento de [CD](../sni-25-cd.md). No reaplicar el bootstrap.
3. Inventariar tareas/imágenes, redes, volúmenes/UID, flags efectivos de storage,
   identidad y workers, agente existente y credenciales de monitor. Usar campos
   seleccionados: no guardar `docker inspect`, release o environment completos.
   La lectura `docker service ls --format '{{.Name}} {{.Replicas}} {{.Image}}'`
   sirve para tareas, no prueba operaciones de negocio.
4. Preparar el bundle PROD con paths, nombres y etiquetas propios; comprobar CD y
   restauración antes de aplicar aliases o ACL. Reusar permisos mínimos de SNI-82,
   sin publicar puertos, cambiar propietarios de contenido ni rotar secretos previos.
5. Instalar/verificar host y dependencias; configurar APM/JDBC y logs con los
   artefactos de SNI-80/81. Después Browser/check funcional, dashboards, SLO y alertas
   de SNI-85/86 con identidad PROD. No deducir cobertura total de una muestra Flex.
6. Probar acceso al fixture funcional con la identidad PROD; registrar consultas y
   rango UTC, versiones/digests, traza real de alta, logs y un aviso recibido con
   recuperación. OAuth PROD no se acredita con el laboratorio local SNI-74; revisar
   issuer/audience/callback/directorio y conservación de IDs antes de activarlo.
7. Registrar CPU/RAM sostenidos y volumen de ingesta por fuente/ambiente frente al
   presupuesto de SNI-79. Los topes 384/256 MiB de DEV no son consumo medido ni sizing
   aprobado para PROD. Contrastar una sola ruta de ingesta por señal.
8. Si falla, retirar sólo el agente/colector nuevo y recuperar las especificaciones
   registradas, conservando datos y releases de aplicación. No usar `down -v`, poda,
   rollback genérico ni borrado de roles que otros consumidores usen. Al terminar,
   desasignar las VMs que se encendieron para la sesión.

## Qué falta para Done

No están acreditados recepción PROD, APM/logs, synthetic autenticado, dashboards,
SLO, canal ni aviso PROD. Tampoco está aprobada su adaptación operativa/CD. El
render local acredita sólo estructura, separación de destinos y ausencia de valores
de credenciales. La evidencia de SNI-87 y una revisión del inventario PROD son los
siguientes insumos, no resultados sustituidos por esta preparación.
