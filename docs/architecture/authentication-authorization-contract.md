# SNI-71 — Contrato de identidad para API, UI e infraestructura

Fecha: 07/11/2026. Base: apuntes de clase, documentación oficial y autorización
del usuario para implementar la preparación disponible antes de crear la cuenta.
Inventario contrastado con dev: Snippets `defce769`, UI `a8a77d11`, Permissions
`500331e2`, infra `51c21a2a`. No representa login real ya implementado.

## Alcance y decisiones

Auth0 administra credenciales, registro, Universal Login y sesión del proveedor.
React usa el SDK oficial con Authorization Code + PKCE. Snippets valida access
tokens RS256 con Spring Security Resource Server. Permissions sigue autorizando
ownership, lectura, modificación y sharing. No se agrega una tabla de contraseñas.

La petición del usuario «empezar a implementar lo que puedas» autoriza preparar
este contrato y el módulo Terraform según la propuesta presentada. No acredita
decisiones de la cátedra todavía desconocidas ni autorización para aplicar IaC,
migrar datos o desplegar. El usuario ya creó la cuenta y confirmó el tenant
`jjt-snippet-searcher.us.auth0.com`; su issuer esperado es
`https://jjt-snippet-searcher.us.auth0.com/`. Quedan pendientes conexión de usuarios,
credenciales de aprovisionamiento y configuración/aceptación reales de SPA y API.
El usuario confirmó la conexión Database `con_jLC4rpvsBwKOterd`, registrada como
entrada pública del módulo. Se verificó mediante lectura de Management API que
existe como `Username-Password-Authentication` con estrategia `auth0`; la futura
asociación a la SPA todavía no fue creada.
La aplicación M2M de aprovisionamiento fue creada por el usuario con Client ID
`exnEJpoD13bXQLHzWDBDQDLzaVmuD3Fe` (público). El secreto no se recibió por chat;
se ingresó localmente mediante el helper Windows. El 07/11/2026 se verificó el
intercambio de token y la consulta de lectura de aplicación/conexión. Los permisos
efectivos coinciden exactamente con los ocho del runbook, sin scopes extra. No se
guardaron tokens ni secretos en el informe; no se creó ni modificó recursos.
El registro
previo de propuestas y alternativas permanece en
[el plan](authentication-authorization-plan.md); este documento concreta la base
de implementación. La presentación se contrastará cuando se publique.

### Elecciones y costos

Decisión de ambientes confirmada por el usuario el 07/11/2026: usar **un tenant
compartido entre DEV y PROD** para reducir configuración y mantenimiento en este
proyecto académico. Alternativa descartada: tenants separados, con mayor aislamiento
y más administración. Se acepta que usuarios y ajustes globales del tenant pueden
afectar ambos ambientes; no se presenta esta decisión como aislamiento completo.

Se conservan una SPA y una API por ambiente, con clientIds, audiences y listas de
URLs separados. El issuer será común, pero cada backend validará su audience:
un token destinado a DEV no habilita PROD. Ownership, snippets y jobs permanecen
en las bases correspondientes de cada ambiente. Si comparten la misma conexión
de usuarios Auth0, comparten perfiles/credenciales y subjects, no los datos de negocio.

Revisar la separación en tenants si el proyecto incorpora usuarios reales,
necesidades de aislamiento adicionales o cambios globales incompatibles entre
ambientes. Este corte sigue preparando sólo recursos DEV en el tenant compartido;
no configura ni habilita PROD.

| Elección | Motivo y alternativa descartada | Costo / límite |
| --- | --- | --- |
| SDK React + Universal Login + PKCE | Flujo mantenido para una SPA; sin formularios de credenciales propios | Dependencia del proveedor y de su sesión; puede requerir interacción para obtener un token nuevo |
| Resource Server en Snippets | Autenticación en el borde actual, con autorización existente | Añadir configuración y pruebas de seguridad a cada ruta real |
| `sub` como actorId con un issuer permitido por ambiente | Compatible con los IDs TEXT actuales; email puede cambiar | Cambiar issuer o vincular cuentas requiere revisar correspondencias; no se unifican identidades de distintos tenants |
| Terraform para preparación Auth0 | Configuración revisable frente a cambios manuales o Deploy CLI | Estado y credenciales administrativos sensibles; operación serializada por un responsable |
| Sin refresh tokens en la primera preparación | No decidir aún rotación, duración y almacenamiento persistente | Al vencer la sesión puede requerirse redirección interactiva; no se promete renovación silenciosa incondicional |
| Directorio backend mediante Management API como adaptador previsto | Reemplazar catálogo dev sin duplicar perfiles; alternativa: índice local sincronizado | Requiere habilitar y probar credenciales de lectura y límites en SNI-74; no se configura ahora |

No se agregan scopes de negocio ni roles owner/reader a Auth0: los permisos por
snippet dependen del estado vigente de Permissions. La UI solicita `openid profile
email` para su sesión/perfil, y la audience de Snippets para el access token.
El backend no exige email/name dentro del access token. Datos del perfil sólo se
consumen como presentación; no autorizan una operación.

## Identidad y compatibilidad de datos

1. Spring valida firma/algoritmo, issuer exacto, audience y tiempos antes de
   construir un principal. La audience debe contener el identificador configurado
   de Snippets. Un ID token para la SPA no es una credencial de API.
2. Un subject no vacío de usuario del issuer permitido se convierte en actorId.
   No se acepta actor/owner del body, query o headers como identidad de la petición.
   Tokens de client credentials no son identidades de usuario para estas rutas.
3. `ActorContext`/`ActorIdentityResolver` deben extenderse en el borde de SNI-72
   para transportar la identidad ya validada, sin introducir Spring/JWT en los
   casos de uso ni consultar credenciales desde jobs.
4. Modo de identidad explícito: `disabled`, `dev` o `auth0`. `dev` sólo con perfil
   dev y actor explícito. En modo auth0, un token inválido o ausente jamás cae a
   `X-Dev-Actor-Id`, aunque el despliegue sea de desarrollo. Configuración auth0
   incompleta falla al arrancar; no degrada silenciosamente a dev/disabled.
5. No cambiar issuer dentro de un ambiente existente sin revisar la identidad.
   Si se admiten varios issuers en el futuro, resolver `(iss, sub)` de manera
   explícita; sub solo no es una clave global entre tenants.

### Lugares que conservan identidad

| Lugar existente | Impacto del cambio |
| --- | --- |
| `snippets.creation_actor_id`, `creation_key`, fingerprint | Preservar actor, payload y clave de creación; la clave es globalmente única, no convertirla en otra operación al cambiar usuario |
| Permissions: ownership y shares | Mantener IDs TEXT y comprobar la identidad autenticada en Snippets; creación registra al actor confirmado |
| Reglas de formato/lint por owner | Nuevas identidades tienen su propio ámbito; no adoptar reglas de un actor dev por email |
| Jobs, items, auditoría y sesiones de ejecución | Actor/ámbito internos durables; ningún bearer, refresh token o secreto en tablas, Redis o eventos |
| UI: `actorScope`, `CreationIntent`, QueryClient y `ExecutionSession` | Incorporar issuer/subject a la separación local de identidad; limpiar cachés y suscripciones al cambiar usuario |
| Directorio `ConfiguredUserDirectory` | Reemplazar con adaptador real en SNI-74; usar el mismo user ID/subject de Auth0, sin convertir email a ID |

Política inicial para datos dev: conservarlos intactos, con sus IDs actuales. Un
nuevo usuario Auth0 no hereda datos de `dev-*` por coincidencia de email o nombre.
Si se desea recuperarlos, preparar inventario y mapeo respaldado para TODAS las
referencias anteriores, comprobar colisiones/idempotencia y obtener autorización
específica antes de ejecutar. No se borra ni migra datos como efecto del login.

## Matriz de API

Rutas internas de Snippets; NGINX agrega `/api` externamente. `*` en esta tabla
agrupa familias para lectura; SNI-72 debe probar métodos y rutas exactos.

| Método y ruta existentes | Autenticación y autorización |
| --- | --- |
| GET `/languages` | Público, conservando el contrato actual |
| POST `/snippets` | Usuario; validar idempotencia y registrar ownership con el actor autenticado |
| GET `/snippets` | Usuario; listado limitado a sus relaciones de acceso |
| GET `/snippets/{id}` | Usuario; acceso de lectura. Descarga original usa el contenido del detalle, sin inventar un endpoint |
| PUT `/snippets/{id}` | Usuario; permiso de modificación |
| GET `/snippets/{id}/formatted` | Usuario; acceso de lectura y vigencia del derivado |
| PUT `/snippets/{id}/shares/{userId}` | Usuario; permiso de compartir y destinatario válido |
| GET `/users` | Usuario; búsqueda limitada y paginada del directorio autorizado |
| GET/PUT `/formatting-rules/{language}/{version}` | Usuario; ámbito de reglas del propio actor |
| GET/PUT `/linting-rules/{language}/{version}` | Usuario; ámbito de reglas del propio actor |
| GET/POST `/snippets/{id}/tests` | Usuario; lectura/modificación según operación |
| POST `/snippets/{id}/tests/{testId}/executions` | Usuario; permisos y capacidad vigentes, sin cambiar US9 |
| POST `/snippets/{id}/executions` | Usuario; permisos y capacidad vigentes, sin cambiar US10 |
| GET `/executions/{id}` y `/executions/{id}/events` | Usuario; comprobar acceso a la ejecución también al reconectar |
| POST `/executions/{id}/inputs` y `/executions/{id}/cancel` | Usuario; mantener autorización de operación de la sesión |
| GET `/snippets/{id}/automatic-tests` | Usuario; acceso al snippet y resultado vigente |
| GET `/jobs/{jobId}` | Usuario; ámbito del trabajo, permisos vigentes; trabajos globales de parser permanecen inaccesibles |

Conservar el healthcheck mínimo necesario para Docker; no abrir management ni
todos los endpoints Actuator. Preflight CORS válido se procesa sin bearer. El
resto de endpoints no se vuelve público por omisión de un matcher.

Credencial inválida/ausente: 401 con Bearer challenge, respuesta pequeña y sin
detalles internos. Para identidad válida mantener la política de 403/404 actual
según la operación, sin revelar recursos ajenos. Respetar respuestas de errores
existentes y no transformar un fallo de identidad en un éxito o un 500.

### Tráfico entre servicios

El navegador sólo llama a Snippets vía `/api`. NGINX no enruta escrituras de
Permissions. Antes de activar auth0 se verifica además que los puertos directos
de Permissions/PrintScript no permitan acceso externo y que la red interna sea
el límite de confianza vigente. Si ese aislamiento no puede acreditarse, debe
resolverse explícitamente antes de habilitar el modo, sin confiar en actorId del
cliente ni simplemente propagar su bearer.

La preparación no crea un sistema M2M para cada microservicio. Cualquier identidad
de servicio que se necesite se configura aparte con alcance mínimo; el token de
usuario no se envía a Permissions, PrintScript ni workers. El comando administrativo
del parser permanece interno y auditable, según SNI-70.

## Sesión, transporte e idempotencia

- Obtener el token mediante SDK al emitir cada petición protegida; no capturar
  un token único al construir Axios/fetch que después quede vencido. No adjuntar
  bearer a orígenes ajenos ni URLs de redirección arbitrarias.
- Usar el mismo proveedor de tokens para Axios y el fetch de eventos, inputs,
  cancelación y progreso. No enviar bearer en querystring ni persistirlo en logs.
- Si falla la obtención silenciosa con necesidad de login, mostrar estado de
  reautenticación conservando el borrador. No implementar un reintento infinito.
- Al cambiar de usuario/logout, cancelar solicitudes/suscripciones locales y
  limpiar datos privados de caché. No cancelar automáticamente una ejecución
  remota ni asumir que logout detiene PrintScript.
- No repetir mutaciones automáticamente ante 401. Una creación incierta retiene
  su key/actor/payload y sólo se retoma con el mismo actor; bajo otra identidad
  queda bloqueada hasta una acción explícita del usuario.
- Eventos NDJSON se autentican al abrir/reabrir la solicitud. Una conexión ya
  admitida puede terminar bajo los límites actuales; expirar el token no genera
  por sí solo cancelación remota. Cada nueva consulta/input/cancel exige token
  vigente y permisos actuales. No se introduce revocación instantánea de streams.
- Logout limpia el estado local y llama al SDK para cerrar sesión en Auth0; no
  promete cerrar sesiones externas como Google ni invalidar todos los JWT emitidos.
- `onRedirectCallback` acepta únicamente navegación interna validada. Callback
  definido para SNI-73: `/auth/callback`; retorno de logout: raíz `/`.

## Configuración compartida

El [módulo Auth0](../../auth0/README.md) prepara únicamente recursos dev. Produce
domain, issuer con slash final, clientId, audience, callbacks, logout URLs y origins.
No modifica automáticamente application.properties ni app-config.json.

| Parámetro | Dónde se usa | Sensibilidad |
| --- | --- | --- |
| domain/issuer | UI y backend; issuer se valida exactamente | Público |
| audience | Solicitud de access token y validación en Snippets | Público |
| clientId SPA | SDK React | Público |
| origins/callbacks/logout URLs | Auth0, runtime UI y CORS según su función | Público |
| Credencial de aprovisionamiento | Terraform local del responsable | Secreto, nunca UI/repositorio/logs |
| Credencial de lectura de directorio | Backend de SNI-74 | Secreto; todavía no creada |
| JWT/refresh token de usuario | SDK/memoria durante la sesión | Secreto; nunca job, evento, caché de negocio ni query key |

Para backend se propone `AUTH_DOMAIN`, `AUTH_AUDIENCE` y `AUTH_MODE`; en UI un
modo `auth0` con `domain`, `clientId`, `audience` en configuración runtime pública.
SNI-72/73 deben documentar las propiedades reales al implementarlas. La imagen
de UI continúa reusable, sin client secret y sin rebuild por ambiente.

## Entregas y aceptación

- SNI-72: principal validado y matriz real; pruebas de firma, issuer, audience,
  expiración, ID token, actor forjado, modo dev/auth0 y permisos owner/lector/tercero.
- SNI-73: callback/login/logout, autenticación en ambos transportes, expiración,
  cachés, creación incierta y ausencia de replay de mutaciones. Aceptación UI con
  proveedor real y API controlada mientras se termina SNI-72.
- SNI-74: adaptador Management API de sólo lectura con IDs coherentes, errores y
  límites; evidencia integrada de tres usuarios y ausencia de tokens en jobs.
  No exponer Management API ni su credencial al navegador.
- Infra: fmt/validate y pruebas mock del módulo; después del bootstrap, revisar
  un plan real contra el tenant y las URLs elegidos. Aplicación y recorrido real
  permanecen pendientes; presentación contrastada cuando esté disponible.

No afirmar aceptación completa de SNI-71/72/73/74 mientras falten sus entradas
reales. El usuario pidió avanzar antes de crear la cuenta: este corte entrega la
preparación verificable, no credenciales inventadas ni una certificación de login.

### Parámetros DEV confirmados y separación de UI PROD

El usuario aceptó completar el plan DEV con audience
`https://jjt-snippets-dev.duckdns.org/api`, access token de 900 segundos y origins
`http://127.0.0.1:5173` / `https://jjt-snippets-dev.duckdns.org`.
Ese TTL pertenece al access token; no define la duración de la sesión Auth0 ni
garantiza renovación silenciosa. Sin refresh grants, la obtención de un token
nuevo depende de la sesión del proveedor y de las restricciones del navegador;
SNI-73 debe manejar correctamente el caso que requiere interacción.

La UI PROD ya existe en `https://jjt-snippets-prod.duckdns.org`. Reutilizará el
tenant compartido, pero necesitará una SPA `snippet-searcher-prod-ui` y una API
`snippet-searcher-prod-api` distintas. Audience propuesta para esa API:
`https://jjt-snippets-prod.duckdns.org/api`; callbacks y retorno se derivarán de
su propia origin HTTPS, sin localhost ni URLs DEV. Estos recursos PROD no forman
parte del módulo/plan DEV actual y todavía no se han aprovisionado. SNI-72/73
requieren parámetros por ambiente, y no confunden acceso a la UI desplegada con
login Auth0 ya habilitado.

## Verificación de esta preparación — 07/11/2026

- Terraform 1.13.5 descargado de HashiCorp y verificado contra su SHA256 oficial.
- Proveedor Auth0 1.56.0 instalado con firma verificada; lockfile con checksums
  para Windows AMD64 y Linux AMD64.
- `fmt -check -recursive`, `validate` y cinco ejecuciones de `terraform test`
  con proveedor simulado: aprobadas. Se comprueban flujo de cliente público,
  callbacks/logout coherentes, firma asimétrica y rechazo de comodines, HTTP
  remoto, paths en origins y URL completa usada como domain.
- Workflow de CI preparado con las mismas comprobaciones sin secrets; actionlint
  fijado por digest aprobado localmente. El workflow remoto aún no se ejecutó.
- Estado, planes, parámetros locales y plugins quedan fuera de Git; el ejemplo
  público y el lockfile permanecen versionables.

Posteriormente, con la credencial ingresada localmente, se comprobaron los ocho
scopes y la existencia de aplicación administrativa/conexión. Las consultas de
lectura no encontraron SPA/API DEV duplicadas y se generó el plan real con los
parámetros DEV confirmados: **4 recursos a agregar, 0 a cambiar y 0 a destruir**
(SPA, método de cliente público, API y asociación individual de conexión).
Plan local ignorado: `auth0/development.tfplan`.

Tras autorización explícita del usuario («sí, autorizo»), se aplicó ese mismo plan
con SHA256 `40f1aca713126d9621e1629edfcc0aece5ba00126698ee273509bd5c9bde34fa`:
**4 agregados, 0 modificados, 0 eliminados**. Se verificaron por Management API la
SPA pública, grants, callbacks/logout/origins, API RS256 con TTL 900 y asociación
a la conexión existente. La comparación conservó la configuración inventariada
de clientes y APIs preexistentes. Un plan posterior con refresh devolvió cero
cambios, sin ampliar los ocho scopes acordados.

Datos públicos verificados en [development.public.json](../../auth0/development.public.json):
Client ID de la SPA `BDuvRyQ6ryyye08Bs9ZEfRzw7AsskFs6`; API ID
`6aef9bcd6bb338827e0e7c6f`. No confundir el clientId SPA con el de Terraform.
Ese JSON es metadata de integración, no un app-config.json listo para reemplazar
el runtime actual. Estado, planes y credenciales continúan ignorados por Git.

No se crearon usuarios ni recursos PROD, ni se ejecutaron migraciones o despliegues.
Login real, seguridad de API y directorio integrado pertenecen a SNI-72/73/74 y
siguen pendientes. SNI-71 conserva pendiente la revisión conjunta del contrato y
el contraste de las exigencias restantes de la presentación cuando esté disponible;
el aprovisionamiento DEV y sus parámetros ya quedaron acreditados.
