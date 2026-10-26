# SNI-40 — HTTPS con Let's Encrypt y renovación con Certbot

## Alcance y estado

TLS termina en NGINX con certificados de Let's Encrypt para el hostname de cada
ambiente de [SNI-39](sni-39-dns-red.md). Afuera sólo hay HTTPS; adentro, la red
Docker del stack sigue en HTTP. No se agregan Auth0, mTLS interno, WAF, HSTS ni
infraestructura nueva.

| Parte | Estado al 26/10/2026 |
| --- | --- |
| Código, tests y CI | Integrado en `dev` (PRs #21, #23 y #24) |
| dev | **HTTPS confiable en servicio**, con renovación automática. Ver [Evidencia](#evidencia) |
| prod | **HTTPS confiable en servicio**, con renovación automática. Ver [Evidencia](#evidencia) |

Este documento declara HTTPS funcionando en dev y en prod.

## Dos estados de NGINX

Let's Encrypt valida el dominio pidiendo un archivo por HTTP (desafío HTTP-01),
pero NGINX no puede arrancar un bloque TLS sin certificado. Por eso el registro del
ambiente (`release.json`) dice en qué estado está el proxy:

| Estado | `tls` | Puertos | Qué sirve |
| --- | --- | --- | --- |
| HTTP | `false` | 80 | El desafío ACME y un 308 a HTTPS para todo lo demás |
| HTTPS | `true` | 80 y 443 | El 80 igual que antes; el 443 con certificado, UI en `/` y API en `/api/` |

El puerto 80 **nunca** sirve la API: no tiene `proxy_pass`. El 308 apunta siempre a
`https://<hostname del ambiente>` con la misma URI y query; no usa el `Host` que
manda el cliente. Un hostname desconocido recibe 404 en el 80, y en el 443 se corta
el handshake (`ssl_reject_handshake`).

| Archivo | Config Swarm | Estado | Contenido |
| --- | --- | --- | --- |
| `nginx/nginx.conf` | `nginx_main` | ambos | Proceso, DNS, upstreams, límites (SNI-38) |
| `nginx/validate-env.sh` | `nginx_env_check` | ambos | Valida hostname y puerto antes de arrancar |
| `nginx/templates/redirect.conf.template` | `nginx_redirect` | ambos | Puerto 80: `/healthz` interno, ACME y 308 |
| `nginx/templates/tls.conf.template` | `nginx_tls` | HTTPS | Puerto 443: certificado, TLS 1.2/1.3, rutas |
| `nginx/templates/routes.conf.template` | `nginx_routes` | HTTPS | Rutas y headers de SNI-38, en un solo lugar |
| `nginx/templates/ingress.conf.template` | — | local | HTTP de desarrollo en `localhost:8088`; incluye las mismas rutas |

`swarm/stack.ingress.yaml` define el estado HTTP. `swarm/stack.tls.yaml` agrega el
443, las dos configs TLS y los certificados; el renderer de SNI-43 lo suma sólo con
`tls: true`. El despliegue se niega a publicar el 443 si en la VM no existen
`fullchain.pem` y `privkey.pem` del hostname.

## Certificados y permisos

| Ruta en la VM | Dueño / modo | Quién la ve |
| --- | --- | --- |
| `/var/lib/snippet-searcher/<env>/letsencrypt` | root, 0700 | Sólo el contenedor de Certbot (cuenta, renovación, `live/`, `archive/`) |
| `.../letsencrypt/live` y `.../archive` | root, 0700 | NGINX, en **solo lectura** |
| Volumen `snippet-searcher-<env>_ingress_acme` | root | Certbot escribe el desafío; NGINX lo lee en solo lectura |

NGINX nunca monta la cuenta ACME ni `renewal/`. Los certificados no se hornean en
imágenes ni van a Git o Linear. Sólo root lee la clave privada: el master de NGINX
la carga al arrancar o recargar.

## Certbot

`scripts/certificates.py` corre `certbot/certbot:v5.8.0` fijado por digest como
contenedor de una sola ejecución (`docker run --rm`), sin `docker.sock`. Se usa con
`sudo` desde el checkout de infra en la VM:

| Orden | Qué hace |
| --- | --- |
| `issue <env> --staging` | Emite con la autoridad de prueba. No es un certificado válido |
| `issue <env>` | Emite el certificado confiable. Si había uno de staging, lo reemplaza una vez; si ya hay uno de producción, se niega |
| `renew <env>` | Renueva si hace falta; si el certificado cambió, recarga NGINX |
| `renew <env> --dry-run` | Prueba la renovación contra staging sin guardar nada |
| `reload <env>` | `nginx -t` + `reload` y comprueba que se sirve el certificado del disco |
| `status <env>` | Emisor y **vencimiento real** del archivo, y si NGINX sirve ese mismo certificado |

Todas toman el mismo `deploy.lock` que los despliegues y no hacen nada si hay un
`pending.json`. La recarga ocurre dentro de la tarea NGINX en ejecución: no
redespliega ni reinicia aplicaciones, no cambia digests ni datos. Si `nginx -t`
falla, no se recarga y el proxy sigue sirviendo la configuración anterior.

Al emitir, Certbot usa `--agree-tos`: quien ejecuta `issue` acepta el Subscriber
Agreement de Let's Encrypt en nombre del equipo. La cuenta no tiene email
(`--register-unsafely-without-email`): Let's Encrypt ya no manda avisos de
vencimiento, y el vencimiento se vigila con el timer y `status`.

## Renovación periódica

`scripts/install_certificates.sh <env>` se ejecuta una vez por VM. Crea la carpeta
de certificados, copia `certificates.py` y `stack_release.py` a
`/usr/local/lib/snippet-searcher/` (root) e instala
`systemd/snippet-certificates@.service` y `@.timer`. El timer se habilita
**después** del primer certificado de producción:

| Disparo | Por qué |
| --- | --- |
| `OnCalendar` 03:00 y 15:00, con hasta 1 h al azar | Una renovación cada 12 h sin pegarle a Let's Encrypt todos a la misma hora |
| `OnBootSec=10min` | Comprobación al volver a encender la VM |
| `Persistent=true` | Si la VM estuvo apagada en un horario, corre al arrancar |

Correr `renew` cada 12 h no pide un certificado nuevo cada vez: Certbot sólo renueva
cuando el vencimiento se acerca, según su criterio por defecto. No se asume una
duración fija de 90 días: `status` lee la fecha real.

## Decisiones aprobadas

Juan aprobó el 25/10/2026, con «si», las nueve primeras recomendaciones del plan.
La décima la definió Juan Francisco ese mismo día: la primera instalación de NGINX
en Azure la hace SNI-40, sin UI, y después SNI-42 incorpora la UI. Juan respondió
«yo configuro nginx».

| # | Elección | Motivo y ventaja | Alternativa descartada y costo aceptado |
| --- | --- | --- | --- |
| 1 | Dos estados, HTTP y HTTPS | Cumple «no arrancar TLS sin archivos» sin certificados falsos | Un autofirmado provisorio expondría un certificado falso; `--standalone` dejaría la renovación con otro método. Exige dos despliegues de infraestructura |
| 2 | El 80 sólo sirve ACME, `/healthz` y redirect | La API nunca queda en HTTP plano; cierra el riesgo de la identidad de dev | Mantener el 80 de SNI-38. El ingreso local sigue en HTTP para desarrollo |
| 3 | Redirect 308 | Conserva método y body, igual que `/api` → `/api/` | 301 convierte un POST en GET sin avisar |
| 4 | Certificados en una carpeta del host; NGINX ve sólo `live/` y `archive/` | NGINX no ve la cuenta ACME | Un volumen entero visible para NGINX. Es un bind mount que tiene que existir en la VM (lo crea el instalador) |
| 5 | Certbot por `docker run --rm` fijado por digest | Una ejecución por vez, sin `docker.sock` ni réplica permanente | Servicio Swarm en bucle o Certbot por apt/snap. Actualizar la versión exige revisar el digest |
| 6 | systemd timer con `Persistent` y `OnBootSec` | Cubre la comprobación al encender; los fallos quedan en `systemctl` y `journalctl` | cron + `@reboot` |
| 7 | Recarga bajo el mismo `deploy.lock` | No pisa un despliegue en curso | `docker service update --force` reinicia la tarea |
| 8 | Staging primero; producción una sola vez | Prueba la recarga con un cambio real de certificado sin pedidos de producción de más | Forzar renovaciones de producción gasta los límites de Let's Encrypt |
| 9 | Cuenta ACME sin email | No hay avisos útiles por mail; no se registra un dato personal | Un email del equipo; se puede agregar después |
| 10 | SNI-40 instala NGINX primero, sin UI | La UI se incorpora a un ingreso HTTPS ya listo | Esperar a SNI-42 bloquearía la emisión |

## Procedimiento por ambiente

Una VM encendida a la vez, como indica SNI-20. Dev se hizo el 26/10/2026; prod sólo
después de pasar infra y los callers a `main` por PR. Los comandos van por SSH con la
clave propia, dentro de un checkout de infra en la revisión revisada, igual que
[SNI-43](sni-43-cd.md). `<host>` es `jjt-snippets-dev.duckdns.org` o
`jjt-snippets-prod.duckdns.org`; `<registro>` es
`/home/azureuser/.local/state/snippet-searcher/<env>/release.json`.

**Requisitos previos:**

* El CD central v0.6.0 fija infra `27e060d`, anterior a SNI-40, y rechaza un registro
  con `tls`. github-workflows v0.6.1 fija infra `9f7eee8`, y los callers de
  snippets, permissions y printscript (y ui, si está instalada) usan `@v0.6.1` en la
  rama del ambiente. El control de corte lo exige.
* Los últimos deploys del CD de esos repos terminaron en verde **con la VM encendida**.
  Con la VM apagada fallan con `Connection timed out` por SSH, sin tocar nada.
* El checkout de la VM incluye el fix #24 (revisa la configuración también después de
  la convergencia).
* Para prod, los callers llegan a `main` por una release. **El CD de prod sólo despliega
  si `main` recibió un PR cuya rama de origen es `dev`**; un PR desde otra rama llega a
  `main` pero la VM rechaza el deploy sin tocar nada. Como las releases anteriores
  fueron squash, `main` y `dev` chocan: se crea `release/sni-40-main` desde `dev` con
  `git merge -s ours origin/main` (`git diff origin/dev` vacío), se mergea a `dev`, y
  recién después se abre el PR `dev` → `main`. Si GitHub pide actualizar la rama, usar
  **Update branch** con merge, nunca con rebase.

Pasos:

1. **Preparar:** `sudo -n bash scripts/install_certificates.sh <env>`.
2. **Sacar los puertos de las apps, de a una.** Si el corte se los saca a las tres a la
   vez, Swarm levanta seis Spring Boot juntos (`start-first`), no llegan sanos al
   healthcheck y hace rollback. Por cada app, bajo el lock:
   `sudo -n flock -w 60 <estado>/deploy.lock docker service update --detach=false --publish-rm 8080 snippet-searcher-<env>_<app>`,
   y comprobar `"State":"completed"` y puertos `null` con `docker service inspect`.
3. **Ingreso HTTP:** `plan <registro> --nginx-host <host> > candidate-http.json`,
   `check`, respaldar el registro y `sudo -n python3 -B scripts/bootstrap_swarm.py deploy candidate-http.json --infrastructure`.
   La salida va a `logs/infrastructure.log`: confirmar con `echo $?` y el `PASS proxy HTTP` del log.
4. **Puertos publicados desde la propia VM:** `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1/healthz`
   da 200. Si da `000`, Swarm no reprogramó el ingress (cadena `DOCKER-INGRESS` vacía):
   `docker service update --detach=false --force snippet-searcher-<env>_nginx` bajo el lock.
5. **Red:** en dev, `AllowPublicHttp` (305) abre TCP 80 a cualquier origen y
   `AllowTeamWeb` (310) queda sólo en 443. Prod tiene 80 y 443 abiertos desde SNI-39.
6. **Desde afuera:** `curl -sS -o /dev/null -w '%{http_code} %{redirect_url}\n' http://<host>/api/snippets` da `308 https://<host>/api/snippets`.
7. **Staging:** `sudo -n python3 -B scripts/certificates.py issue <env> --staging`.
8. **Ingreso HTTPS:** el mismo `plan` con `--tls`, `check`, respaldo y `deploy --infrastructure`.
   Repetir el paso 4 también para 443 (`curl -sk --resolve <host>:443:127.0.0.1 https://<host>/healthz`).
9. **Producción:** `sudo -n python3 -B scripts/certificates.py issue <env>`. Recarga NGINX
   y comprueba que sirve el certificado nuevo.
10. **Desde afuera, sin `-k`:** `curl -sv https://<host>/healthz` con `SSL certificate verify ok` y 200.
11. **Timer:** `sudo -n systemctl enable --now snippet-certificates@<env>.timer` y una
    corrida real con `sudo -n systemctl start snippet-certificates@<env>.service`;
    `sudo -n journalctl -u snippet-certificates@<env>.service` muestra el resultado.
12. **Renovación y recarga, por separado:** `renew <env> --dry-run`, `reload <env>` y `status <env>`.
13. **Reinicio del proxy:** guardar `docker service ls` (nombre e imagen), forzar sólo la
    tarea NGINX, confirmar con `status` que sirve el mismo certificado y que la lista
    de imágenes no cambió.

## Recuperación y diagnóstico

| Situación | Qué pasa | Qué hacer |
| --- | --- | --- |
| Configuración NGINX inválida en un despliegue | Swarm hace rollback de la tarea; el comando de infraestructura reconcilia y queda en rojo | Corregir, nueva revisión de config, repetir `plan`/`deploy` |
| `nginx -t` falla durante una recarga | No se recarga; sigue el certificado y la configuración anteriores | `reload <env>` muestra el error; el timer queda `failed` |
| Renovación fallida | Se conserva el certificado vigente; el comando sale con error e informa el vencimiento | `journalctl -u snippet-certificates@<env>.service`, corregir red/DNS y `renew <env>` |
| VM desasignada | Ningún scheduler corre; no hay encendido automático | Al encender, `OnBootSec`/`Persistent` renuevan; revisar con `status` |
| Certificado vencido tras mucho tiempo apagada | Los navegadores muestran error hasta renovar | `renew <env>`: Certbot renueva certificados vencidos |
| Se perdió la carpeta de certificados | El estado HTTPS no arranca: falta el archivo | Volver al estado HTTP (`plan` sin `--tls`), emitir y volver a HTTPS. Cuidar los límites de Let's Encrypt |
| Swarm hace rollback al sacar puertos de las apps | Las apps vuelven a publicar 8080–8082; desde el fix #24 la operación falla en vez de confirmarse | Sacar los puertos de a una app (paso 2) y repetir el corte |
| Los puertos publicados no responden ni desde la VM | NGINX sano por la red interna, pero `DOCKER-INGRESS` sin reglas `DNAT` | Forzar la tarea NGINX (paso 4); no hace falta reiniciar Docker |

Para diagnosticar: `systemctl list-timers 'snippet-certificates@*'`,
`systemctl status snippet-certificates@<env>.service` y
`sudo -n python3 -B scripts/certificates.py status <env>`.

## Verificación local

```bash
python3 -B -m unittest discover -s scripts -p 'test_*.py'
python3 -B scripts/validate_nginx_config.py
python3 -B scripts/validate_expanded_stack.py
python3 -B scripts/verify_https.py
python3 -B scripts/verify_nginx.py
```

`verify_https.py` levanta NGINX real con una CA descartable y la misma estructura de
`live/` y `archive/` que Certbot. Prueba:

* El 80 sirve sólo `/healthz`, ACME (GET) y 308 con URI y query intactas, y un POST por HTTP nunca llega a la API.
* El 443 tiene cadena y hostname verificados sin `-k`, TLS 1.2 y 1.3, rutas con `X-Forwarded-Proto: https`, y rechaza un SNI desconocido.
* Una renovación se sirve tras `nginx -t` y `reload` en el mismo contenedor.
* Reiniciar el proxy conserva el certificado.

Los tests unitarios cubren las reglas del registro, el plan `--tls`, el rechazo sin
certificado, los puertos por estado y las reglas de `certificates.py`.

Verificado el 26/10/2026 con Docker 29.7.2, Compose 5.3.1 y Python 3.14: 179 tests,
todos los validadores y las dos aceptaciones con NGINX real. Las pruebas mutadas sin
`ssl_reject_handshake` y con 301 en lugar de 308 fallaron, como debían.

## Evidencia

26/10/2026, por Juan Rudolph. dev con infra `0481274`; prod con infra `45aa45c` (`main`,
mismo contenido). Horas en UTC (Argentina = UTC−3).

| Comprobación | dev | prod |
| --- | --- | --- |
| Puertos de apps retirados de a uno | `completed`, puertos `null` en las tres; ver Incidentes | `converged` en las tres, sin rollback, antes del corte |
| Ingreso HTTP y 308 desde afuera | Desplegado 14:08; `308 https://<host>/api/snippets?q=a` desde la IP del equipo y desde Cloud Shell; 443 con timeout para la IP ajena | `salida=0` y `PASS proxy HTTP`; `local80 200` desde la VM; `308 https://<host>/api/snippets?q=a` desde afuera |
| Certificado staging | `(STAGING) Baloney Bulgur YE2`, vencía el 29/12/2026 (64 días) | `(STAGING) Baloney Bulgur YE2`, vencía el 29/12/2026 15:57:31 GMT |
| Certificado de producción | Let's Encrypt `YE1`, vence el 24/01/2027 13:55:41 GMT; reemplazó a staging una sola vez | Let's Encrypt `YE2`, vence el 24/01/2027 16:07:19 GMT; emitido 17:05, reemplazó a staging una sola vez |
| HTTPS sin `-k` | 200, `SSL certificate verify ok`, `CN=jjt-snippets-dev.duckdns.org` | 200, `SSL certificate verify ok`, `CN=jjt-snippets-prod.duckdns.org` |
| `renew --dry-run` | `all simulated renewals succeeded` | `all simulated renewals succeeded` |
| Recarga real | `nginx -t` correcto, reload y certificado servido igual al del disco, sin reiniciar tareas (en `issue` y en `reload`) | Igual que dev, en `issue` (17:05) y en `reload` (17:13) |
| Reinicio del proxy | Tarea forzada; `status` confirma el mismo certificado | Tarea forzada; `local443 200` y `status` confirma el mismo certificado |
| Timer | Habilitado; corrida real por systemd a las 15:00:14, `status=0/SUCCESS`, `not yet due for renewal` | Habilitado; corrida real por systemd a las 17:07:35, `status=0/SUCCESS` |
| Digests de aplicaciones | Sin cambios antes y después del reinicio del proxy | `IMAGENES-IGUALES` antes y después del reinicio del proxy |
| Verificación completa del registro | `Swarm.verify` con el fix #24: configuración, 60 s estable, SQL, HTTP y redirect correctos | Hecha por los dos `deploy --infrastructure` (fix #24 incluido): `PASS proxy HTTP` y `PASS proxy y rutas internas por TLS` |

### Incidentes de dev

1. **Rollback de las apps al sacarles los puertos (14:08–14:10).** El primer corte
   actualizó las tres apps a la vez. Las tareas nuevas quedaron `unhealthy` y Swarm
   hizo rollback, devolviendo 8080–8082. La operación se confirmó igual, porque la
   configuración se revisaba antes de la convergencia. Se corrigió con el PR #24 y se
   retiraron los puertos de a una app (14:31–14:40). No hubo exposición: el NSG
   bloquea esos puertos.
2. **Ingress sin reprogramar tras publicar 443.** NGINX respondía por la red interna,
   pero 80 y 443 daban `Connection refused` desde afuera y desde la VM. La cadena
   `DOCKER-INGRESS` estaba vacía. Se resolvió forzando la tarea NGINX, sin tocar las
   apps.

### Incidentes de prod

1. **Deploy de prod rechazado en la primera release.** El primer PR a `main` salía de
   `release/sni-40-main`. La VM respondió `Prod exige el merge de una PR de dev a main
   del mismo repositorio` y no tocó nada. Se repitió por el camino `release` → `dev` →
   `main` descrito en los requisitos previos.
2. **Ingress sin reprogramar tras publicar 443**, igual que en dev. El paso 8 lo detectó
   (`local80 000`, `local443 000`) y se resolvió forzando la tarea NGINX, antes de
   emitir el certificado de producción. El retiro previo de puertos evitó el rollback de dev.

## Coordinación

* **SNI-39:** dev quedó con `AllowPublicHttp` (80 a cualquier origen) y `AllowTeamWeb` (sólo 443).
* **SNI-42:** la UI entra al ingreso HTTPS ya preparado; el probe interno exige `/` por 443 cuando hay UI.
  Su caller tiene que pasar a `@v0.6.1` antes de instalarla.
* **SNI-41:** CORS con el origen `https://<host>`.
* **SNI-43:** el registro cambia `port` por `tls`; `plan` acepta `--tls`. El CD v0.6.1 fija
  infra `9f7eee8`, sin el fix #24. Los cortes de infraestructura se hacen con un checkout
  que sí lo incluye, y en los deploys de apps un rollback ya se detecta por el digest, así
  que publicar v0.6.2 es una mejora opcional.
* **SNI-44:** verifica el ingreso completo desde afuera, incluida la cadena pública.

El probe interno de despliegue no valida la cadena pública: usa TLS sin verificar
para comprobar ruteo, porque en el paso 8 el certificado todavía es de staging. La
cadena se verifica desde afuera, sin `-k`.

Fuentes: material de clase «07-reverse-proxy» (págs. 4–7) y «06-https» (págs. 19–40),
[nginx-docker 8fe0fbf](https://github.com/austral-ingsis/nginx-docker/tree/8fe0fbfeaa9f597835b83266af10908ad88f77f2),
[Certbot: webroot, renovación y hooks](https://eff-certbot.readthedocs.io/en/stable/using.html),
[HTTP-01](https://letsencrypt.org/docs/challenge-types/).
