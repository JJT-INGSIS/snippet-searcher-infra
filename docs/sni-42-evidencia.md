# SNI-42 — UI independiente en dev y prod

Ejecución del 26/10/2026 (Argentina). SNI-40 ya había instalado NGINX/TLS;
SNI-42 incorpora `ui` al stack existente, sin instalar otro proxy de entrada.

## Identidad del artefacto

- Repositorio: `JJT-INGSIS/snippet-searcher-ui`.
- Origen dev: `bca8783dda6954b7e905faccd732e2e4e3eee3fd`.
- Árbol Git: `6746868ce7e74273a08cc08d7b358cab871f3818`.
- Digest verificado: `ghcr.io/jjt-ingsis/snippet-searcher-ui@sha256:d07e85f143e7cf7b485647a48cb534c3f211817da6dc7d44fbda22f223a8f390`.
- [CI/CD dev 40433093336](https://github.com/JJT-INGSIS/snippet-searcher-ui/actions/runs/40433093336): aprobado; Deployment `7348069736`, task `sni25:verified`, creado por `github-actions[bot]`.
- [PR UI #4, dev → main](https://github.com/JJT-INGSIS/snippet-searcher-ui/pull/4): merge `bcb63db283b77c1a6f0c0d2bd7382a52d2f6ab78`, con el mismo árbol Git.
- [CI/CD prod 40435320210](https://github.com/JJT-INGSIS/snippet-searcher-ui/actions/runs/40435320210): aprobado; selección de evidencia dev y despliegue, con publicación de imagen omitida.

Los callers usan `v0.6.1`. La instalación manual de dev usa infra
`d0c45a493d368843ee390d36ed6df8683ef4a477` corregida; la de prod,
`eb7aa13ef1d4348f4c310a7667e2621fdfe734b6`, promovida mediante
[PR infra #29](https://github.com/JJT-INGSIS/snippet-searcher-infra/pull/29).
No se sobrescribieron tags publicados.

## Comprobaciones

| Comprobación | dev | prod |
| --- | --- | --- |
| Primera instalación bajo lock, respaldo y journal | Aprobada; UI añadida al registro, sin pending | Aprobada; mismo digest e infraestructura preservada |
| CI y CD independientes de UI | Run 40433093336 aprobado | Run 40435320210 aprobado; sin reconstruir imagen |
| HTML, catálogo y listado por HTTPS | Navegador real; `/api/languages` y listado 200 | UI y catálogo 200; listado 401, incluso con actor dev |
| Navegación SPA | `/rules`, incluida recarga completa | `/rules`, incluida recarga completa |
| Configuración runtime | `dev`, actor explícito `dev-juanfran`, JSON `no-store` | `prod`, identidad deshabilitada, JSON `no-store` |
| Misma imagen entre ambientes | Digest verificado arriba | Mismo digest y hash de JavaScript servido |
| Conservación de backends, bases, storage y TLS | Comparación con respaldo inicial aprobada | Comparación con respaldo inicial aprobada |

Auditoría final: ambos recibos de UI indican `outcome: verified`, el mismo árbol
y digest; sus registros coinciden y no hay `pending.json`. Los siete servicios
permanentes de cada stack quedaron con una réplica de una. `CD_ENABLED` y
`PROD_DEPLOY_ENABLED` quedaron habilitados para los próximos cambios de UI.

El bundle `/assets/index-B0evBex7.js` tiene SHA-256
`93760fb93d7208b50ab9bd2b412c2dd6090cdf7ad9e3078627c0b7818e90e798`
en ambos dominios. La UI de prod informa que no hay identidad habilitada; no
convierte el rechazo del listado en un resultado vacío ni en autenticación ficticia.

El listado del actor elegido estaba vacío y se mostró como tal; no se generaron
snippets ficticios para aparentar contenido. `/rules` sigue informando que la
funcionalidad no está implementada. Estas pruebas acreditan despliegue/transporte,
no completan las historias pendientes de lint, tests o ejecución.

## Restauración manual y defecto encontrado

La primera instalación expuso un error previo en `stack_document`: el JSON de
Compose ya contiene `$$`, y volver a escaparlo dejaba `$$line` en los healthchecks
de Spring. Las apps respondían HTTP, pero el shell interpretaba `$$` como PID y
fallaba el healthcheck. Swarm recuperó las tareas sanas con sus mismos digests.

La [PR infra #28](https://github.com/JJT-INGSIS/snippet-searcher-infra/pull/28)
elimina el segundo escape. Dos regresiones fallaron antes del fix; luego pasaron
181 tests Linux, diez renders y un probe Swarm con cero réplicas y control negativo.
Los recursos de ese probe se retiraron al finalizar.

En dev se restauró manualmente el digest inicial `sha256:5a4ceff4bec8fbc8b7bdac88b68dd240f09142ddcffa9ce4dbf5b564fcd04855`
y después el digest verificado `sha256:d07e85f143e7cf7b485647a48cb534c3f211817da6dc7d44fbda22f223a8f390`,
mediante el comando existente `bootstrap_swarm.py deploy <candidato> --service ui`.
Ambos recorridos aprobaron convergencia, SQL, storage y HTTP.

La primera aplicación del fix también normalizó el ancla `$` de
`NGINX_ENVSUBST_FILTER`: NGINX se recreó una vez, conservando configs y certificados.
Por eso el primer guard estricto de identidad de tareas no pasó. En la segunda
actualización se comprobó explícitamente que backends, bases y NGINX conservaron
sus tareas, además de imágenes/configuración; terminó sin operaciones pendientes.

Esto prueba restauración manual de imágenes sanas. No se indujo una imagen
defectuosa ni se cortó SSH: esas regresiones del stack ampliado siguen en SNI-44.

## Límites y operación posterior

- Dev permanece restringido al equipo por Azure. La IP residencial no se publica.
- Prod no utiliza actor de desarrollo; sin Auth0, cargar UI no acredita identidad
  ni operaciones protegidas productivas.
- El CD requiere la VM del ambiente encendida; no enciende ni apaga Azure.
- El bootstrap/reapply debe usar la revisión corregida, preservando `tls: true` y
  las referencias vigentes. No reutilizar la copia anterior para reaplicar el stack.
- `v0.6.1` sigue fijando infra `9f7eee8`: el update normal de apps no usa el renderer,
  pero antes de probar reconciliación automática de infraestructura en SNI-44 hay
  que incorporar este fix también a la revisión central mediante una versión nueva,
  sin mover tags existentes.
- La aceptación integral DNS/TLS/CORS, red, fallos automáticos y corte SSH pertenece
  a SNI-44; esta evidencia no la declara completada.
