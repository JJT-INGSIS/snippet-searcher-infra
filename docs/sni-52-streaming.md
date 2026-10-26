# SNI-52 — Transporte incremental por NGINX y CORS

## Alcance y fuente de verdad

El contrato [SNI-45](architecture/execution-contract.md) y sus
[fixtures v1](contracts/execution-v1.json) definen fetch streaming + NDJSON,
cursor `after`, POST separados de input/cancel y límites. No se cambia ese protocolo.
La UI contacta sólo a Snippets; PrintScript permanece interno.

**La aceptación local demuestra transporte con NGINX real y un upstream HTTP
controlado. No ejecuta PrintScript ni acredita autorización de sesiones,
cancelación efectiva de workers o integración funcional US9/10.** Los proveedores
reales se verifican después en SNI-47/48/49/51/53; el ingreso público, en SNI-44.

## Configuración y decisiones aprobadas

Juan Francisco aprobó este plan el 25/10/2026, con las precisiones de seguir
exactamente las rutas/métodos de SNI-45 y separar transporte de intérprete real.
Implementación y validación local: 26/10/2026.

| Elección | Motivo y costo aceptado | Alternativa y revisión |
| --- | --- | --- |
| `proxy_buffering off` y `gzip off` sólo en `/api/executions/` | Entrega incremental y mapeo por prefijo sencillo, sin regex ni duplicar forwarding. Los pequeños descriptores/POST de esa familia también usan respuesta sin buffering | Desactivarlo globalmente cambia otras respuestas. Una location regex sólo para events exige otro tratamiento de URI; revisar si esa familia incorpora respuestas grandes |
| Mantener `proxy_read_timeout 60s` y heartbeat de contrato cada 10s | Acota silencios sin confundirlos con el deadline de ejecución (120s, responsabilidad del backend) | Aumentar el timeout ocultaría productores sin heartbeat. Los cambios de límites requieren coordinación con SNI-45 y backend |
| CORS por ruta/método en Spring | Conserva una política única, sin wildcard de rutas/métodos/orígenes ni headers especulativos | Un permiso global es más corto, pero amplía acceso cross-origin. Cambiar el contrato exige actualizar policy, pruebas y documentación |

`nginx/templates/routes.conf.template` es compartido por el HTTP **local** y el
servidor HTTPS de SNI-40. Se conserva la redirección pública HTTP, ACME, certificados,
SPA, hosts canónicos y saneamiento de forwarding. `/api/executions/...` se traduce a
`/executions/...` una sola vez, conservando query/body/método y headers.

La caché de proxy y los reintentos ya estaban deshabilitados y se conservan; no se reenvían
automáticamente inicios, inputs ni cancelaciones. El servidor debe emitir
`Content-Type: application/x-ndjson` y hacer flush. El ingreso impone una sola
cabecera `Cache-Control: no-store` en esta familia, incluidos errores, reemplazando
la del upstream para impedir caché de sesiones privadas también en el navegador.
NGINX no genera heartbeats, no transforma eventos y no inventa un terminal al cerrar
una conexión. Cerrar HTTP no demuestra cancelación del trabajo.

El cliente debe ensamblar líneas NDJSON y UTF-8 entre lecturas; un chunk no equivale
a un evento. El cursor viaja en `after`, no en `Last-Event-ID`. No se agregan SSE,
WebSockets, Upgrade ni broker.

La política CORS exacta vive en [Snippets](https://github.com/JJT-INGSIS/snippets-service/blob/dev/docs/cors.md).
Incluye las ocho operaciones públicas de SNI-45 (tests, inicios y sesiones), no
el POST `/executions` interno de PrintScript. Autorizar preflight no implementa
endpoints ni autoriza acceso a snippets/sesiones. Origin vacío por configuración
continúa sin grants; identidad dev sigue deshabilitada en prod.

## Verificación automática

Desde infra, con Docker Linux local:

```bash
python3 -B -m unittest discover -s scripts -p 'test_*.py' -v
python3 -B scripts/validate_nginx_config.py
python3 -B scripts/validate_expanded_stack.py
python3 -B scripts/verify_nginx.py
python3 -B scripts/verify_https.py
```

La suite completa requiere Linux/flock. HTTPS usa OpenSSL y enlaces simbólicos;
ejecutar esa prueba en Linux/macOS o en el runner Ubuntu de CI. El verifier HTTP
tarda unos tres minutos: incluye un stream de 70s con heartbeat cada 10s y el timeout
real de 60s sin datos. Ambos verificadores se ejecutan en el CI existente.

`verify_execution_stream.py` comparte las aserciones entre HTTP y HTTPS. El upstream
de prueba espera un POST antes del terminal: acumular todo hasta el final hace
fallar el test. También se comprueban cursor/Unicode, identidad/body, input/cancel
sin reintentos, errores previos al stream y EOF sin terminal. El test largo prueba
que el timeout mide inactividad; el deadline total sigue siendo del backend.

En Snippets: `./gradlew build` prueba todas las combinaciones de rutas/métodos
permitidos, rechazos, orígenes y perfiles. No se incorporan endpoints de ejecución
ficticios al código productivo. En rutas inexistentes, comprobar ausencia de grants:
un OPTIONS 200 sin Access-Control-Allow-Origin no es permiso del navegador.

## Navegador real (opcional, reproducible)

1. En infra ejecutar `python scripts/verify_nginx.py --browser`. Arranca sólo NGINX
   y upstreams de transporte en un proyecto aleatorio, puerto localhost libre, sin
   leer `.env` ni modificar el Compose habitual. Anotar `http://localhost:PUERTO`.
2. Arrancar Snippets real con su procedimiento local habitual (ver su README),
   perfil dev, puerto 18083 y `SNIPPETS_CORS_ALLOWED_ORIGINS=http://localhost:PUERTO`.
   No incluir 127.0.0.1 en esa allowlist: es el origen negativo. No hace falta
   tener implementadas las sesiones; se comprueba que sus errores sean legibles.
3. Desde UI, con sus dependencias existentes, copiar la spec temporalmente:

```powershell
$spec = 'cypress/e2e/backend/sni52-transport-local.cy.js'
if (Test-Path -LiteralPath $spec) { throw 'La spec temporal ya existe' }
Copy-Item ../snippet-searcher-infra/tests/nginx/execution.cy.js $spec
try {
    npx cypress run --spec $spec --config "specPattern=cypress/e2e/backend/**/*.cy.js,baseUrl=http://localhost:PUERTO,chromeWebSecurity=true" --env backend=http://127.0.0.1:18083
    if ($LASTEXITCODE -ne 0) { throw 'Falló la aceptación de navegador' }
} finally {
    Remove-Item -LiteralPath $spec
}
```

Reemplazar PUERTO. Son tres casos: consumo incremental por proxy/input concurrente,
CORS real de Spring con errores legibles y métodos/headers rechazados, y bloqueo
desde otro origen. Sin `cy.intercept` ni desactivar la seguridad del navegador.
La fixture UI es sólo una página de transporte; no acredita la UI funcional completa.
Al terminar, Enter/Ctrl+C en el verifier retira sólo su proyecto; detener también
el proceso local de Snippets. La UI del equipo no necesita modificaciones.

## Diagnóstico y aplicación posterior

Comparar GET interno `/executions/{id}/events?after=...` con el público
`/api/executions/{id}/events?after=...`, usando un ID real y headers de acceso
válidos. `curl -N` evita el buffering del cliente; observar eventos antes del terminal.
Si el salto interno también acumula, revisar flush/lectura incremental del backend
y Language (SNI-47/48/49), no aumentar límites de NGINX ni abrir CORS para ocultarlo.
La prueba de navegador sigue siendo necesaria: curl no aplica CORS.

SNI-40 mantiene la instalación TLS en Azure; este ticket no abre puertos ni activa
NGINX/UI en las VMs. Tras integrar infra, usar un checkout revisado y fijo que incluya
SNI-40/52, planificar desde el release vigente y versionar `nginx_routes` con el
procedimiento SNI-43/40. Conservar digests de apps, proveedor/datos y estado TLS;
no editar configs inmutables existentes, no hacer stack rm ni redeployar apps para
cambiar el proxy. El nuevo CORS requiere integrar/construir Snippets normalmente.

Coordinar con Juanchi archivos compartidos y compatibilidad del pin de herramientas
central antes del rollout. Este ticket conserva formato/inventario y no publica
una versión nueva del central ni sobrescribe tags. Verificar siempre la revisión
real que ejecuta Actions; editar infra/dev no la cambia automáticamente.

Pendiente posterior: repetir con Snippets/Language/PrintScript reales y navegador
por el dominio HTTPS, cuando se entreguen sus implementaciones y acceso de equipo.
No usar estas fixtures para afirmar cancelación efectiva, límites globales, permisos
de sesiones, recuperación del intérprete ni funcionalidad completa en prod.
