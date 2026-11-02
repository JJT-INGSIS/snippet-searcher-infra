# SNI-56 — Verificación en dev

Fecha: 02/11/2026, America/Buenos_Aires. Ambiente: exclusivamente `vm-snippet-dev`.
El usuario autorizó crear el secreto y volumen de Redis y reemplazar Snippets y
PrintScript mediante stop-first, aceptando una breve interrupción. Producción y
los callers main no se modificaron.

## Implementación y CD

- [Infra #38](https://github.com/JJT-INGSIS/snippet-searcher-infra/pull/38):
  commit integrado `9c8ec4d98c249a3d75dd4559e01636eddf4c8f2a`.
- [Snippets #60](https://github.com/JJT-INGSIS/snippets-service/pull/60):
  integración PostgreSQL/outbox con filesystem AOF lleno.
- [Central #12](https://github.com/JJT-INGSIS/github-workflows/pull/12):
  `v0.6.3` publicado como tag liviano desde
  `3e7d229efedb9b010b470c246afb34d840a91d6a`, fijando el SHA de infra anterior.
  Se conservó `v0.6.2` sin cambios.
- Callers dev integrados con CI aprobado: Permissions #27, PrintScript #30,
  Snippets #63 y UI #15. Snippets incorporó el avance concurrente SNI-62 y
  repitió hooks/CI; no se saltearon protecciones.

| Repositorio | CI/CD dev confirmado |
| --- | --- |
| Permissions | [41521456551](https://github.com/JJT-INGSIS/permissions-service/actions/runs/41521456551) |
| PrintScript | [41521476675](https://github.com/JJT-INGSIS/printscript-service/actions/runs/41521476675) |
| Snippets | [41522925316](https://github.com/JJT-INGSIS/snippets-service/actions/runs/41522925316) |
| UI | [41522015742](https://github.com/JJT-INGSIS/snippet-searcher-ui/actions/runs/41522015742) |

Todos finalizaron exitosamente, incluido Deploy and verify. Antes del corte se
verificaron desde la VM el pin central, los cuatro callers y la ausencia de CD
activos. El preflight observó aproximadamente 6 GiB disponibles de RAM y 20 GiB
libres en el filesystem de Docker; esos valores son una observación puntual.

## Corte y prueba remota

Se generó el candidato desde el release confirmado y se ejecutó el bootstrap
revisado mediante `--infrastructure`, con lock y journal compartidos. Operación:
`infra-199002060f9b4e1fbb491030b974d200`. Finalizó sin journal pendiente, con checks
de convergencia y SQL/HTTP aprobados. Se creó Redis y se actualizaron únicamente
Snippets y PrintScript. Ocho servicios quedaron con una réplica.

La verificación posterior, bajo el mismo lock para evitar concurrencia con CD:

- Confirmó imagen, configs, red interna, ausencia de puertos publicados,
  secretos por archivo, healthcheck, memoria/CPU y stop-first efectivos.
- Comprobó PING autenticado, rechazo NOAUTH sin credenciales y noeviction.
- No encontró el secreto ni su hash ACL en inspect o logs de Redis.
- Escribió un mensaje en un stream de prueba separado del stream de aplicación,
  creó su Consumer Group y dejó esa entrega pendiente.
- Reemplazó únicamente Redis mediante un reinicio controlado del servicio,
  conservando el volumen, y observó un contenedor nuevo saludable.
- Confirmó que tanto el mensaje como la PEL sobrevivieron por AOF. Sólo después
  confirmó la entrega de prueba; el stream se conserva como evidencia. No se
  borraron mensajes ni pendientes de aplicación.
- Confirmó que publicador, worker y activación de capacidad siguen deshabilitados.
  Instalar Redis no activa handlers ni cambia las tres excepciones de la ADR.

El puerto TCP 6379 no resultó accesible desde la estación de verificación; el
servicio además carece de publicación de puertos en Docker. Esta observación no
equivale a una auditoría completa de reglas NSG.

## Preservación comprobada

Se compararon snapshots y huellas antes del corte y después de la prueba AOF:

- Todas las imágenes existentes y sus montajes se conservaron.
- NGINX, Permissions, UI y ambas bases conservaron exactamente sus specs y task
  IDs; no se reiniciaron durante este corte. Snippets y PrintScript se reemplazaron
  de forma deliberada para aplicar su conexión/política de rollout.
- Se conservaron las configuraciones previas de infraestructura, incluido NGINX.
- Permanecieron intactas las huellas de 102 snippets, 201 ownerships y 102 archivos
  de contenido existentes. Las tablas de test cases y shares estaban vacías.
  Los probes HTTP pueden agregar sus propios fixtures; la comparación exige que
  las filas y archivos previos sigan existiendo con el mismo contenido.
- No quedó una operación pendiente y el release quedó confirmado.

Las pruebas destructivas de disco lleno/OOM y la restauración desde backup se
hicieron en contenedores/volúmenes aislados, tanto localmente como en CI, no sobre
datos de dev. El detalle operativo permanece en el [manual Redis](sni-56-redis.md).

## Límites y observación independiente

Antes de instalar Redis ya vencía por timeout el HTTPS público de dev desde esta
estación. SSH, los servicios y las verificaciones internas SQL/HTTP funcionaron.
No se considera QA externo aprobado ni se atribuye ese timeout a Redis.

Redis sigue siendo una instancia, sin HA ni garantía de pérdida cero/exactly-once.
No se promovieron features a prod, no se habilitaron workers y no se integró
Snippets #58/SNI-69, que no es dependencia de este corte.
