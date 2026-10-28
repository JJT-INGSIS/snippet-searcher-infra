# SNI-44 — Evidencia de aceptación integral

Ejecución del 28/10/2026, Argentina. Estado: **aceptación completada**.
Las comprobaciones siguientes se realizaron contra los ambientes reales; las
limitaciones funcionales y de seguridad se detallan al final.

## Herramientas y control de integración

- Infra [PR #31](https://github.com/JJT-INGSIS/snippet-searcher-infra/pull/31),
  revisión `9fcc49204260566667171cdde320eea8f81c965d`; promoción por
  [PR #32](https://github.com/JJT-INGSIS/snippet-searcher-infra/pull/32).
- Central [PR #11](https://github.com/JJT-INGSIS/github-workflows/pull/11), tag
  liviano nuevo `v0.6.2` = `5f05ef4711e3363dcec582627e811fd9f0292508`.
  Actionlint, CI de PR y CI de main aprobados; no se movieron tags.
- Main sigue exigiendo PR, CI y base actualizada en los cuatro repos; aplica a
  administradores, sin force push ni bypass de PR.
- Mantenimiento de main: UI #9, Snippets #46, Permissions #26, PrintScript #25.
  Sólo caller/README; CD se deshabilitó durante esos merges y se restauraron sus
  valores originales al terminar los cuatro CI. Publicación/despliegue omitidos.
- Callers dev: UI #8, Snippets #45, Permissions #25, PrintScript #24. Se incorporó
  el mantenimiento de main a sus historiales mediante merges normales antes de
  verificar dev, para conservar la futura promoción por igualdad de Git tree.
- Decisión explícita de Juan: no promover las funcionalidades SNI-46/47/50 a prod
  como efecto de este mantenimiento. Las imágenes de prod permanecen intactas.

## Transporte, certificados y navegador

| Prueba | Dev | Prod |
| --- | --- | --- |
| DNS, TLS público y hostname sin `-k` | Aprobado, TLS 1.3 | Aprobado, TLS 1.3 |
| HTTP 308 conserva hostname/ruta/query; ACME inexistente 404 | Aprobado | Aprobado |
| UI y recarga SPA `/rules`, runtime `no-store`, catálogo JSON | Aprobado | Aprobado |
| Navegador same-origin, errores JSON, sin recursos HTTP | Aprobado | Aprobado |
| Origen local no autorizado: catálogo HTTP accesible pero fetch bloqueado por navegador | Aprobado | Aprobado |
| CORS permitido/rechazado con Spring local real y seguridad de navegador habilitada | 2/2; preflight y 401 legible | No se habilitan orígenes locales en prod |
| Allowlist vacía, crear/actualizar/detalle con proxy Vite real | 1/1 local | No se ejecutan escrituras de prueba |
| Sin identidad y con actor dev arbitrario | Error legible en API protegida | 401 en ambos casos; identidad runtime deshabilitada |
| `certificates.py renew --dry-run` | All simulated renewals succeeded | All simulated renewals succeeded |
| Recarga sin reiniciar tarea y posterior recreación exclusiva de NGINX | Aprobado, mismo certificado y tareas ajenas conservadas | Evidencia previa SNI-40; aquí no se fuerza recreación |
| SQL autenticado, migraciones, storage, HTTP interno y TLS del stack | Aprobado | Aprobado sin escribir datos de aplicación |
| Estado/datos después de verificar | Referencias/recibos/configs conservados, tareas de apps/DB intactas, datos previos preservados y sin pending | Registro, tareas/specs, imágenes, volúmenes, operaciones y huellas idénticos; sin pending |

Certificado dev SHA-256:
`6247bdf097d128d3b52be13350ef707c5257b1d019f7ee7165bd4dd70f170f63`,
serial `0537681FC0C2569839AB7CED01AE831DF988`, vence 24/01/2027 13:55:41 GMT.
Prod SHA-256:
`4c8b103b951dc80b510136551321479d5c774244d6b701f71d73b8677f277238`,
serial `05C799694A7833A3B64B9F791837D1D807F8`, vence 24/01/2027 16:07:19 GMT.
El dry-run no reemplazó los certificados públicos. El arranque real de ambas VMs
conservó los recursos persistentes; no se emitieron certificados nuevos.

El checker prueba puertos TCP concretos de aplicaciones, Swarm/management,
PostgreSQL, Redis y Asset/Azurite. En prod los 16 fueron inaccesibles desde la
estación externa. No constituye un escaneo UDP ni sustituye la revisión de NSG.
Dev conserva AllowTeamWeb por IP; el cambio de IP residencial requirió actualizar
la regla sin ampliar el ingreso a Internet. La IP del equipo no se publica.

## Despliegues y recuperación

| Operación | Evidencia | Resultado |
| --- | --- | --- |
| UI dev con central v0.6.2 | [40747730231](https://github.com/JJT-INGSIS/snippet-searcher-ui/actions/runs/40747730231) | Aprobado |
| Permissions dev | [40747751987](https://github.com/JJT-INGSIS/permissions-service/actions/runs/40747751987) | Aprobado |
| PrintScript dev | [40747762463](https://github.com/JJT-INGSIS/printscript-service/actions/runs/40747762463) | Aprobado |
| Snippets dev | [40747740352](https://github.com/JJT-INGSIS/snippets-service/actions/runs/40747740352) | Aprobado |
| Reapply con referencias vigentes | `infra-e3b6ac7c4b294c428feeb4a5b4c81ee6` | CLI 0, verified, sin pending |
| Configuración NGINX inválida, sólo dev | `infra-2c60d0faeaf7423a83747d927e0901d9` | CLI 1 y recuperación confirmada; Swarm rollback_completed |
| Interrupción real del cliente SSH tras observar pending durable | `infra-3467bd58714444539649acf06eadc8c3` | Reconexión/reconciliación verified, una sola operación nueva, sin pending |

Los cuatro runs completaron CI, publicación y despliegue (no omitidos), usando
la revisión central del tag v0.6.2. Cada aplicación conserva su recibo y digest;
la reaplicación no retrocedió imágenes al manifiesto del bootstrap. NGINX/UI,
las bases, los mounts/configs y el proveedor local quedaron coherentes con
release.json; las siete réplicas permanentes convergieron.

El ensayo de falla agregó una directiva inválida únicamente a una copia de
`nginx/templates/routes.conf.template`, con scripts idénticos a la revisión
9fcc492. Se aplicó por el bootstrap real `deploy <candidate> --infrastructure`,
con gate y lock habituales. La tarea candidata terminó con exit 1 y Swarm
registró rollback_completed entre 19:11:31 y 19:11:38 UTC. Se recuperó
`nginx_routes_v1`, sin retroceder ninguna aplicación. La operación de infra
conserva el fallo (CLI 1), aunque la recuperación y HTTPS posteriores pasaron.
No se simuló una imagen defectuosa de aplicación ni una Action fallida: el
ensayo remoto fue de configuración de infraestructura. Se retiraron el config
inválido sin uso `nginx_routes_v4491` y la copia desechable; se conservaron journals.

Para el corte SSH se inició una reaplicación sana, se observó pending durable y
se terminó exclusivamente el cliente SSH local. Al reconectar se adquirió el
mismo lock y se ejecutó la reconciliación existente: el journal de la misma
operación estaba verified, sin duplicación ni pending. Esto prueba desconexión
del cliente; no equivale a matar el proceso remoto ni apagar la VM. Un intento
auxiliar previo no llegó a cortar SSH porque el lector del journal necesitaba
sudo; terminó como reaplicación sana. Se corrigió el lector, sin ampliar permisos
ni borrar archivos, y se repitió el corte real indicado en la tabla.

Las huellas de las 70 filas de snippets, 139 ownerships y 70 archivos anteriores
permanecieron iguales como subconjunto del estado final de dev. Los smoke tests
y Cypress agregaron fixtures identificados sólo en dev. No se extrajo contenido
ni credenciales. Cypress final pasó 2/2 en cada ambiente, con seguridad de
navegador habilitada: en dev incluyó POST 201, PUT 200 y detalle 200 con contenido
actualizado por HTTPS; prod sólo hizo lecturas y comprobaciones 401. La aceptación
funcional completa de las historias nuevas no forma parte de estas pruebas.

## Evidencia histórica y mantenimiento de main

La consulta real de Deployments recuperó la UI verificada del run
[40433093336](https://github.com/JJT-INGSIS/snippet-searcher-ui/actions/runs/40433093336),
aunque dev ya tenía otro árbol: tree `6746868ce7e74273a08cc08d7b358cab871f3818`,
digest `sha256:d07e85f143e7cf7b485647a48cb534c3f211817da6dc7d44fbda22f223a8f390`.
Es la imagen que sigue ejecutándose en prod; no se reconstruyó ni redesplegó.

El mantenimiento exclusivo de caller/README en main cambia su Git tree sin
probar ese contenido completo en dev. La selección de ese nuevo árbol se
rechazó correctamente por falta de evidencia exacta, antes de modificar prod.
No usar un rerun de ese main de mantenimiento como promoción. La siguiente
promoción funcional debe ser una PR normal dev→main cuyo contenido completo
ya haya pasado despliegue/verificación en dev. Se sincronizó la ascendencia de
main en dev; no se relajó la igualdad de árboles ni se promovieron SNI-46/47/50.

## Validación local y límites

186 tests Linux y diez renders aprobados, más el build completo de Snippets.
La aceptación TLS local de Windows no pudo crear symlinks; la misma aceptación
pasó en CI Linux, incluyendo NGINX real, recarga y persistencia de certificados.
Un primer arranque local de Java falló por su ruta temporal de sockets; se repitió
con el ajuste documentado y las pruebas CORS pasaron. No se cambió código de negocio.

Auth0 y la aceptación funcional de las historias pendientes siguen fuera de
alcance. Asset/Azurite no se activaron: storage continúa local. Usar los scripts
revisados y callers actuales para recuperación; no reejecutar copias históricas
de herramientas anteriores. Este gate no revoca por sí solo el acceso de un
operador/root a scripts antiguos.

Procedimientos reproducibles: [matriz de aceptación](sni-44-acceptance.md),
[SNI-40](sni-40-tls.md), [SNI-42](sni-42-evidencia.md) y [SNI-43](sni-43-cd.md).
