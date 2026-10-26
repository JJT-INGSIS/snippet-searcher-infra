# NGINX desde cero, con nuestra configuración

## 1. Qué problema estamos resolviendo

Tenemos varias aplicaciones. Snippets administra snippets y coordina validación,
almacenamiento y permisos. Permissions decide accesos. PrintScript valida el
lenguaje. Asset guarda contenido sobre Azurite. También tendremos una UI.

No queremos que el navegador conozca todos sus puertos o pueda saltear Snippets
para acceder directamente al código guardado. Queremos una entrada estable:
la misma dirección para abrir la UI y llamar a la API.

NGINX es un programa que puede recibir HTTP. Puede servir archivos o actuar de
**reverse proxy**: recibe una petición y la entrega a otro servidor por cuenta
del sistema. Aquí lo usamos como reverse proxy; la UI sirve sus archivos desde
su propio contenedor.

No es necesario para que Snippets se comunique con Permissions. Esas llamadas
siguen siendo directas dentro de Docker. Tampoco crea las VMs ni decide dónde
Swarm levanta cada contenedor.

## 2. Una request no es solamente una URL

Un pedido tiene varias partes:

```http
POST /api/snippets?example=1 HTTP/1.1
Host: localhost:8088
Content-Type: application/json
Authorization: Bearer <identidad, cuando corresponda>
Idempotency-Key: <uuid>

{"name":"Ejemplo","language":"printscript","version":"1.0","code":"println(1);"}
```

* Método: `POST`, indica la operación HTTP; no es equivalente a `GET`.
* Path: `/api/snippets`, el destino dentro del servidor.
* Query: `example=1`, parámetros posteriores a `?`.
* Headers: metadatos del pedido; pueden contener identidad, formato y clave de reintento.
* Body: datos que enviamos, en este caso un JSON.

El proxy no debe perder el código, cambiar el método o generar otra clave de
idempotencia. Tampoco convierte el header de desarrollo en autenticación real.

La respuesta también tiene estado HTTP, headers y body. Snippets puede responder
201, 400, 403 o un error técnico según el caso de uso. NGINX transmite esa respuesta;
no decide si el snippet es válido o de quién es.

## 3. Recorrido de un pedido en nuestro sistema

```text
Navegador: POST http://localhost:8088/api/snippets
    |
    v
NGINX: reconoce el Host, elige /api/ y quita ese prefijo
    |
    v
Snippets: POST http://snippets-service:8080/snippets
    |
    +--> PrintScript: validar
    +--> PostgreSQL: metadatos y referencias
    +--> Permissions: accesos
    +--> Asset: contenido, si el proveedor remoto fue activado
    |
    v
Respuesta de Snippets --> NGINX --> navegador
```

El ejemplo describe responsabilidades, no una transacción distribuida ni un orden
nuevo de operaciones. Los casos de uso existentes siguen coordinando sus pasos.
En Azure, en lugar de `localhost`, se usará el hostname del ambiente cuando DNS,
red y despliegue estén configurados. Hoy no activamos ese ingreso remoto.

## 4. DNS, puertos, Docker y Swarm: cuatro cosas distintas

**DNS** traduce nombres a direcciones. Hay dos ámbitos:

* DNS público: por ejemplo, un nombre del ambiente que apunta a la VM de Azure.
* DNS interno de Docker: `snippets-service` apunta al servicio dentro de su red.

**Puerto** identifica dónde escucha un proceso. Dos contenedores pueden usar
8080 porque tienen espacios de red distintos. `ui:8080` no es `snippets-service:8080`.

**Docker** ejecuta los contenedores y les da red. En Compose publicamos el puerto
local 8088 hacia el 8080 del contenedor NGINX. Los contenedores no usan ese 8088
para llamar a Snippets: usan su nombre y su puerto interno.

**Swarm** asigna las réplicas a nodos y ofrece red/routing hacia ellas. Su routing
mesh puede recibir una conexión por un nodo y entregarla a una tarea en otro.
No selecciona por sí solo «`/api` a Snippets y `/` a UI»: esa decisión HTTP es NGINX.

Nuestro candidato Swarm usa puerto público 80 hacia NGINX 8080. Las aplicaciones
ya no publican 8080/8081/8082 en ese candidato. El firewall de Azure es otra capa:
publicar un puerto Docker no modifica automáticamente las reglas de Azure.

## 5. Qué archivos leer y en qué orden

1. [`nginx/nginx.conf`](../nginx/nginx.conf): reglas generales del proceso y proxy.
2. [`ingress.conf.template`](../nginx/templates/ingress.conf.template): hostname del ingreso local, que incluye
   [`routes.conf.template`](../nginx/templates/routes.conf.template) con las rutas. En las VMs, el 80 usa
   [`redirect.conf.template`](../nginx/templates/redirect.conf.template) y el 443
   [`tls.conf.template`](../nginx/templates/tls.conf.template) ([SNI-40](sni-40-tls.md)).
3. [`validate-env.sh`](../nginx/validate-env.sh): validación previa de configuración.
4. [`compose.yaml`](../compose.yaml): cómo se levanta localmente.
5. [`stack.ingress.yaml`](../swarm/stack.ingress.yaml): candidato para Swarm, no activado.

El archivo de decisiones y verificación está en [SNI-38](sni-38-nginx.md).

## 6. Entender nginx.conf

### Proceso y conexiones

`worker_processes auto` deja que NGINX determine cantidad de workers según CPU.
Los workers atienden conexiones; `worker_connections 1024` es un límite por worker,
no «1024 usuarios garantizados». Una petición proxied usa conexiones al cliente y
al upstream. Memoria, CPU y backend también limitan capacidad.

`pid /tmp/nginx.pid` indica dónde registrar el proceso maestro.
El bloque `events` agrupa ajustes de conexiones; `http` contiene las reglas HTTP.

### DNS y upstreams

```nginx
resolver 127.0.0.11 valid=5s ipv6=off;
resolver_timeout 2s;

upstream snippets_backend {
    zone snippets_backend 64k;
    server snippets-service:8080 resolve;
}
```

`resolver` es el DNS embebido de Docker. `valid=5s` acota el tiempo de cache de
las resoluciones; no garantiza que todo cambio esté visible exactamente a los 5 s.
`resolve` permite actualizar direcciones sin reiniciar NGINX. `zone` mantiene el
estado compartido del upstream entre workers.

`snippets_backend` es un nombre que usamos dentro de NGINX. `snippets-service`
es el nombre real del servicio Docker. No escribimos una IP como `172.x.x.x`:
esas direcciones pueden cambiar al reemplazar un contenedor.

La UI tiene su propio grupo `ui_backend`. Si falta, sus requests fallan, pero
eso no impide arrancar el proxy o usar una API disponible.

### Límites

* `client_max_body_size 8m`: tope del body HTTP completo; no del archivo de código solamente.
* `proxy_connect_timeout 2s`: espera al establecer conexión con el upstream.
* `proxy_read_timeout 60s`: inactividad entre lecturas de la respuesta, no tiempo total de negocio.
* `proxy_send_timeout 60s`: inactividad al transmitir hacia el upstream.
* Timeouts de cliente/envío: evitan algunas conexiones que no progresan.

No son un sistema de trabajos ni un límite de ejecución del intérprete. Una
respuesta que envía datos periódicamente puede durar más de un minuto.

### Qué no hacemos automáticamente

`proxy_next_upstream off` evita reenviar la petición a otro destino tras un fallo.
Si una escritura llegó al servidor pero se perdió la respuesta, repetirla sin
coordinar idempotencia puede duplicar efectos. Ese problema no se soluciona
asumiendo que «si hubo timeout, no escribió».

`proxy_intercept_errors off` conserva los errores del backend. `proxy_cache off`
evita cachear resultados de API. Mantenemos buffering normal: no anticipamos el
canal incremental de ejecución, que pertenece a otra tanda.

Los logs guardan request ID, método, estados y tiempos, no Authorization, código,
query ni cuerpo. Se pierde detalle de diagnóstico para no registrar credenciales.

## 7. Entender server y location

Un bloque `server` define cómo atender un hostname/puerto. `listen 8080` es el
puerto interno. `server_name` contiene el hostname autorizado del ambiente.
El servidor por defecto rechaza hosts desconocidos con 404, salvo el healthcheck.

Los `location` eligen qué hacer con un path. Los principales son:

```nginx
location = /api {
    return 308 /api/$is_args$args;
}

location /api/ {
    proxy_pass http://snippets_backend/;
}

location / {
    proxy_pass http://ui_backend;
}
```

`=` significa coincidencia exacta. `/api/` es un prefijo más específico que `/`.
Así `/api/snippets` no termina en UI, mientras `/editor/123` sí.

La **barra final de proxy_pass importa**. En el bloque de API, la URI `/` del
destino reemplaza el prefijo `/api/`: `/api/snippets` llega como `/snippets`.
En UI no agregamos otra URI al destino, por eso conserva el path de navegación.
No cambiamos controllers para que sepan de `/api`.

El `map` de nginx.conf calcula `X-Forwarded-Prefix` según el path público.
No reescribe el cuerpo ni decide permisos.

## 8. Redirect no es proxy

Un **redirect** devuelve al cliente «pedí esta otra dirección». El navegador debe
hacer otra petición. Eso sucede con `/api` → `/api/`.

Un **proxy** llama al backend desde el servidor y entrega su respuesta. El navegador
no recibe la instrucción de conectarse a `snippets-service`; ese nombre es interno.

Elegimos 308 porque conserva método y body al seguir el redirect. La dirección
es relativa y conserva la query, sin construir una URL con un Host manipulable.
Un cliente HTTP que no siga redirects verá el 308 directamente; no es un fallo.

## 9. Para qué sirven los headers de forwarding

El backend recibe una conexión de NGINX, no directamente del navegador. Los headers
canónicos le describen host, puerto y protocolo públicos. Un cliente puede enviar
headers con esos mismos nombres: por eso el proxy los reemplaza en vez de creerlos.

`Authorization` e `Idempotency-Key` son distintos: los transportamos, no inventamos
identidad ni otra clave. El backend sigue teniendo que validarlos.

`X-Forwarded-For` no es «el usuario autenticado». Con NAT/routing mesh puede contener
una dirección intermedia. No sirve como permiso para leer o editar snippets.

La plantilla se expande con hostname/puerto del ambiente. `validate-env.sh`
rechaza valores que puedan introducir directivas. El filtro de envsubst es importante:
no debe reemplazar las variables propias de NGINX, como `$uri` o `$scheme`.

## 10. Cómo interpretar los errores

| Estado | Qué suele indicar en este recorrido |
| --- | --- |
| 308 | Falta la barra canónica en `/api` |
| 400/403/404/422 del backend | Request inválido, permiso, ausencia u otra condición según su contrato |
| 413 del proxy | Body HTTP mayor al límite configurado |
| 502 del proxy | No pudo obtener una respuesta válida del upstream, por ejemplo destino ausente/desconectado |
| 504 del proxy | Se agotó una espera al comunicarse con upstream |

No basta con mirar «falló»: hay que identificar qué capa respondió. Un error de
NGINX puede tener un body HTML y seguir siendo un error correcto. Lo incorrecto
sería ocultarlo devolviendo la página de UI con estado 200.

`/healthz` sólo dice «NGINX puede responder». No dice «PostgreSQL, Asset y todos
los endpoints funcionan». Por eso también tenemos pruebas específicas por servicio.

## 11. Qué falta para HTTPS, CORS y autenticación

Son problemas distintos:

* **HTTPS** cifra/verifica el transporte mediante un certificado. Tener NGINX no lo activa solo.
* **DNS** permite usar un nombre público para llegar a la VM. No crea certificados ni abre el firewall.
* **CORS** regula qué respuestas permite leer un navegador desde otro origen. No es autorización de usuarios.
* **Autenticación** identifica al usuario. Un dominio o certificado no la reemplaza.
* **Autorización** decide qué puede hacer ese usuario; en nuestro sistema participan Snippets y Permissions.

Cuando UI y API usan el mismo origen (`/` y `/api`), se simplifica el caso habitual
de CORS. No significa que el ticket de CORS o la autenticación estén terminados.

Reservamos un webroot ACME para que Certbot pueda demostrar control del dominio:
el emisor solicita un archivo bajo `/.well-known/acme-challenge/`. Hoy sólo está
preparada la ruta; no existe un certificado creado por este ticket.

## 12. Por qué la configuración cambia entre Compose y Swarm

En Compose montamos archivos locales read-only y tenemos un puerto de depuración
localhost. Para cambiar configuración hay que recrear/reload de forma controlada;
guardar un archivo no garantiza que el proceso lo haya recargado.

Swarm distribuye **configs inmutables** con nombre/revisión. Editar el archivo del
repo no modifica el snapshot de una config que ya existe. Crear una revisión nueva
y actualizar la referencia cambia la configuración distribuida. Conservar la vieja
permite volver a ella. Esto es diferente de un volumen que guarda datos de usuario.

No ejecutamos el candidato Swarm automáticamente: los verificadores/registro/CD
actuales esperan otro inventario. SNI-43 debe adaptarlos sin perder las garantías
que ya probamos al promover imágenes y recuperar despliegues.

## 13. Cómo lo probamos sin terminar todo el proyecto

Usamos NGINX real y pequeños servidores HTTP controlados que muestran lo que
recibieron. Eso permite comprobar ruta, método, body, headers, errores, timeout
y reemplazo de IP sin necesitar la UI terminada o construir tres aplicaciones.

Es evidencia de transporte, no de funcionalidad de negocio. No demuestra que el
usuario pueda compartir un snippet desde la UI real. SNI-36 prueba ese recorrido;
SNI-44 prueba el ingreso remoto y su integración con DNS/TLS/CD.

## Qué deberías poder explicar después

1. El navegador conoce la entrada pública, no las URLs internas de cada dependencia.
2. Swarm decide ubicación/red de tareas; NGINX decide ruteo HTTP por hostname/path.
3. NGINX quita `/api/` antes de entregar la petición a los controllers existentes.
4. Headers y código viajan sin convertir al proxy en el dueño de la lógica de negocio.
5. Un backend caído devuelve un error, no una pantalla HTML exitosa.
6. Las configs se versionan; los volúmenes conservan datos; ninguno reemplaza un backup.
7. Lo preparado y probado localmente no equivale a estar desplegado o autenticado en prod.
