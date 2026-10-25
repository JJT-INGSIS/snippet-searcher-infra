# SNI-25 — Despliegue independiente por digest

> La [extensión SNI-43](sni-43-cd.md) conserva este protocolo de aplicaciones y
> amplía inventario/recuperación de infraestructura. Las notas de habilitación
> v0.4/v0.5 de abajo son históricas; el rollout nuevo requiere v0.6.0 y su SHA
> de infra revisado. No reutilizar herramientas v0.5.1 tras migrar a registro v2.

Los pipelines de cada servicio hacen CI y llaman al CD central. Dev construye una
imagen, la despliega y verifica; main selecciona ese mismo digest por igualdad
exacta del Git tree y lo despliega en prod. El merge de una PR dev → main autoriza
la promoción; no se agrega otro approval ni se reconstruye en producción.

## Habilitación e integración

Esta implementación queda **deshabilitada para despliegues remotos** hasta
completar la [integración central de SNI-25](https://github.com/JJT-INGSIS/github-workflows/blob/main/docs/sni-25-integration.md).
Los callers ya usan `v0.4.0`. Esta simplificación propone una versión nueva del
central (`v0.5.0`), sin modificar la publicada. Primero integrar estos scripts y
sustituir `REPLACE_WITH_SIMPLIFIED_INFRA_COMMIT` del nuevo CD por el SHA completo
del commit revisado de infra; después probar y versionar el central. No admite
una rama ni una revisión arbitraria elegida por el consumidor. La revisión anterior
de infra no implementa los nuevos comandos del runner.

Requisitos operativos:

- Bootstrap SNI-24 confirmado en la VM del ambiente a probar, con `release.json` y sus checks pasados.
- VM Ubuntu 24.04 x64 encendida para ese ambiente, manager `vm-snippet-dev` / `vm-snippet-prod`.
- Las tres imágenes públicas en GHCR, incluyendo linux/amd64. No se agrega un PAT a las VMs.
- Clave dedicada a CD autorizada para `azureuser`, `sudo -n` y acceso SSH desde el runner.
- En cada servicio, environments `dev` limitado a dev y `prod` limitado a main;
  variables `SSH_HOST`, `SSH_USER`, `SSH_PORT` y secretos `SSH_PRIVATE_KEY`, `SSH_KNOWN_HOSTS`.
- Variable de repositorio `CD_ENABLED=true` para habilitar el despliegue en dev.
- **Antes de definir `PROD_DEPLOY_ENABLED=true`**, comprobar en los tres repos:
  main exige PR, CI y base actualizada; las reglas aplican a administradores,
  no hay bypass de pushes directos ni force pushes. Registrar esa comprobación.

La API administrativa devolvió 403. En el navegador el 13/10/2026 se activó y se
verificó el guardado de **Do not allow bypassing the above settings** en main de
los tres servicios. Exigen PR, CI y base actualizada también a administradores,
sin bypass específico de PR ni force push. Producción no se habilitó: faltan
integración, credenciales y pruebas reales. El script comprueba además que main
continúe protegida y que el commit objetivo sea el merge de una PR de dev del
mismo repositorio. La marca `protected` por sí sola no reemplaza la revisión de
las reglas y sus excepciones.

GitHub Environments y perfiles Spring son configuraciones diferentes. Las
contraseñas y el perfil de runtime permanecen en el stack de SNI-24; los secretos
de dependencias Gradle se usan únicamente durante el build.

El acceso, usuario `azureuser`, puerto 22 y autorización de públicas están en
[SNI-20](sni-20-acceso-vms.md). Consultar también el
[bootstrap SNI-24](sni-24-bootstrap.md) y su [evidencia](sni-24-evidencia.md).

## Responsabilidades y contrato del runner

| Archivo | Responsabilidad |
| --- | --- |
| `cd_evidence.py` | Metadata de build, descriptor entre jobs, preparación del pedido, registro y resumen |
| `github_cd.py` | Cliente GitHub, evidencia histórica, identidad compartida y autorización de rama |
| `ssh_deploy.py` | SSH estricto, envío del bundle/token, reintento y descarga del journal |
| `deploy_service.py` | Lock de VM, actualización independiente, reconciliación y rollback |

`cd.yml` conserva solamente `publish`, `select` y `deploy`. Cada productor exporta
un descriptor JSON interno `artifact` con `image-ref`, `source-sha`, `source-tree`,
`build-run-id` y `build-run-attempt`. No es un archivo de Actions ni evidencia de
verificación: es el transporte entre jobs. No se repite en outputs del workflow.

Comandos utilizados por el YAML:

| Comando | Resultado |
| --- | --- |
| `cd_evidence.py source` | Validar checkout/paquete/plataformas y exportar imagen, árbol y scope de caché |
| `cd_evidence.py published` | Exportar el descriptor del digest dev construido |
| `cd_evidence.py select` | Exportar el descriptor con evidencia histórica del árbol exacto de main |
| `cd_evidence.py prepare request.json` | Validar descriptor, inspeccionar imagen/etiquetas y escribir el pedido |
| `ssh_deploy.py request.json receipt.json` | Ejecutar en VM y recuperar su recibo durable |
| `cd_evidence.py record receipt.json` | Registrar solamente un recibo dev verificado |
| `cd_evidence.py summary receipt.json` | Mostrar el recibo o indicar que no hay confirmación |

La inspección de imagen se ejecuta una vez en el runner, al preparar el pedido.
El run/attempt del build permanece en el descriptor al reintentar un job fallido;
el pedido añade el run/attempt actual de verificación. Un reintento no atribuye
la imagen a una construcción nueva. Las comprobaciones de autorización sobre la
rama vigente se ejecutan en la VM, dentro del lock.

## Operación en la VM

`scripts/deploy_service.py` recibe por stdin un objeto `request` y un token efímero
de Actions para verificar autorización. El token no se escribe en archivos ni se
incluye en argumentos del proceso. Los scripts revisados se copian a
`~/.local/share/snippet-searcher/cd/<infra-SHA>/scripts`.

Dentro del mismo `deploy.lock` usado por el bootstrap:

1. Reconciliar primero cualquier operación interrumpida.
2. Validar manager, ambiente, servicio, repositorio y referencia por digest.
3. Rechazar runs anteriores y comprobar que el commit siga siendo la punta autorizada;
   en prod, comprobar también la evidencia histórica del digest antes de modificar Swarm.
4. Comparar las cinco imágenes reales con el registro y verificar la versión anterior.
5. Descargar la imagen y revalidar autorización después de las comprobaciones lentas.
6. Persistir la operación pendiente antes de ejecutar `docker service update --image`.
7. Actualizar **una aplicación**, esperar convergencia y verificar el stack.
8. Registrar atómicamente el resultado, conservando las otras imágenes y PostgreSQL.

El CD no llama a `validate_promotion()` del bootstrap, que compara el stack
completo. Permissions y PrintScript pueden conservar en prod digests diferentes
de dev al promover Snippets. Se verifica el conjunto en ejecución para detectar
incompatibilidades, sin actualizar esas otras aplicaciones.

La reaplicación del bootstrap conserva las referencias vigentes y los recibos de
CD. Si existe una operación pendiente, rechaza la reaplicación antes de modificar
el stack. No debe usarse el bootstrap para eludir una promoción rechazada por CD.

## Estado y recuperación tras perder SSH

Estado por ambiente en `~/.local/state/snippet-searcher/<dev|prod>/`:

| Archivo | Responsabilidad |
| --- | --- |
| `deploy.lock` | Exclusión entre aplicaciones y bootstrap |
| `release.json` | Imágenes vigentes, checks y último recibo por servicio |
| `pending.json` | Identidad de la operación todavía sin resolver |
| `operations/<servicio>-<run>-<attempt>.json` | Pedido, versión anterior, candidata y resultado |
| `history/sni25-<identidad>.json` | Registro confirmado de esa operación |
| `logs/<identidad>.log` | Diagnóstico remoto sin depender de la conexión SSH |

Se usan archivos privados y escritura atómica. El journal se confirma antes del
registro global; si el proceso se interrumpe entre ambos, se comprueba el estado
real y se completa el registro sin volver a enviar la actualización.

Una desconexión SSH tiene resultado incierto. El proceso ignora SIGHUP y conserva
la salida en la VM. El transporte reintenta **el mismo pedido e identidad** una
vez ante pérdida de conexión. Bajo el lock, el diario determina si la actualización
fue aceptada, si quedó la imagen anterior o si ya se verificó. No se presupone que
el servicio se haya caído porque el cliente perdió la respuesta.

- Candidata ejecutándose y verificada: confirmar el éxito.
- Candidata fallida: restaurar el digest anterior verificado y comprobarlo.
- Swarm ya hizo rollback: verificar la versión recuperada sin otra actualización.
- Swarm está en `rollback_started` hacia el digest esperado: esperar la
  convergencia y el período de estabilidad. Ese estado no confirma todavía la
  recuperación. Si se esperaba la candidata y Swarm volvió a otra imagen, la
  comprobación del digest rechaza la candidata; `rollback_paused` sigue siendo
  un fallo.
- Recuperación fallida: conservar el pendiente y marcar el registro como no saludable.
- Imagen externa inesperada: detenerse y pedir intervención; no sobrescribirla.

Una recuperación correcta **mantiene la Action en rojo**. Un nuevo intento puede
verificar el mismo digest sin reconstruir ni reiniciar innecesariamente la aplicación.
Si otra ejecución ya reemplazó la imagen, un reintento viejo no puede volver a instalarla.
El journal es la única fuente del recibo: no se duplica en stdout de SSH. El runner
conserva también un recibo de recuperación para el resumen, pero no lo registra como
evidencia de un despliegue exitoso.

Para diagnosticar, en la VM del ambiente:

```bash
state="$HOME/.local/state/snippet-searcher/dev" # usar prod cuando corresponda
cat "$state/release.json"
test ! -f "$state/pending.json" || cat "$state/pending.json"
ls "$state/operations" "$state/logs"
docker service ps --no-trunc snippet-searcher-dev_snippets-service
```

No borrar `pending.json` ni corregir manualmente `release.json` para desbloquear
un despliegue. Reejecutar el job de despliegue fallido para reconciliar. Si la rama
avanzó, la nueva ejecución primero resuelve el pendiente y después verifica su
propia autorización. Ante un cambio externo, Thiago debe resolver el estado real
y documentarlo antes de continuar.

El equivalente manual desde un runner Linux con el checkout **fijo de infra**, el
pedido JSON obtenido de Actions y las mismas variables/secrets es:

```bash
python3 scripts/ssh_deploy.py request.json receipt.json
# Solo para un recibo dev verificado, con el token y contexto de Actions originales:
python3 scripts/cd_evidence.py record receipt.json
```

Estos comandos no evitan los controles de rama, identidad, protección ni Git tree.
`GH_TOKEN` viaja por stdin a la VM. No pegarlo en el pedido JSON, logs ni argumentos.

## Evidencia histórica y promoción

Después de una verificación dev exitosa, Actions crea un GitHub Deployment
`task=sni25:verified`, `environment=dev`. Su payload guarda servicio, repositorio,
commit, Git tree, digest, run/attempt de construcción y verificación, checks y
resultado real. Se usa `auto_merge=false`; el estado se registra con
`auto_inactive=false`. Repetir el registro del mismo recibo no duplica el Deployment.

La selección consulta **todas las páginas**, no solo el Deployment más reciente.
Requiere payload verificado del bot de Actions, imagen y servicio correctos,
Git tree comprobado contra el commit real y run/attempt concluido exitosamente
en dev. También exige que el run haya ejecutado el pipeline y el CD centrales de
la misma revisión inmutable. Antes de SSH, la preparación inspecciona el digest
descargado y las etiquetas de repositorio, commit, árbol y run/attempt de construcción.
En la VM se confirma de nuevo la evidencia de ese digest bajo el lock, además de
revalidar la autorización actual antes de la actualización.

Los Deployments genéricos creados por GitHub Environments no cuentan como
evidencia. Un estado posterior `inactive` no invalida el recibo explícito. No se
consulta el historial de estados, los logs ni artefactos temporales de Actions
para recuperar la prueba histórica. Sí se necesita conservar la metadata del
run/attempt, el commit y la imagen en GHCR: si se eliminan o no pueden consultarse,
la promoción falla; no se elige una imagen aproximada.

Dev puede avanzar o su VM estar apagada al promover. Se utiliza la prueba
histórica del contenido exacto, no el estado actual de la VM de dev. La VM de prod
sí tiene que estar encendida.

Si el registro de evidencia falla después de un despliegue saludable, no se
revierte una aplicación sana: la Action falla y prod no puede promoverla todavía.
Reejecutar los jobs fallidos conserva el digest y el intento original de build,
vuelve a verificar el servicio y registra un recibo del nuevo intento.

El modelo de confianza incluye las reglas de las ramas y la revisión de workflows:
el payload no es una firma criptográfica. Un Git tree igual exige igualdad de
**todo** el repositorio, incluyendo README y workflows. Ante una diferencia,
integrar ese contenido en dev, verificarlo allí y recién promoverlo.

## Verificaciones y límites

Se reutilizan los verificadores SNI-24: cinco digests y réplicas convergentes,
estabilidad de 60 segundos, healthchecks, SQL autenticado, migraciones, permisos
del volumen de contenido y HTTP desde la red interna. Dev crea datos de prueba;
prod usa las comprobaciones existentes sin escrituras de prueba.

El lock se comparte entre servicios. Actions serializa además por servicio y
ambiente con `cancel-in-progress=false`. La obsolescencia se comprueba dentro del
lock y antes de actualizar. El job tiene un límite de 90 minutos; un timeout o
cancelación no demuestra el estado final de la VM: consultar el diario.

El rollback de imagen **no revierte datos ni migraciones**. Los cambios de esquema
y contratos HTTP deben seguir siendo compatibles con la versión anterior durante
la ventana de recuperación. Un cambio incompatible requiere plan coordinado antes
del merge. No se agregan recursos Azure ni encendido automático: una VM apagada
produce un fallo de conexión claro.

## Pruebas

```bash
python3 -B -m unittest discover -s scripts -p 'test_*.py' -v
python3 scripts/validate_stack.py
docker compose config --quiet
```

Las pruebas de journal, evidencia y transporte usan adaptadores simulados; la
exclusión `flock` se comprueba con procesos Linux reales. No prueban un despliegue
real en Swarm. El CI usa valores ficticios para validar Compose y no necesita claves.

Para cerrar SNI-25 quedan las verificaciones en GitHub/VMs:

- Mantener la protección de main verificada el 13/10/2026, sin bypass de pushes directos.
- Propagación de secrets/environment hasta el job final de la cadena reutilizable.
- Dev: construir → publicar → desplegar → verificar → registrar evidencia, primero Snippets.
- Prod: PR dev → main, SHA diferente/árbol idéntico, mismo digest, sin build.
- Árbol sin prueba, Deployment genérico, CI fallido y ejecución obsoleta: rechazo.
- Recuperación controlada en dev, preservando datos y las otras imágenes; Action roja.
- Corte SSH real durante actualización/verificación y después de confirmar: reconciliar sin duplicar.
- Recuperación de evidencia histórica después de que dev avance; sin logs/artefactos ni VM dev.
- Registro de GitHub temporalmente fallido y reintento de jobs fallidos sin reconstruir.
- VMs apagadas: fallo visible, sin encendido ni permisos Azure nuevos.
