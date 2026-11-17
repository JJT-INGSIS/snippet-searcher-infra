# SNI-74 — Activación Auth0 de DEV

**DEV activado y login público verificado — 17/11/2026.**
La [evidencia](evidence/sni74-auth0-dev-2026-11-17.json) registra el corte confirmado
a las 23:21:57 UTC, ingreso real por Auth0/Google, callback a la URL pública y dos
GET autenticados de `/api/snippets` con 200. API sin token o con header dev forjado:
401 Bearer. Los nueve servicios permanecieron 1/1; APM, secretos montados, agentes
y especificaciones ajenas a Snippets/UI se conservaron. No hubo journal pendiente.

Thiago autorizó la ventana después de las pruebas de Juanchi y preparar el cambio
propio al no estar disponible la rama comunicada. También autorizó agregar sólo la
IP actual /32 a `AllowTeamWeb`, conservando las IPs previas y Synthetics. Los valores
de esas direcciones no se publican en la evidencia.

Se usaron las imágenes confirmadas y CD v0.6.6, sin migrar identidades/datos, activar
PROD, provisionar la M2M del directorio o encender workers. La aceptación local de
owner/lector/tercero se conserva separada en Snippets. DEV queda encendido para
continuar las pruebas del equipo; la aceptación PROD pertenece a SNI-88.

## Cambio y límites

El release conserva una sección `auth` para API y agrega `ui.auth` con `domain`,
`client_id` público y `audience`. Se validan completos, sin actor dev, sin secretos
y coherentes con issuer/audience de la API. El CORS de Snippets permite sólo la
origin HTTPS de NGINX registrada. Los valores salen de
[`development.public.json`](../auth0/development.public.json), no del entorno del runner.

`deploy --infrastructure --auth-only` usa el mecanismo acotado de `scoped_deploy.py`
para reemplazar exclusivamente Snippets y UI. Conserva imágenes, bases, storage,
Redis, NGINX, APM y agentes. El alcance queda en el diario persistente: un reintento
desde el CD recupera con ese mismo alcance y no reaplica el stack completo. Un
cambio ajeno a identidad o un estado de API desconocido se rechazan, sin sobrescribirlos.

Se eligió extender el despliegue parcial existente frente a reconciliar y reaplicar
todo el stack. Se reduce el alcance operativo y se preserva el monitoreo; el costo
es mantener validación/recuperación del alcance nuevo y publicar herramientas de CD
compatibles antes del corte. Marco de trade-offs y decisiones: capítulos 2/21 del
[índice de Fundamentals of Software Architecture, 2e](https://www.oreilly.com/library/view/fundamentals-of-software/9781098175504/).
La elección concreta es del proyecto, no una recomendación atribuida al libro.

El login no necesita la credencial Management del directorio. Su ausencia debe
afectar búsqueda/sharing explícitamente, no impedir entrar o consultar la API
autenticada. No se agregan permisos Auth0, usuarios, secretos de ingesta ni migraciones.
Los IDs dev y sus relaciones permanecen intactos: un usuario Auth0 no los hereda por email.

## Orden de publicación y corte

1. Integrar esta revisión de infra con CI verde.
2. Publicar el workflow central `v0.6.6`, fijando `INFRA_REVISION` al commit revisado
   que incluye UI Auth0, el bundle APM y verificación HTTP compatible. No mover tags
   existentes. Actualizar los cuatro callers y esperar sus checks/despliegues.
   El gate verifica el contenido fijado, los callers actuales y ausencia de runs activos.
3. Inspeccionar el release confirmado y la salud real de DEV, agentes/APM, alias,
   secreto de licencia y journal pendiente. Respaldar release/journal; no copiar
   environment ni valores de secretos a informes. Confirmar el alcance público de red.
4. Preparar desde ese registro real, sin usar los digests de bootstrap:

   ```sh
   python3 -B scripts/bootstrap_swarm.py plan \
     /home/azureuser/.local/state/snippet-searcher/dev/release.json \
     --auth0-dev > /home/azureuser/sni74-auth0-dev-candidate.json
   ```

5. Revisar que sólo cambien `auth` y `ui`, con mismas imágenes/APM/infra/storage.
   Aplicar como operador, con el usuario de estado correcto y el lock/journal habituales:

   ```sh
   sudo -n python3 -B scripts/bootstrap_swarm.py deploy \
     /home/azureuser/sni74-auth0-dev-candidate.json --infrastructure --auth-only
   ```

6. Verificar UI runtime `identity.mode=auth0`, `/api/languages` público y 401 con
   desafío Bearer para `/api/snippets` sin token o con header dev. Spring puede
   responder 401 vacío: no exigir un Problem Details donde el contrato no lo garantiza.
7. Abrir la URL pública HTTPS, completar login/callback y comprobar una consulta
   autenticada 200. Registrar fecha, versión y resultado sin JWT/código OAuth. No
   acreditar login por la pantalla de bienvenida o por un 401 aislado.
8. Contrastar APM/monitoreo, réplicas y licencias antes/después. Comunicar a Thiago
   que el login de DEV quedó disponible para SNI-85; no completar el ticket de Juanfran.
   Coordinar cuánto tiempo queda DEV encendido para su prueba; PROD queda fuera del corte.

## Verificación y recuperación

Suite: `uv run --no-project --python 3.12 python -B -m unittest discover -s scripts -p 'test_*.py'`.
Incluye rechazo de parámetros incompletos/mezclados, conservación de APM en el render,
alcance a dos servicios, 401 vacío válido y recuperación de UI/API mezcladas tras una
interrupción. La evidencia real de propietario/lector/tercero está en Snippets;
es aceptación local, separada de la aceptación pública DEV registrada arriba.

Ante corte incierto, inspeccionar y reconciliar la operación registrada. No ejecutar
un deploy genérico ni borrar `pending.json`. La recuperación usa el mismo alcance y
la identidad anterior, conservando imágenes/datos y APM. Un estado distinto de las
dos configuraciones conocidas requiere revisión humana.
