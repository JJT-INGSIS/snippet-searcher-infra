# SNI-25 — Despliegue independiente por digest

Los pipelines de cada servicio hacen CI y llaman al CD central. Dev construye una
imagen, la despliega y verifica; main selecciona ese mismo digest por igualdad
exacta del Git tree y lo despliega en prod. El merge de una PR dev → main autoriza
la promoción; no se agrega otro approval ni se reconstruye en producción.

## Habilitación e integración

Esta implementación queda **deshabilitada para despliegues remotos** hasta
completar la [integración central de SNI-25](https://github.com/JJT-INGSIS/github-workflows/blob/main/docs/sni-25-integration.md).
Los callers preparados apuntan al futuro `v0.4.0`; no integrarlos antes de publicar
y comprobar esa versión. El CD contiene `REPLACE_WITH_SNI25_INFRA_COMMIT`: sustituirlo
por el SHA completo del commit revisado que integre estos scripts. No admite una
rama ni una revisión arbitraria elegida por el consumidor.

Requisitos operativos:

- Bootstrap SNI-24 confirmado en ambas VMs, con `release.json` y sus checks pasados.
- VMs Ubuntu 24.04 x64 encendidas, managers `vm-snippet-dev` / `vm-snippet-prod`.
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

## Operación en la VM

`scripts/deploy_service.py` recibe por stdin un objeto `request` y un token efímero
de Actions para verificar autorización. El token no se escribe en archivos ni se
incluye en argumentos del proceso. Los scripts revisados se copian a
`~/.local/share/snippet-searcher/cd/<infra-SHA>/scripts`.

Dentro del mismo `deploy.lock` usado por el bootstrap:

1. Reconciliar primero cualquier operación interrumpida.
2. Validar manager, ambiente, servicio, repositorio y referencia por digest.
3. Rechazar runs anteriores y comprobar que el commit siga siendo la punta autorizada.
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
- Recuperación fallida: conservar el pendiente y marcar el registro como no saludable.
- Imagen externa inesperada: detenerse y pedir intervención; no sobrescribirla.

Una recuperación correcta **mantiene la Action en rojo**. Un nuevo intento puede
verificar el mismo digest sin reconstruir ni reiniciar innecesariamente la aplicación.
Si otra ejecución ya reemplazó la imagen, un reintento viejo no puede volver a instalarla.

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
la misma revisión inmutable. Inspecciona el digest descargado y las etiquetas de
repositorio, commit, árbol y run/attempt de construcción.

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
