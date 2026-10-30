# SNI-53 — Aceptación de US8–10 con UI, intérprete y permisos reales

Verifica crear tests (US8), ejecutarlos (US9) y ejecutar código de forma
interactiva (US10) con Snippets, Permissions, PostgreSQL, storage `local`,
PrintScript, NGINX y la UI reales, sin proveedores falsos.

**Estado: aceptación funcional local cumplida.** La primera corrida del 30/10/2026
dio 13/15 y encontró dos bugs (A y B). Se arreglaron el mismo día y la corrida
final dio **15/15** (ver [Corrida final](#corrida-final--1515)). Quedan
pendientes HTTPS remoto y prod, fuera de esta aceptación local.

## Alcance

| Incluido | Fuera de alcance |
| --- | --- |
| Compose local con perfiles `ui` e `ingress`: el navegador y el script entran por NGINX (`localhost:8088`) | HTTPS en las VMs y verificación en prod: las VMs están apagadas (decisión 4) |
| Storage `local`, el habilitado en todos los ambientes (ver [SNI-44](sni-44-acceptance.md)) | Asset/Azurite, Auth0, Redis, lint, formato, US11–16 |
| Identidad de desarrollo (`X-Dev-Actor-Id`), solo en local | Identidad de dev en prod |

## Decisiones

Propuestas en el plan de SNI-53 y aprobadas por Juan el 30/10/2026 («vamos con
tus recomendaciones»).

| # | Decisión | Alternativa descartada | Beneficio | Costo aceptado |
| --- | --- | --- | --- | --- |
| 1 | Script Python sin dependencias para la matriz + checklist de navegador | Todo a mano; todo con Cypress | Repetible, cumple las ventanas de 15 s/30 s, deja JSON de evidencia | ~600 líneas para mantener |
| 2 | Script y doc en infra | En snippets-service | La prueba cruza 4 servicios, UI y NGINX; infra tiene Compose y la aceptación de SNI-44 | PR en un repo compartido |
| 3 | "Output antes del final" con la pausa real de `readInput` (US10) y orden de eventos en US9 | Agregar una pausa a PrintScript; medir tiempos | Espera real por todo el camino PrintScript → Snippets → NGINX → navegador | En US9 no se ve una espera: PrintScript 1.1 no tiene loops ni pausas |
| 4 | HTTPS remoto y prod quedan pendientes | Prender las VMs | Sin costo de créditos | Falta la prueba por HTTPS; queda en SNI-52 |
| 5 | Los bugs van a tickets aparte; SNI-53 queda abierto hasta una corrida verde | Arreglarlos dentro de SNI-53 | La aceptación no cambia código | Más tickets |

## Cómo repetirlo

Con los repos hermanos en `dev` y desde la raíz de infra:

```sh
UI_DEV_ACTOR=dev-juan docker compose --profile ui --profile ingress up -d --wait
COMPOSE_PROFILES=ui,ingress python3 -B scripts/verify_us8_10.py --output /tmp/sni53.json
python3 -B -m unittest discover -s scripts -p 'test_*.py'
```

El script tarda unos 4 minutos y no se debe usar la UI mientras corre:

- Reinicia, mata y recrea contenedores, **sin borrar volúmenes**.
- Crea sus propios actores (`sni53-…`) y snippets, y comparte con `dev-ana`.
- De `.env` solo lee la contraseña de la base, para comprobar que no aparezca en ningún resultado. Nunca la imprime.
- Con `SNI53_BASE_URL` se puede apuntar a otro ingreso.

## Matriz y resultados — 30/10/2026

Versiones probadas:

| Repo | Commit |
| --- | --- |
| snippets-service | `f6108c1` |
| permissions-service | `46e7af3` |
| printscript-service | `2fb2928` |
| snippet-searcher-ui | `3ce356d` |
| snippet-searcher-infra | `02374d5` |

El JSON de la corrida guarda además los IDs de las imágenes; por ejemplo,
Snippets `sha256:91a530a1…` y PrintScript `sha256:3988b153…`.

### Script: 13/15

| # | Caso | Resultado |
| --- | --- | --- |
| 1 | Definiciones exactas: pasa, falla, duplicados, vacíos, `ñ 🌎`, inputs de menos | ✅ Se listan exactas y en orden |
| 2 | Compartir con B (`dev-ana`); C sin acceso; test de otro snippet | ✅ B lista y ejecuta (PASSED) pero no crea (`403`); C recibe `404` en tests, detalle y las dos ejecuciones; test ajeno `404` |
| 3 | Ejecutar tests | ✅ PASSED, FAILED, PASSED con vacíos/Unicode, `INPUT_EXHAUSTED` sin comparación, `PROGRAM_ERROR` sin comparación |
| 4 | Interactivo y dueño de la sesión | ✅ `Antes` llega antes del pedido de input; otro actor recibe `403` en descriptor, eventos, input y cancelar; repetir el input da `200`, otro valor `409`; auditoría `INTERACTIVE`, sin test, 0 outputs, reserva liberada |
| 6 | Editar el snippet mientras corre | ✅ Sale `v1`/`v1 Ana` (la foto vieja), el `codeHash` no cambia y el snippet queda en `v2` |
| 5 | Cupo por actor y Stop | ✅ Segunda ejecución `409`; Stop da `CANCELLED`, libera la reserva y se puede volver a ejecutar |
| 5 | Límite global (4) | ❌ **Bug A**: la 5.ª da `503` en vez de `429` |
| 9 | `readEnv` de `PATH` y de `SNIPPETS_DB_PASSWORD` | ✅ `PROGRAM_ERROR` con `ENVIRONMENT_VARIABLE_NOT_FOUND`, sin output; el secreto no aparece |
| 5 | Salida excesiva (>1 MiB) | ✅ `LIMIT_EXCEEDED`, motivo `event-buffer-exceeded` |
| 5 | Espera de input vencida | ✅ `LIMIT_EXCEEDED`, motivo `input-wait-timeout`, a los 30 s; reserva liberada |
| 5 | Sin navegador | ✅ PrintScript cancela a los 15 s; la recuperación guarda `CANCELLED` y libera |
| 3 | PrintScript caído | ⚠️ El inicio da `503 dependency-unavailable` y un actor nuevo ejecuta cuando vuelve. ❌ **Bug B**: el actor del inicio fallido queda bloqueado |
| 5 | Reinicio ordenado de PrintScript | ✅ No se presenta como completado; resultado desconocido y reserva liberada |
| 5 | PrintScript muere de golpe | ✅ Igual que el reinicio |
| 7 | Recrear bases y servicios sin borrar volúmenes | ✅ Tests y resultados guardados sin cambios; la sesión activa queda interrumpida y no se reanuda |

### Navegador

Hecho con `prueba1` (código con `println` + `readInput`), compartido con `dev-ana`.

| # | Qué | Actor | Resultado |
| --- | --- | --- | --- |
| 8 | Output antes del final | A | ✅ `Antes` visible con "Esperando input"; después `Hola, Ana` y Completado |
| 5 | Stop | A | ✅ "Cancelación confirmada", motivo `actor-cancelled` |
| 6 | Editar mientras corre | A | ✅ Salió la versión vieja, con el aviso "Resultado de la versión guardada al iniciar" |
| 1/3 | Tests desde el modal | A | ✅ Un test aprobado (outputs `Antes` y `Hola, Ana` en dos campos) y uno con diferencias |
| 8 | Limpieza al cambiar de snippet | A | ✅ La sesión abandonada quedó `CANCELLED` en el servidor. Ver la observación 3 |
| 2 | Lectura compartida | B | ✅ `prueba1` como Compartido; tests en solo lectura, sin "Nuevo test", edición y compartir deshabilitados |
| 2/3 | Ejecutar como compartido | B | ✅ Test aprobado y ejecución interactiva completa |

## Bugs encontrados

### A — Nombre distinto para el cupo global (printscript-service)

PrintScript rechaza la 5.ª ejecución con `429` y el tipo
`execution-capacity-exceeded` (`ExecutionRegistry`). El
[contrato](architecture/execution-contract.md) dice
`execution-capacity-exhausted`. Snippets no reconoce el nombre y responde
`503 dependency-unavailable`, así que el usuario ve "servicio no disponible"
cuando el sistema está lleno. No deja reservas tomadas.

**Arreglado** en printscript-service PR #26 (`fix/capacity-exhausted-name`): usa
el nombre del contrato, y el test de capacidad verifica el rechazo exacto.

### B — Un inicio fallido bloquea al actor (snippets-service)

Si alguien ejecuta mientras PrintScript está caído o arrancando, el cliente de
ejecución marca el error de conexión como "incierto". Snippets conserva la
reserva sin asociación y la recuperación no la libera. Ese actor recibe
`409 execution-already-active` en cada intento siguiente, hasta que alguien la
libere a mano en la base.

Una conexión rechazada prueba que el pedido no llegó, así que no hay
incertidumbre.

**Arreglado** en snippets-service PR #50 (`fix/start-connect-failure`) con la
opción B1, aprobada por Juan el 30/10/2026. Alternativas descartadas: liberar
reservas viejas sin asociación, que podía liberar un programa que sí corría, e
inicio idempotente, que cambia el contrato y dos servicios. Ahora una conexión
rechazada o un timeout de conexión son fallas seguras y la reserva se libera. Un
timeout **después** de enviar sigue siendo incierto, como define SNI-48.

## Corrida final — 15/15

30/10/2026 22:46 UTC, mismo script y mismos comandos, después de mergear los dos
arreglos.

| Repo | Commit |
| --- | --- |
| snippets-service | `7092414` |
| permissions-service | `46e7af3` |
| printscript-service | `ed6a686` |
| snippet-searcher-ui | `3ce356d` |
| snippet-searcher-infra | `c3398b0` |

Los 15 casos pasaron. Los dos que antes fallaban:

| Caso | Antes | Ahora |
| --- | --- | --- |
| 5 límite global | 5.ª ejecución `503` | `429 execution-capacity-exhausted`; las 4 activas se cancelan y la 5.ª ejecuta después |
| 3 PrintScript caído | El actor del inicio fallido quedaba bloqueado | Recibe `503`, un actor nuevo ejecuta al volver PrintScript y el actor del inicio fallido queda liberado |

Los demás casos repitieron los resultados de la primera corrida.

## Observaciones

1. **US9 sin espera visible:** un test termina en milisegundos. La entrega
   incremental se demuestra con la pausa de US10, que usa el mismo canal; en
   US9 se registra que cada output llega como un evento separado antes del
   terminal (decisión 3).
2. **Reinicio ordenado de PrintScript:** el navegador no recibe un terminal
   `INTERRUPTED`; el stream se corta. La auditoría guarda resultado desconocido
   (`execution-session-unavailable-after-restart-or-expiry`) y libera la
   reserva: nunca se presenta como éxito.
3. **Volver a un snippet después de abandonar una ejecución:** la UI muestra
   "Resultado desconocido… se solicitó cancelar" y exige "Reconectar ejecución"
   antes de ejecutar otra vez. Es lo definido en SNI-51 (no supone el resultado
   sin leerlo), aunque el servidor ya la tenía cancelada.
4. **Salida excesiva:** corta primero el buffer de eventos (256 KiB) y no el
   límite de 1 MiB. El resultado es igual `LIMIT_EXCEEDED`, sin sesiones colgadas.
5. **PrintScript sin healthcheck en Compose:** `up --wait` vuelve antes de que
   el servicio atienda. El script espera a que valide código antes de seguir.
6. **Datos de prueba:** cada corrida deja snippets y tests de actores `sni53-…`
   en la base local. No se usan en dev ni en prod.

## Pendiente

- [x] Arreglar el bug A (printscript-service #26) y el bug B (snippets-service #50).
- [x] Repetir el script hasta 15/15 y agregar esa corrida acá.
- [ ] HTTPS remoto y prod: anotarlo en SNI-52 cuando se enciendan las VMs.
- [ ] SNI-37: marcar cumplida la parte de tests; lint sigue pendiente.
