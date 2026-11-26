# Despliegues y recuperación

[Inicio](../README.md) · [Operación de infraestructura](operations.md) ·
[Workflows compartidos](https://github.com/JJT-INGSIS/github-workflows/blob/main/README.md)

## Publicación y promoción

Los cuatro callers (Snippets, Permissions, PrintScript y UI) ejecutan CI y
publican imágenes en GHCR desde DEV. El CD instala por digest. Con
`CD_ENABLED=true` puede desplegar DEV. Para promover a PROD también se requiere
`PROD_DEPLOY_ENABLED=true` y un merge autorizado de `dev` a `main`. Usá los
GitHub Environments `dev` y `prod` con restricciones de rama, variables
`SSH_HOST`, `SSH_USER`, `SSH_PORT` y secretos `SSH_PRIVATE_KEY` y `SSH_KNOWN_HOSTS`.
Confirmá las protecciones de rama antes de habilitar PROD.

1. El pipeline de DEV construye, publica y despliega la imagen. Después de
   verificarla en Swarm, registra un GitHub Deployment explícito
   (`task=sni25:verified`) con commit, árbol Git, digest y run/intento del build
   y la verificación.
2. En `main`, CD busca evidencia histórica del **mismo árbol Git completo**.
   Verifica procedencia e identidad del workflow, metadata e imagen en GHCR.
   Una promoción usa ese digest. Cambiar incluso documentación o workflows
   modifica el árbol y requiere verificar el contenido en DEV.
3. El runner envía el pedido por SSH verificado. La VM vuelve a validar
   autorización y evidencia bajo el lock y actualiza solo la aplicación
   objetivo. Para promover, PROD debe estar encendido. La evidencia histórica
   permite que DEV haya avanzado o esté apagado.

[`cd_evidence.py`](../scripts/cd_evidence.py) prepara y registra la evidencia.
[`github_cd.py`](../scripts/github_cd.py) valida procedencia y ramas.
[`ssh_deploy.py`](../scripts/ssh_deploy.py) transporta el pedido y recupera
el recibo. [`deploy_service.py`](../scripts/deploy_service.py) verifica y
reconcilia la operación en la VM. El CD fija una revisión compatible de Infra.
Antes de cambiar un overlay o el formato del registro, revisá esa revisión y
los callers de ambos ambientes.

Una imagen publicada o un Deployment genérico de GitHub Environments no
acreditan el despliegue. Si el servicio quedó sano y falla el registro de
evidencia, reejecutá los jobs fallidos autorizados y conservá el digest. PROD
requiere un recibo DEV verificado. Preservá la metadata de Actions y el artefacto
de GHCR que usa la selección histórica.

## Cambios al stack

[Swarm](../swarm/) combina un stack base con overlays de UI, ingress/TLS, Asset,
Redis, procesamiento, APM y observabilidad. La presencia de un overlay en Git
no indica que esté activo. Los JSON `swarm/*-release.json` son manifiestos de
bootstrap. El registro confirmado por ambiente en la VM y el estado de Swarm
permiten comprobar los digests y las opciones efectivas.

Para un cambio explícito de infraestructura, usá un checkout Linux fijo y
revisado en la VM. Verificá manager, estado saludable, secretos, volúmenes,
compatibilidad del CD y ausencia de pendiente. Prepará el candidato desde
el registro efectivo:

```bash
state="$HOME/.local/state/snippet-searcher/dev"
python3 -B scripts/bootstrap_swarm.py plan "$state/release.json" --config-version REVISION > candidate-dev.json
python3 -B scripts/bootstrap_swarm.py check candidate-dev.json
```

`REVISION` representa el número de una config de Swarm nueva cuando cambia su
contenido. Elegí las opciones reales con `bootstrap_swarm.py --help`. Para un
corte acotado, el comando admite `--proxy-only`, `--apm-only`, `--background-only`
y `--auth-only` según el cambio. Usá el mismo alcance al aplicar cuando corresponda.
Revisá el manifiesto, respaldá el registro y aplicá el candidato con
`sudo -n python3 -B scripts/bootstrap_swarm.py deploy candidate-dev.json --infrastructure`
y el selector acotado si lo elegiste. Un corte con alta inicial de UI en PROD
puede requerir el contexto de GitHub para probar su digest en DEV. Usá el registro,
hostname, secretos y contexto propios de cada ambiente.

La reaplicación conserva digests vigentes y proveedor de storage. Los cambios de
imagen se entregan por el CD de la aplicación. Para cambiar una política de Swarm,
reconciliá la definición del stack. Snippets y PrintScript usan `stop-first` para
evitar solapar coordinadores. Programá esa reconciliación en una ventana sin
ejecuciones activas. Verificá después `Spec.UpdateConfig.Order` en ambos servicios.

## Diagnóstico y recuperación

El estado se guarda en `~/.local/state/snippet-searcher/<dev|prod>/`:

| Archivo o carpeta | Uso |
| --- | --- |
| `deploy.lock` | Exclusión entre CD y operaciones de infraestructura |
| `release.json` | Configuración e imágenes confirmadas y último recibo |
| `pending.json` | Operación sin resolver |
| `operations/`, `history/` y `logs/` | Journal, recibos históricos y diagnóstico |

Ante SSH interrumpido, consultá el journal y el stack. Reintentá la misma
operación autorizada para que se reconcilie. Conservá el pendiente para que el
runner pueda confirmar un candidato sano o restaurar la versión anterior.
Usá `docker service ps --no-trunc` para inspeccionar convergencia. Si aparece
una imagen o config ajena al candidato y a la referencia anterior, frená e
identificá el cambio antes de continuar.

Un rollback sano conserva en rojo el despliegue que falló. Si la recuperación
falla, queda un pendiente y el registro indica que el estado no está sano.
Los verificadores comprueban digests, estabilidad, réplicas, healthchecks y las
dependencias internas pertinentes. Para un cambio de ingreso, verificá aparte
DNS/TLS y acceso desde navegador. Para el formato, login y otras funciones,
repetí los casos de aceptación del servicio afectado.

La evidencia JDBC/Flyway de Snippets se busca en los logs retenidos del
contenedor que está ejecutándose. Limitarla a las últimas 200 líneas daba un
falso fallo después de suficiente tráfico; consultar logs del servicio completo
también podría aceptar evidencia de una tarea anterior. Se conservan los
controles SQL de migraciones y salud. Si Docker ya rotó toda la evidencia de
arranque, la verificación sigue fallando explícitamente: no se omite el control.
