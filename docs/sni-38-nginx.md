# SNI-38 — Entrada HTTP con NGINX

## Alcance y estado

Una entrada por ambiente: UI en `/`, API pública de Snippets en `/api/`.
La implementación local y el candidato Swarm **no activan NGINX en Azure**.
No se abren puertos, no se emiten certificados ni se modifica identidad/autenticación.
El CD ampliado se prepara en [SNI-43](sni-43-cd.md); evidencia remota final en SNI-44.

Base: infra/dev `1ef642081876601f6dc7238a022abe0aa3963280`, con SNI-33 integrado.
Rama: `feat/sni-38-nginx-ingress`. No hay cambios Kotlin ni en los controllers.

## Contrato público → interno

| Pedido público | Destino |
| --- | --- |
| `/`, `/editor/...` y demás rutas de UI | `http://ui:8080`, conservando URI |
| `/api/snippets` | `http://snippets-service:8080/snippets` |
| `/api/snippets/{id}` | `http://snippets-service:8080/snippets/{id}` |
| `/api/languages` | `http://snippets-service:8080/languages` |
| `/api/users` | `http://snippets-service:8080/users` |
| `/api` sin barra, con cualquier método | 308 relativo a `/api/`, conservando query |
| `/healthz` | Salud propia del proxy, sin consultar upstreams |
| `/.well-known/acme-challenge/{token}` | Archivo en `/var/www/acme/.well-known/acme-challenge/{token}` |

`/api/` enruta exclusivamente a Snippets, no es una lista de endpoints nuevos.
Un endpoint futuro de Snippets queda en su namespace sin editar el proxy. NGINX
normaliza URIs según sus reglas estándar; no agregamos un decodificador propio.
La query conserva duplicados, vacíos y codificación; métodos y bodies se preservan.

Una ruta de API inexistente conserva el error del backend; nunca cae en la SPA.
El fallback de navegación SPA pertenece al servidor de UI, no al proxy de entrada.
No hay rutas hacia Permissions, PrintScript, Asset, Azurite, PostgreSQL o brokers.

## Decisiones y alternativas

Thiago aprobó el 24/10/2026 las tres propuestas del plan con «sí apruebo»: 308 para
`/api`, DNS en runtime y límites de 8 MiB / 2 s / 60 s. Las decisiones anteriores
de SNI-19/33 se mantienen; esta aprobación no autoriza despliegues o migraciones.

| Elección | Motivo y ventaja | Alternativa y costo aceptado |
| --- | --- | --- |
| 308 relativo de `/api` a `/api/` | Canoniza la entrada sin convertir POST/PUT en GET ni construir una URL con Host del cliente | Rechazar la ruta evita un salto HTTP. Aceptamos una petición extra para clientes que siguen el redirect. |
| Upstreams con nombre estable, `resolve`, zona compartida y DNS Docker | Arranque sin UI/API y recuperación de cambios de IP sin reiniciar proxy | Resolución sólo al arrancar es más simple pero retiene IPs viejas y exige destinos presentes. Aceptamos DNS/cache y recuperación no instantánea. |
| DNS `127.0.0.11`, cache 5 s, resolución 2 s | Compatibilidad con red Docker y espera acotada | No es configuración portable fuera de Docker; tráfico puede fallar temporalmente durante resolución/reemplazo. |
| 8 MiB por request, conexión 2 s, lectura/envío 60 s | Acota recursos/esperas sin rechazar por defecto el envoltorio JSON de código de 1 MiB | Requests mayores, incluso por metadatos extensos, reciben 413. No es el mismo límite que el contenido de SNI-19. |
| NGINX oficial 1.30.6-alpine fijado por digest | Versión reproducible con DNS dinámico OSS; no construimos una imagen propia innecesaria | Mantener el pin exige revisión y repetir pruebas al actualizar. No se sigue `latest`/`stable` automáticamente. |
| UI separada `ui:8080` | Permite imagen y despliegue independientes y evita recompilar proxy por cambios de UI | Es un contrato a adoptar en SNI-42; no sustituimos la UI pendiente con una pantalla ficticia en runtime. |
| Sólo NGINX publica HTTP en el candidato Swarm | No se puede eludir el punto de entrada accediendo a los puertos de aplicación | Diagnóstico externo directo requiere túnel/operación interna. Compose conserva localhost para desarrollo. |
| HTTP inicial; reservar webroot de ACME | Permite cerrar y probar ruteo sin bloquearse por dominios/certificados | No hay cifrado externo todavía; TLS/renovación y apertura de red pertenecen a SNI-39/40. |
| Sin caché, sin interceptar errores y sin reintentos upstream | No oculta fallas ni duplica escrituras inciertas | No recupera transparentemente una petición fallida y no reduce tráfico al backend. El cliente/caso de uso maneja reintentos con su contrato. |
| Salud propia del proxy | Una UI caída no hace reiniciar NGINX ni corta una API sana | Salud 200 no acredita disponibilidad de aplicaciones; se necesitan probes por destino. |
| Headers canónicos, no cadena confiada del navegador | Evita confiar en protocolo, host o IP afirmados por el cliente | Se pierde una cadena previa de proxies; añadir un balanceador externo exige revisar explícitamente la frontera de confianza. |
| Log estructurado mínimo; errores sólo fatales | Evita que URLs, querystrings, Authorization, bodies o claves aparezcan en errores de request de NGINX | Menos detalle diagnóstico. Se correlaciona por request ID, estado y tiempos; habilitar debug requiere una decisión de seguridad. |
| Overlay Swarm integrado mediante render SNI-43 | Comparte la base y elimina explícitamente los puertos de aplicaciones en el resultado | Requiere herramientas nuevas; no aplicar el overlay directamente con herramientas antiguas. |

SNI-38 entregó inicialmente un candidato completo. SNI-43 elimina esa duplicación:
el renderer combina base y overlay y quita explícitamente los puertos de aplicación.
Una lista `ports: []` no garantiza eliminarlos en el merge de Swarm. No usamos
`!reset` como si fuera compatible con `docker stack`; CI verifica el resultado.

## Configuración de archivos

* `nginx/nginx.conf`: proceso/eventos, DNS/upstreams, formato de logs, límites y
  defaults de proxy. El `map` identifica el prefijo público sin repetir headers.
* `nginx/templates/ingress.conf.template`: hostname del ambiente, rutas y headers.
  La imagen expande sólo `PROXY_HOSTNAME` y `PROXY_PUBLIC_PORT`. `$uri`, `$scheme`,
  `$remote_addr` y `$request_id` deben seguir siendo variables de NGINX.
* `nginx/validate-env.sh`: verifica hostname y puerto antes de ejecutar el entrypoint
  oficial. No admite inyección de directivas ni imprime el valor inválido.
* `compose.yaml`: perfil `ingress` opt-in, binds de sólo lectura y puerto localhost.
* `swarm/stack.ingress.yaml`: overlay HTTP de NGINX/configs/ACME, combinado con
  `stack.yaml` y opcionalmente Asset/UI por el renderer SNI-43.
* `scripts/validate_nginx_config.py`: renderiza dev/prod, con y sin Asset, y rechaza drift.
* `scripts/verify_nginx.py`: aceptación real local; no despliega en Swarm ni Azure.
* `tests/nginx/`: upstreams HTTP y desafío ACME exclusivamente para transporte de prueba.
  No es la UI ni un Snippets alternativo habilitado en dev/prod.

## Uso local

Variables opcionales en `.env.example`:

| Variable | Default local | Uso |
| --- | --- | --- |
| `PROXY_HOSTNAME` | `localhost` | Nombre canónico aceptado; un solo hostname minúsculo, sin esquema/path/puerto |
| `PROXY_HTTP_PORT` | `8088` | Puerto publicado sólo en `127.0.0.1` |
| `PROXY_PUBLIC_PORT` | `8088` | Puerto canónico que ve el navegador; mantenerlo alineado con el publicado |

```bash
docker compose --profile ingress up -d nginx
docker compose --profile ingress exec -T nginx nginx -t
curl -i http://localhost:8088/healthz
```

Es normal recibir 502/504 en `/` si no existe UI, o en `/api/...` si Snippets no
está disponible. No sirve una página de bienvenida que simule la aplicación.
Levantar las aplicaciones por sus procedimientos existentes; el perfil `ingress`
no las construye ni levanta por dependencia rígida. No cambian sus puertos locales.

## Headers y frontera de confianza

NGINX acepta el hostname configurado, no cualquier Host. El servidor por defecto
rechaza otras rutas con 404; `/healthz` queda disponible para healthchecks internos.
`Host` y `X-Forwarded-Host` se normalizan a `hostname:puerto_canónico`.
`X-Forwarded-Proto` deriva de la conexión real (`http` en esta fase), no del header
del cliente; `X-Forwarded-Port` viene de configuración validada. `Forwarded` y
`X-Forwarded-Ssl` se eliminan. `X-Forwarded-Prefix` es `/api` para API y vacío para UI.
`X-Request-ID` se reemplaza por el ID generado por NGINX. Se conservan Authorization,
Idempotency-Key, Content-Type y Origin, sin implementar CORS en el proxy.

`X-Real-IP` y `X-Forwarded-For` parten del peer observado, sin concatenar la cadena
del cliente. Bajo routing mesh/NAT ese peer puede ser de Docker, no la IP original
del navegador. Nunca usar esos headers como identidad o autorización de usuario.

El backend sólo debe confiar en el conjunto explícito de headers generado por el
proxy controlado, no en cualquier `X-Forwarded-*` arbitrario. Esta PR no habilita
interpretación automática de headers en Spring ni cambia autenticación. El retiro
de puertos directos reduce bypass, pero no convierte la red interna en una frontera
de confianza absoluta frente a contenedores comprometidos.

Errores de aplicación conservan estado, body y Content-Type (incluido Problem
Details). Los errores propios de NGINX, por ejemplo 413/502/504, pueden tener HTML
con ese estado de error: no son HTML de la SPA ni un éxito 200. No se reescribe el
JSON de errores ni su `instance`. No se promete reescritura universal de URLs de
respuesta: backends deben respetar host canónico y contratos de URL relativos.

## Tiempo y recuperación

`proxy_read_timeout 60s` mide **inactividad entre lecturas**, no una duración total
máxima de cualquier operación. `proxy_send_timeout`, `send_timeout` y los timeouts
de cliente también son por operaciones/inactividad; no sustituyen límites de
ejecución del dominio. El probe lento comprueba un backend que no envía respuesta.

No hay WebSockets, timeouts infinitos ni buffering global deshabilitado por adelantado.
El canal incremental de US9/10 se define en SNI-45 y su ajuste de proxy en SNI-52.
Tras un fallo, NGINX puede excluir un upstream brevemente por contabilidad pasiva;
DNS y recuperación están acotados, pero no son instantáneos ni una garantía de SLA.

## Swarm, configs y recuperación de configuración

**No aplicar el overlay con herramientas antiguas ni un `docker stack deploy`
manual como atajo.** Seguir [el rollout SNI-43](sni-43-cd.md): herramientas,
callers, drenaje, registro vigente y operación de infraestructura bajo lock.

El candidato publica sólo HTTP 80 → NGINX 8080 y deja las aplicaciones sin puertos
publicados. TLS futuro agregará 443 y su configuración; hoy no se publica un 443
sin certificado. Las dos bases, contenido local y secretos se conservan.

Las configs se llaman `snippet-searcher-<ambiente>_nginx_{main,routes,env_check}_v1`.
Son snapshots inmutables: cambiar el archivo local no cambia una config existente.
Para actualizar, incrementar sólo la revisión del recurso modificado, validar
`nginx -t` y el render, y entregar las referencias nuevas al despliegue bajo lock.
Conservar las configs anteriores. Volver atrás significa referenciar sus nombres
anteriores y reemplazar la tarea del proxy; no reconstruir aplicaciones ni borrar datos.
El registro debe conservar también hostname/puerto del ambiente, no sólo imagen.

El webroot es el volumen `<stack>_ingress_acme`, montado read-only en `/var/www/acme`.
Certbot deberá escribir en ese mismo volumen y ruta; NGINX sólo sirve GET/HEAD y
devuelve 404 si falta el token. Hoy no hay emisión/renovación ni servicio Certbot.
Los stacks actuales son de un nodo; si se amplían, el volumen local exige coordinar
ubicación o almacenamiento compartido. No es automáticamente visible en todas las VMs.

## Verificación reproducible

```bash
python3 -B scripts/validate_stack.py
python3 -B scripts/validate_asset_config.py
python3 -B scripts/validate_nginx_config.py
python3 -B -m unittest discover -s scripts -p 'test_*.py' -v
python3 -B scripts/verify_nginx.py
```

El runner exige Docker local (guarda existente de SNI-33), crea un proyecto
`sni38-check-<uuid>`, usa un puerto aleatorio ligado a localhost e ignora `.env`.
No necesita credenciales, frontend, Gradle, VMs, DNS público ni certificados.

Aceptación con NGINX real:

1. Arrancar sin upstreams; salud propia y `nginx -t` correctos, API ausente → 502.
2. Incorporar UI, luego API; recuperación por DNS sin recrear proxy.
3. Verificar GET/POST/PUT/DELETE/OPTIONS, cuerpo exacto, query codificada y headers.
4. Verificar 308 con query y seguimiento conservando método/body.
5. Verificar API 404/422 JSON sin fallback de UI, 503/502 sin repetición de escrituras.
6. Verificar Host desconocido y spoofing de forwarding, logs sin datos sensibles.
7. Verificar webroot ACME, ausencia 404 y escritura denegada.
8. Verificar 413 antes de enviar un cuerpo mayor a 8 MiB y transporte de 1 MiB intacto.
9. Verificar timeout real de lectura a los 60 s (el runner tarda más de un minuto).
10. Caída de UI sin romper API y salud propia independiente.
11. Reemplazar realmente API, comprobar ID/IP nuevos y recuperación sin reiniciar NGINX.

Al finalizar, retira sólo contenedores/red del proyecto generado. No borra volúmenes
ni configura un Swarm en Docker Desktop. El runner no contiene implementación de
permisos, persistencia ni casos de uso de Snippets. CI repite pruebas y aceptación.

## Coordinación por ticket

* SNI-39: hostname por ambiente y acceso de red. Ningún puerto se abrió aquí.
* SNI-40: usar el webroot acordado, agregar TLS/443 y renovación; no asumir un
  certificado existente ni habilitar HSTS antes de verificar el transporte completo.
* SNI-41: CORS de Spring, sin wildcard implícito ni confundirlo con autorización.
* SNI-42: UI propia con nombre `ui`, puerto 8080, `/api` relativo, fallback SPA en su servidor.
* SNI-43: inventario/configs/volumen nuevo y candidato sin puertos de apps; no
  reintroducir versiones históricas al reaplicar. No se modificaron sus scripts compartidos.
* SNI-44: evidencia real de ingreso DNS/TLS/proxy y regresión CD en dev/prod.
* SNI-36: recorrido funcional real con UI, Permissions y Asset, independiente de este probe.
* SNI-45/52: protocolo incremental futuro; este proxy HTTP base no lo anticipa.

## Fuentes

[Ejemplo de la cátedra fijado](https://github.com/austral-ingsis/nginx-docker/tree/8fe0fbfeaa9f597835b83266af10908ad88f77f2),
[proxy_pass y headers](https://nginx.org/en/docs/http/ngx_http_proxy_module.html),
[upstreams, resolve y zonas](https://nginx.org/en/docs/http/ngx_http_upstream_module.html),
[configs de Swarm](https://docs.docker.com/engine/swarm/configs/).
La demo sirve estáticos desde el proxy; aquí se mantiene UI separada como exige el ticket.

## Evidencia y límites

Verificado localmente el 24/10/2026, Docker Engine 29.3.1, Compose 5.1.1 y Python 3.11:

* **107 tests exitosos**, sin omisiones/fallos: 99 de la base y 8 nuevos de esta entrega.
* `validate_stack.py`: base dev/prod correcta.
* `validate_asset_config.py`: dev/prod × local/asset correctos.
* `validate_nginx_config.py`: dev/prod × con/sin Asset correctos; sólo el proxy
  publica HTTP, sin cambiar configuración/datos previos.
* `nginx -t` correcto usando la imagen fijada. El índice oficial estable se resolvió
  a la versión 1.30.6-alpine y digest `47928bf67eb62a1863cb08d9ecb52d3e704304ba614eaee17884204677702951`.
* Aceptación final: proyecto `sni38-check-70d0b8375eb6`. Pasaron todas las fases,
  incluido OPTIONS/Origin, headers canónicos, query/body exactos, errores sin SPA,
  no replay, 413, ACME, timeout real de 60 s, outages independientes y cambio real
  de ID/IP del upstream sin recrear el proxy. Logs sin los marcadores sensibles de prueba.
* Regresión real de Asset: proyecto `sni33-check-c91941671c52`, persistencia tras
  recrear ambos contenedores, outage/recuperación y borrado idempotente correctos.
  Su volumen quedó conservado.
* `git diff --check`: correcto. Se conserva la advertencia de Compose sobre
  `version` en archivos Swarm históricos; no es una falla del renderizado.

Durante el desarrollo se corrigió el escape de `$` del filtro envsubst en el YAML
Swarm. La primera aceptación lenta mostró la exclusión pasiva temporal del upstream
tras el timeout: el test ahora espera su recuperación acotada antes de aislar la
caída de UI, sin desactivar el timeout ni relajar el contrato de independencia.
Las ejecuciones fallidas no se contaron como evidencia exitosa.

Se retiraron sólo contenedores/redes de proyectos de prueba. No se borraron volúmenes
ni se inicializó Swarm en Docker Desktop. No hay despliegue remoto, emisión TLS,
UI real integrada ni cambios de estado en Linear en esta entrega. La aceptación
de transporte no declara terminados los casos de uso del frontend.
