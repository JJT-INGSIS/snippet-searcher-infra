# Identidad y autorización

[Arquitectura](README.md) · [Configuración y operación de Auth0](../../auth0/README.md)

La UI delega el login a Auth0 mediante Authorization Code con PKCE. Obtiene
el access token para la audiencia de su ambiente y lo envía como
`Authorization: Bearer` a Snippets por el ingreso HTTPS. Las nuevas solicitudes,
incluidas las reconexiones del canal de ejecución, requieren un token válido.
El token queda fuera de la URL y del contenido de logs, jobs y eventos.

En modo `auth0`, Snippets valida firma, issuer, audiencia y vigencia. `sub`
identifica al actor. Cada operación aplica el permiso correspondiente mediante
Permissions y su propio contexto. Las solicitudes protegidas sin credencial
válida reciben 401. El modo DEV local requiere su configuración explícita.
Un header DEV en un entorno Auth0 no habilita identidad.

| Operación | Control |
| --- | --- |
| `GET /languages` | Público. |
| Crear, editar y compartir | Usuario autenticado. La creación registra el dueño. Edición y sharing exigen el permiso correspondiente. |
| Listar, leer, descargar y ejecutar | El acceso deriva de ownership o sharing y se valida al solicitar la operación. |
| Reglas de formato y lint | Selección privada por dueño, lenguaje y versión. |
| Tests, sesiones y progreso de jobs | Acceso al snippet o ámbito del trabajo y comprobaciones propias de la operación. |
| Buscar destinatarios | Endpoint autenticado de Snippets. Consulta el directorio habilitado para el ambiente. |

Auth0 conserva las cuentas y credenciales de usuario. Snippets y Permissions
persisten identificadores de actor para ownership, sharing, reglas y trabajos.
Una identidad Auth0 no hereda relaciones DEV por coincidencia de correo.
El directorio usa una credencial M2M separada para consultar
Auth0 Management API con `read:users`. La SPA no recibe ese secreto y el login
funciona independientemente de la disponibilidad del directorio.

NGINX sólo publica la API de Snippets. Permissions y PrintScript se consultan en
la red privada y los workers operan con el actor o ámbito guardado en su trabajo.
La UI limpia los datos privados de la sesión local al salir o cambiar de usuario.
Salir de la UI no constituye una cancelación remota de un intérprete.
