# SNI-24 — Evidencia de ejecución

## 12/10/2026 — preparación local

- Rama: `feat/sni-24-swarm-bootstrap`, worktree `sni-24-infra`.
- Sin commit, push, PR, merge ni publicación en Linear.
- Usuario confirmó paquetes públicos actuales de GHCR.
- Cuatro manifiestos verificados por digest y `linux/amd64`; Snippets incorpora SNI-8/SNI-17.
- 28 tests locales exitosos; stack renderizado para dev/prod; Bash válido.

## Ejecución remota

### Dev — primer bootstrap confirmado

- Pull público de las tres aplicaciones y PostgreSQL exitoso, sin login ni tokens.
- Cinco servicios 1/1 y sus cinco digests esperados, estables durante 60 segundos.
- SQL autenticado por TCP: Snippets con 2 migraciones; Permissions con 1 migración.
- Directorio de contenido escribible por uid 10001 y evidencia JDBC/Flyway de Snippets.
- HTTP desde el servicio temporal de verificación dentro de `snippet-searcher-dev_default`: health Permissions UP, PrintScript válido y suite de contratos 2/2.
- Ownership de prueba de la suite: `c194715f-a186-493d-9a2e-c8f1709839f5` (`infra-smoke-test`).
- Snippet creado y confirmado: `93172bf0-a977-4f3d-8136-7632f3556245`, con contenido y owner `infra-bootstrap-probe` comprobado en Permissions.
- Servicio temporal HTTP eliminado y release confirmado en `/home/azureuser/.local/state/snippet-searcher/dev/release.json`.

La primera ejecución no confirmó el release porque intentó adjuntar un contenedor a una overlay no attachable. Se corrigió el verificador para usar un servicio Swarm temporal y se repitió exitosamente, sin cambiar la red ni regenerar secretos. Los primeros arranques de las aplicaciones fallaron mientras sus bases aún iniciaban; la política de reinicio permitió recuperar las tareas y los checks finales pasaron.

### Dev — actualización independiente

Se verificó otro manifiesto público de PrintScript (`sha256:5684c3d7caab2bb50b14fe0c98553b295961fddc076d1869af9a8be3cf5998a6`, publicación del mismo commit `aee17456de01505b27f562e07e7cac4bb6db5344`). Se aplicó con `--service printscript-service`:

- La tarea de PrintScript cambió y las otras cuatro tareas conservaron exactamente sus IDs de contenedor.
- Las referencias registradas de Snippets, Permissions y PostgreSQL permanecieron iguales.
- SQL/HTTP y creación de Snippets volvieron a pasar; nuevo snippet de prueba `0c24fde5-9fe7-4c91-965e-862979184250` y ownership de la suite `459b96f4-13a1-45bb-8344-ee1b1b45ed2d`.
- El release quedó confirmado. El digest final de PrintScript se usa también para prod; no se construyó ninguna imagen.

### Dev — reaplicación y persistencia

- Se reaplicó el manifiesto que aún tenía PrintScript `sha256:5dfa0e...`: el registro conservó `sha256:5684c3...` y las cinco tareas mantuvieron sus IDs. La configuración local final de dev/prod quedó actualizada al digest confirmado.
- Registro de dev confirmado: `2026-10-12T14:35:08.859094+00:00`.
- Se forzó una nueva tarea de `snippets-db` y otra de `permissions-db` bajo el bloqueo del ambiente. Las dos instantáneas de tablas de cada base (conteo y fingerprint del contenido, incluyendo migraciones) quedaron idénticas antes/después.
- Las huellas de los archivos del volumen de contenido se conservaron durante la recreación de ambas bases.
- SQL/HTTP se repitió después de recrear las tareas, antes de promover.
- NSG efectivo de dev revisado en Azure durante el despliegue: sólo SSH TCP 22 como entrada desde Internet; reglas VNet/Load Balancer y DenyAllInBound. No se abrieron HTTP, bases ni Swarm/Docker.

### Estado previo a prod

Dev se confirmó `Detenido (desasignado)` antes de iniciar prod. Se entregó a prod una copia sin secretos del registro de dev, y `prod-release.json` usa las mismas tres aplicaciones y PostgreSQL por digest. El bootstrap de prod completó las comprobaciones y confirmó el registro indicado abajo.

### Digests finales seleccionados

| Imagen | Digest |
| --- | --- |
| `ghcr.io/jjt-ingsis/snippets-service` | `sha256:b9863900437d33729ad8006cc289bf54346dd722ccbee1d5bf97cd614b3d66a3` |
| `ghcr.io/jjt-ingsis/permissions-service` | `sha256:51a25deb9769e1e17d884a3940e6d877e7a491ca20a80ebab8977b4ee03403d7` |
| `ghcr.io/jjt-ingsis/printscript-service` | `sha256:5684c3d7caab2bb50b14fe0c98553b295961fddc076d1869af9a8be3cf5998a6` |
| `postgres:18.6-bookworm` | `sha256:afc7e2d441324c0388fa80c3d24f733b4194a4eb7f47dd8ee2b08eb1a24a647c` |

Comprobación posterior a persistencia en dev: snippet `b19db316-521c-4db4-bc0b-553b733db651` y ownership de suite `6fcf37a1-d7c0-4ef2-85c2-7a310bd54ab3`. Estas pruebas dejan datos identificables sólo en dev.

### Prod — bootstrap y persistencia confirmados

- Registro confirmado: `2026-10-12T14:44:11.779257+00:00` en `/home/azureuser/.local/state/snippet-searcher/prod/release.json`.
- Comparación de registros: las tres referencias de aplicaciones y PostgreSQL coinciden exactamente con dev.
- Cinco servicios 1/1, digests esperados y healthchecks saludables; sin servicios temporales de prueba al finalizar.
- SQL autenticado: Snippets con 2 migraciones y Permissions con 1. El volumen de Snippets es escribible por uid 10001.
- HTTP interno: health Permissions UP, validación PrintScript y consulta ownership inexistente 404. No se creó ownership ni snippets de prueba en prod.
- Persistencia: tareas nuevas de ambas bases, con las dos instantáneas de tablas de cada una idénticas. Huellas del contenido preservadas.
- Salud SQL/HTTP repetida después de recrear las tareas, con resultado exitoso.
- Conteos finales en prod: `snippets=0`, `snippet_ownership=0`; las únicas filas inicializadas son las migraciones (2/1). Los datos de prueba de dev no se copiaron.
- Volúmenes propios: `snippet-searcher-prod_snippets_data`, `snippet-searcher-prod_permissions_data`, `snippet-searcher-prod_snippets_content`.
- NSG efectivo de prod revisado en Azure: SSH TCP 22 permitido; reglas VNet/Load Balancer y DenyAllInBound. Sin apertura pública HTTP, bases, Docker ni control de Swarm.

## Entrega y cierre técnico

- [x] Manifiestos por digest y plataforma verificados; renderizado local y Compose local válidos.
- [x] Dev y después prod desplegados con las mismas imágenes finales.
- [x] SQL autenticado, migraciones y HTTP interno comprobados en ambas VMs.
- [x] Volúmenes, secretos y datos independientes; storage para usuario no root.
- [x] Persistencia tras recrear ambas tareas de base comprobada por ambiente.
- [x] Actualización aislada de PrintScript preservó otras aplicaciones y bases.
- [x] Reaplicar un manifiesto anterior conservó referencias vigentes y tareas.
- [x] Guía operativa, contrato para SNI-25 y comandos de commit/PR en Markdown.
- [x] Dev y prod confirmadas `Detenido (desasignado)` al terminar; datos y estado del stack conservados en disco.
- [ ] Publicación/integración de esta rama y check remoto de CI: a cargo del usuario; no se ejecutaron commit, push ni merge.

SNI-20 conserva como pendiente el acceso personal de Juan Francisco/Juan Rudolph, y la documentación de SNI-21 también permanece local. No se actualizó ni cerró ningún ticket en Linear durante SNI-24. La evidencia distingue pruebas reales, validación local y acciones de integración pendientes.

Validación local final: **29 tests exitosos**, incluidos los controles de rollback de digest de base, preservación de referencias y promoción exacta. Renderizado dev/prod, Compose local, Bash, sintaxis Python y enlaces Markdown correctos. La centralización final del inventario de servicios conserva los mismos cinco servicios probados en las VMs.
