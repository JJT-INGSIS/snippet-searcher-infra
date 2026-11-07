# SNI-71 — Propuesta de autenticación y autorización

Fecha: 07/11/2026. Estado: propuesta revisable basada en los apuntes de clase y
la recomendación adjunta. La presentación todavía no está disponible. Este
documento registra el inventario y el plan; no acredita una integración implementada
ni crea/configura recursos de Auth0. El avance autorizado posteriormente se concreta
en el [contrato compartido](authentication-authorization-contract.md) y en el
[módulo preparatorio](../../auth0/README.md). Los pendientes del tenant no se dan
por verificados y este plan conserva las alternativas originales para contexto.

## Requisitos aportados por el usuario

- Delegar registro, login, recuperación de credenciales y logout en Auth0.
- Conservar la autorización de snippets y ownership en Permissions.
- Usar el SDK de la UI, Spring Security en el borde HTTP e infraestructura como código.
- Revisar dominio, audience, URLs de retorno y permisos mínimos.
- Evitar duplicar perfiles de Auth0 o agregar datos al token sin una necesidad concreta.

El apunte sobre una tabla propia con id/email/password contradice la delegación
de autenticación. No se propone almacenar contraseñas ni validar credenciales
en Snippets. Una eventual tabla de correspondencia de identidades o datos propios
del negocio es otra responsabilidad y requiere justificar su necesidad.

Decisión confirmada por el usuario el 07/11/2026: una persona crea el tenant del
proyecto e invita a los otros integrantes; cada integrante administra con su
propia cuenta, sin compartir contraseñas. Se acordó mantener dos administradores.
La cuenta y el tenant no existían al preparar la propuesta inicial. Posteriormente
el usuario confirmó el dominio `jjt-snippet-searcher.us.auth0.com`; conexión de
usuarios, configuración de aplicaciones y aprovisionamiento permanecen pendientes.

Decisión posterior confirmada el 07/11/2026: un único tenant compartido entre DEV
y PROD, con SPA/API y audiences por ambiente. El usuario prioriza reducir
configuración y mantenimiento del TP, aceptando compartir usuarios y ajustes
globales de Auth0. Detalle, límites y condición de revisión en el contrato.

## Inventario comprobado

| Componente | Estado local observado | Integración necesaria |
| --- | --- | --- |
| UI | `@auth0/auth0-react` instalado; `main.tsx` no tiene Auth0Provider; App no integra login | SDK, callback, estados de sesión y botón para Universal Login |
| Runtime UI | `src/utils/api/config.ts` acepta disabled/dev | Modo Auth0 con configuración pública validada por ambiente |
| HTTP UI | Axios y fetch de ejecución son transportes separados; usan identityHeaders | Obtener access token para cada solicitud en ambos transportes |
| Cachés y creación | actorScope y creación idempotente dependen del actor | Separar cachés por identidad; conservar borradores e intenciones de creación |
| Snippets | DevelopmentActorIdentityResolver usa X-Dev-Actor-Id sólo con perfil dev | Resolver identidad a partir del principal autenticado validado |
| Permissions | OwnershipController y casos de ownership, acceso y sharing existentes | Reutilizar autorización; confiar sólo en llamadas internas admitidas |
| Directorio | ConfiguredUserDirectory con usuarios de desarrollo | Adaptador de usuarios reales para sharing, en SNI-74 |
| NGINX | `/api/` apunta a Snippets y conserva Authorization; ejecuciones sin buffering | Mantener transporte NDJSON y la autoridad de autenticación en Spring |
| Workers | Coordinación y datos durables existentes | Usar identidad interna persistida; no conservar tokens de usuario |

La revisión de Linear del 06/11 también registra OAuth pendiente. No se encontró
integración Auth0 comentada en los archivos de arranque locales actuales; si la
cátedra entrega otra base, debe compararse con estos puntos de integración.

## Contrato propuesto

1. UI registrada como Single Page Application. SDK oficial con Authorization
   Code + PKCE y Universal Login. La pantalla local puede ofrecer ingresar/salir
   y mostrar estados; la captura y validación de contraseñas pertenecen a Auth0.
2. Registrar una API para Snippets. La UI solicita un access token para su audience
   y lo envía mediante Authorization: Bearer. Un ID token no se usa como credencial
   para la API. No se agregan roles de owner ni listados de snippets al token.
3. Snippets funciona como OAuth2 Resource Server: Spring Security verifica firma,
   algoritmo admitido, issuer, audience y tiempos; SecurityFilterChain aplica la
   matriz de rutas. No se implementa un emisor de tokens propio.
4. Identidad externa basada en el subject validado, vinculada al issuer permitido.
   No usar email como clave de ownership. Para un issuer único por ambiente se
   propone reutilizar sub como actorId; no aceptar IDs elegidos por el cliente.
5. Permissions conserva las decisiones por snippet: owner es el actor autenticado
   que confirmó la creación; lector y tercero mantienen las reglas existentes.
   Un token válido no concede acceso a todos los snippets.
6. No reenviar el access token de usuario a PrintScript, Redis o workers. La
   autenticación entre servicios es una decisión aparte del login de usuario:
   comprobar aislamiento de Permissions y necesidad de credenciales de servicio
   antes de abrir nuevas rutas o accesos. No exponer sus escrituras al navegador.

El principal autenticado debe llegar a los casos de uso por el borde HTTP,
conservando la separación actual. No confiar en headers dev cuando está activo
Auth0. El modo dev seguirá siendo explícito para pruebas locales.

### Matriz de rutas propuesta

| Ruta/capacidad | Política |
| --- | --- |
| UI, callback y healthcheck mínimo | Acceso público según su función |
| GET /languages | Conservar público, como el cliente actual; confirmar en contrato |
| Crear, listar, leer y actualizar snippets; descargas y formato | Autenticación y permisos actuales según operación |
| Reglas de formato/lint, tests y resultados | Autenticación y ámbito correspondiente |
| Ejecuciones, estado, eventos, inputs y cancelación | Autenticación más acceso a la ejecución/snippet |
| GET /jobs/{id} | Autenticación y autorización por ámbito del trabajo |
| GET /users y compartir | Autenticación; directorio mínimo y permisos de sharing |
| Activación del parser | Mantener comando administrativo interno; no convertirlo en ruta pública |
| Preflight CORS | Permitir los orígenes/métodos/headers acordados sin exigir un token al preflight |

Las rutas exactas deben inventariarse sobre el dev integrado al implementar SNI-72.
No usar sólo matchers de ejemplos de la presentación dejando endpoints reales sin cubrir.
Credencial ausente o inválida: 401. Identidad válida sin permiso: conservar la
política actual de 403/404 para no revelar recursos privados.

Para NDJSON se propone validar cada solicitud, incluida reconexión, inputs y
cancelación. Si vence el token, el SDK obtiene otro o pide login para la siguiente
solicitud; no repetir automáticamente creación, ejecución ni otra mutación ante
un 401. La política de una conexión ya abierta debe quedar documentada y probada;
el vencimiento de un token no equivale por sí solo a cancelar trabajo remoto.

## Configuración e infraestructura como código

- Backend: externalizar AUTH_DOMAIN/issuer y AUTH_AUDIENCE. Se puede conservar
  application.properties; application.yml es un formato alternativo, no un requisito
  de OAuth. Usar las propiedades reales soportadas por la versión de Spring y
  un validador de audience cuando corresponda.
- UI: domain, clientId, audience y URL de callback en app-config.json; son parámetros
  públicos. Ningún client secret ni token de Management API en el navegador.
- URLs: enumerar por separado localhost y los hostnames efectivos de DEV/PROD,
  con esquema, puerto y ruta exactos. Callback, Allowed Logout URLs, Allowed Web
  Origins y CORS son configuraciones relacionadas pero diferentes. Audience es
  el identificador de API y no tiene por qué ser una URL navegable.
- IaC: se recomienda Terraform con el proveedor oficial Auth0 para aplicación
  SPA, API y sus configuraciones; alternativa: Auth0 Deploy CLI. Terraform facilita
  revisión de cambios pero agrega gestión de estado y credenciales. No hay elección
  aprobada ni archivos Terraform existentes comprobados en este inventario.
- Credenciales de aprovisionamiento y del directorio: backend/operación, permisos
  mínimos y almacenamiento seguro. No versionar secretos ni estado con datos sensibles.
- La cuenta/tenant y credenciales iniciales requieren bootstrap. No crear cuentas
  facturables ni aplicar IaC o desplegar remotamente como efecto de este documento.

## Directorio e identidades existentes

Los tokens de un usuario no contienen un directorio de todos los usuarios. Para
sharing se propone un adaptador backend de Auth0 Management API con credenciales
de servicio de sólo lectura y respuesta mínima (id, nombre visible y los datos
que requiera el contrato). Alternativa: índice local mínimo de usuarios conocidos,
que reduce consultas externas pero exige sincronización y no incluye a todos los
usuarios hasta conocerlos. La elección y la exposición de datos quedan pendientes.

No migrar automáticamente dev-juan/dev-thiago ni otros IDs a subjects de Auth0.
Inventariar ownership, shares, reglas, ejecuciones, jobs e idempotencia por actor;
acordar correspondencias y un procedimiento separado si se conservan datos de DEV.

## Orden de trabajo

1. SNI-71 (Juan): revisar este contrato, acordar identidad/directorio/IaC y completar
   parámetros verificables del tenant. Los apuntes permiten avanzar sin esperar
   la presentación; al recibirla se contrastan las exigencias restantes.
2. Infra: preparar configuración reproducible y bootstrap del tenant/SPA/API,
   coordinado con SNI-71. No duplicar el trabajo en un nuevo ticket sin revisar el reparto.
3. SNI-72 (Juan) y SNI-73 (Juanchi) en paralelo con el mismo contrato. Backend con
   claves JWT controladas; UI con SDK y API controlada hasta integrar ambos.
4. SNI-74 (Thiago): directorio real y aceptación conjunta owner A, lector B y tercero;
   login/logout, sharing, expiración, cambio de identidad y HTTP/NDJSON.

La falta del tenant impide acreditar login real, no preparar el contrato y las
pruebas controladas. No marcar tickets terminados sólo por agregar configuración.

## Datos y decisiones que faltan

- Existencia del tenant, dominio real, aplicación SPA/clientId e identificador de API.
- URLs exactas por ambiente y políticas de sesión/registro que indique la cátedra.
- Confirmar subject/issuer como identidad y tratamiento de datos dev preexistentes.
- Elegir directorio mínimo y herramienta IaC; comprobar el aislamiento de servicios.
- Confirmar política de expiración de conexiones NDJSON ya abiertas.

## Fuentes técnicas

- [Auth0 React SDK](https://auth0.com/docs/libraries/auth0-react).
- [Authorization Code + PKCE](https://auth0.com/docs/get-started/authentication-and-authorization-flow/authorization-code-flow-with-pkce).
- [Validación de access tokens](https://auth0.com/docs/secure/tokens/access-tokens/validate-access-tokens).
- [Spring Security Resource Server](https://docs.spring.io/spring-security/reference/servlet/oauth2/resource-server/jwt.html).
- [Proveedor Terraform de Auth0](https://developer.auth0.com/resources/labs/tools/devops-terraform).

## Revisión de la fuente de SSO aportada — 07/11/2026

La página [Cómo implementar el inicio de sesión único](https://auth0.com/es/learn/how-to-implement-single-sign-on)
explica la sesión central del proveedor y la reutilización de esa sesión entre
aplicaciones. Es fundamento conceptual; sus instrucciones de SSO Integrations
para aplicaciones externas no son el procedimiento de registro de nuestra SPA.

Para este proyecto se mantiene la propuesta de una aplicación React SPA y una
API de Snippets. Tener varios microservicios no exige crear una pantalla de login
ni una aplicación interactiva Auth0 por cada backend. Tampoco exige SAML,
integraciones empresariales o Actions personalizadas para el recorrido inicial.

La documentación técnica del SDK confirma Universal Login, PKCE y obtención de
access tokens con audience para llamar a la API. Se usará onRedirectCallback
compatible con el router de React para recuperar la navegación tras el login,
sin permitir destinos externos arbitrarios.

Agregar al contrato de logout la distinción entre estado/caché local de la UI,
sesión de Auth0 y sesión de un proveedor externo como Google. El logout debe
limpiar el estado privado local y usar el SDK para terminar la sesión de Auth0.
No se promete cerrar automáticamente todas las sesiones de todos los proveedores
o aplicaciones: se verifica el comportamiento configurado para nuestro flujo.

Los valores de Allowed Callback URLs, Allowed Logout URLs y Allowed Web Origins
se registran explícitamente por ambiente. Son distintos de los orígenes CORS
admitidos por Snippets; no basta completar una sola de esas configuraciones.

Fuentes contrastadas:
- [SDK React](https://auth0.com/docs/libraries/auth0-react).
- [Application Settings](https://auth0.com/docs/get-started/applications/application-settings).
- [Capas del logout](https://auth0.com/docs/authenticate/login/logout).
- [Validación de access tokens](https://auth0.com/docs/secure/tokens/access-tokens/validate-access-tokens).
