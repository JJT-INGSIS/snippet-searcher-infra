# SNI-72 — Configuración de autenticación de la API

La implementación de Snippets y sus pruebas se documentan en
[authentication.md](https://github.com/JJT-INGSIS/snippets-service/blob/dev/docs/authentication.md).
El [contrato SNI-71](authentication-authorization-contract.md) sigue definiendo
identidad, transporte y separación por ambiente. Auth0 administra credenciales;
Snippets verifica JWT con claves públicas, sin client secret ni tabla de passwords.

## Preparación local

Compose admite `AUTH_MODE`, `AUTH_ISSUER`, `AUTH_AUDIENCE` y
`SNIPPETS_CORS_ALLOWED_ORIGINS`. `.env.example` documenta sus valores vacíos y modo
dev actual. Para una comprobación local auth0, usar issuer y audience DEV de
`auth0/development.public.json`; la UI debe enviar access token. No confundir el
domain sin esquema de la UI con el issuer HTTPS completo y slash final del backend.

## Swarm y despliegues independientes

Los parámetros públicos de API se preparan como metadata opcional `auth` de un
registro de release v2; no se leen del entorno mutable del runner de CD:

```json
{
  "auth": {
    "mode": "auth0",
    "issuer": "https://jjt-snippet-searcher.us.auth0.com/",
    "audience": "https://jjt-snippets-dev.duckdns.org/api"
  }
}
```

Este fragmento ilustra la sección de un registro completo; no es un manifiesto
desplegable. No se agrega a los registros DEV/PROD existentes en este ticket.

Sin sección auth se conserva el comportamiento previo: dev en DEV y disabled en
PROD. El render aislado de `stack.yaml` sin registro falla cerrado con disabled;
las herramientas normales obtienen el modo del registro validado. Se rechazan
modo dev en PROD, issuer/audience incompletos en auth0 y campos no previstos,
incluidos secretos. Estos valores sólo llegan a Snippets.

Actualizar la imagen de un servicio conserva la sección auth. Reaplicar un
registro sin auth también conserva la elección ya confirmada. Un cambio explícito
de infraestructura puede registrar una nueva elección preservando imágenes y
datos. La verificación efectiva detecta una configuración de autenticación
distinta de la registrada; para registros antiguos admite tareas todavía sin
variables AUTH_*.

## Activación posterior

Integrar estos archivos no activa Auth0. Antes del corte DEV se necesita:

1. SNI-73 listo para emitir bearer en HTTP/NDJSON y manejar reautenticación.
2. Publicar y consumir un bundle/CD con estas versiones de `stack_release.py`,
   `stack_runtime.py` y `stack.yaml`, verificando los callers y SHA fijados. Un
   runner antiguo no conoce la nueva metadata: no habilitar auth0 hasta actualizarlo.
3. Revisar un registro candidato completo con auth y las imágenes actuales,
   aislamiento externo de Permissions/PrintScript, audience y URLs correctas.
4. Obtener aprobación específica para la operación remota y aplicar con el
   procedimiento existente de cambio explícito de infraestructura (`--infrastructure`).
5. Verificar login/API y reautenticación reales, permisos y ausencia de bypass
   por header dev. El directorio y la aceptación integral pertenecen a SNI-74.

No modificar variables mediante `docker service update` por fuera del registro:
el siguiente CD las reemplazaría. No editar archivos de estado ni tablas para
activar el modo. Este ticket no cambia workflows fijados, imágenes, datos,
usuarios del tenant ni configuración remota. No habilita PROD.

La preparación sigue el plan de SNI-72 aprobado por el usuario el 08/11/2026.
Frente a parámetros efímeros del runner se conserva configuración pública durable
por ambiente; el costo aceptado es actualizar el bundle antes de la activación.

## Comprobaciones

Las pruebas `test_auth_configuration.py` verifican rechazo de configuración
inválida, valores heredados, conservación en despliegues independientes y render
desde el registro frente al entorno del runner. Ejecutar además las regresiones
Python completas y los validadores locales Compose/Swarm existentes. No requieren
credenciales Auth0 ni conexión con VMs para estas comprobaciones.

Verificación local del 08/11/2026: 211 pruebas Python aprobadas en Linux aislado
sin red, socket Docker ni credenciales; validadores Compose/Swarm, Asset, NGINX,
stack ampliado y Redis aprobados. También se renderizó modo auth0 en ambos
ambientes, comprobando que sus parámetros sólo llegan a Snippets. No se desplegó.
