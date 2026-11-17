# SNI-88 — Preparación de cobertura PROD

Estado al 17/11/2026: **PREPARACIÓN, NO DESPLEGADO**. SNI-87 aún no acredita
alerta/aviso/recuperación y SNI-86 sigue Todo. Este documento no habilita el corte
ni presenta el piloto DEV como recepción PROD.
Resultados y brechas: [registro de preparación](../evidence/sni88-preparation-2026-11-17.json).

## Candidato y topología

La última inspección de PROD registrada es del 09/11, en la
[base común](../architecture/observability-baseline.md#consulta-de-prod--09112026):
NGINX, UI, tres JVM, dos PostgreSQL y storage local; no aparecían Redis, Asset ni
Azurite. No se encendió PROD para esta revisión. El bootstrap `swarm/prod-release.json`
es una selección histórica, no el inventario efectivo ni un candidato de aplicación
listo para promover.

[`config.prod-local.example.json`](../../observability/config.prod-local.example.json)
prepara sólo esas dependencias: dos bases con alias privados `prod-*`, storage
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
| `scripts/observability_runtime.py` | Rechaza PROD expresamente; sus labels no son parametrizables por el ejemplo |
| `prepare/provision/start/verify_observability_dev.py` | Host, paths y operaciones DEV; no ejecutar en PROD ni reemplazar nombres con `sed` |
| `scripts/observability_deployment.py` | Compatibilidad de CD verificada sólo con el marcador DEV; PROD necesita reconciliación equivalente antes de instalar aliases/ACL |

Se reutiliza el renderer genérico y los binarios fijados, conservando el rechazo de
un despliegue no revisado. La alternativa de convertir todo en flags ahora reduciría
duplicación, pero permitiría generar una instalación para una topología que todavía
no comprobamos. Se acepta terminar la adaptación operativa después del inventario.
Es análisis del proyecto con el marco de trade-offs/decisiones de los capítulos
2/21 del [índice de Fundamentals of Software Architecture, 2e](https://www.oreilly.com/library/view/fundamentals-of-software/9781098175504/),
no una prescripción de tecnología atribuida al libro.

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
