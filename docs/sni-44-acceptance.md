# SNI-44 — Aceptación integral del ingreso y recuperación

## Alcance y decisiones

Plan aprobado por Juan Francisco Siaba el 28/10/2026: verificar DNS, TLS, CORS y
red; independencia de aplicaciones; reapply; recuperación e interrupción SSH en
dev. Prod sólo recibe configuraciones revisadas y comprobaciones no destructivas.
Se reutilizan scripts y pruebas existentes; no se incorpora otro orquestador.
El costo aceptado es ejecutar las pruebas operativas con las VMs encendidas y
disponibilidad temporalmente afectada en dev durante los ensayos de falla.

La UI y NGINX ya están instalados en ambos ambientes (SNI-40/42). Asset/Azurite
no están instalados y el storage sigue siendo `local`. No se exige Auth0 ni
completar historias funcionales para validar el transporte. Una respuesta 401
de prod es correcta mientras no haya autenticación real.

## Preparación de herramientas

La revisión central v0.6.1 fija infra anterior al arreglo del doble escape de
Compose/Shell documentado en SNI-42. No ejecutar recuperación de infraestructura
con esa copia antigua. Orden: integrar infra con el fix y gate v0.6.2; fijar su
SHA revisado en central; validar y publicar v0.6.2 sin mover tags; actualizar los
cuatro callers. Antes del reapply esperar runs activos y comprobar el gate bajo
el bloqueo compartido. Los workflows conservan publish/select/deploy y sus inputs.
Este orden agrega revisión/CI, pero mantiene reproducibles los scripts ejecutados
en las VMs y evita recuperar con herramientas incompatibles.

## Matriz y fuentes de evidencia

| Área | Procedimiento | Límite |
| --- | --- | --- |
| DNS/TLS/rutas/UI | `python -B scripts/verify_public_ingress.py dev` y `prod` | Estación externa autorizada; TLS con CA/hostname verificados, nunca `-k` |
| Navegador HTTPS | `tests/nginx/public-ingress.cy.js` contra cada dominio | UI real, sin respuestas interceptadas; POST inválido sólo en dev |
| CORS permitido/rechazado | `snippets-service/src/test/ui/cors.cy.ts` con Spring real local y allowlist explícita | No equivale a autorizar localhost en prod |
| Proxy mismo origen | Spec HTTPS anterior y `cors-proxy.cy.ts` | Verificar errores y escritura inválida, no sólo GET |
| Renovación/recarga | `certificates.py renew dev --dry-run`, `reload dev`, `status dev` | Dry-run usa staging sin reemplazar certificado público; registrar huella antes/después |
| Red | Puertos explícitos del checker + servicios/publicaciones y reglas NSG | Timeout desde un cliente no demuestra todas las reglas; no escanear IPs ajenas |
| Independencia/reapply | Snapshot previo, actualización de app/UI y bootstrap con referencias vigentes | Comparar imágenes/configs/volúmenes ajenos, no sólo réplicas |
| Rollback | Falla controlada sólo en dev usando operación con journal | La operación queda fallida aunque recupere; no promover la imagen defectuosa |
| SSH perdido | Cortar cliente SSH después de observar pending; consultar journal y reconciliar bajo lock | Desconexión no equivale a caída remota; no borrar pending ni inventar recibos |
| Prod | HTTPS/identidad, registros, réplicas, mismos digests verificados | Sin datos ficticios, fallas deliberadas ni cambios de proveedor |

El checker externo es opt-in: no se incorpora al CI de runners públicos, cuyas
IPs no pertenecen a AllowTeamWeb. Produce JSON con certificado público y resultados,
sin credenciales. Un error de DNS/red es fallo o prueba inconclusa; nunca éxito
por asumir que la VM estaba apagada. No demuestra por sí solo CORS de navegador.

Para el spec HTTPS, desde UI copiar temporalmente el archivo al directorio
Cypress de backend y ejecutar (reemplazar dev por prod cuando corresponda):

```powershell
Copy-Item ../snippet-searcher-infra/tests/nginx/public-ingress.cy.js cypress/e2e/backend/sni44-public.cy.js
npx cypress run --config 'specPattern=cypress/e2e/backend/sni44-public.cy.js,chromeWebSecurity=true' --env environment=dev
# Al terminar, retirar sólo la copia temporal; conservar este spec en infra.
```

La configuración y los pasos del backend real para cross-origin están en
[CORS de Snippets](https://github.com/JJT-INGSIS/snippets-service/blob/dev/docs/cors.md).
El contrato de rutas/métodos sigue SNI-45/52. No añadir comodines, métodos ni
headers para hacer pasar una prueba. CORS no implementa endpoints ni autentica.

## Cierre

Registrar comandos, revisión de infra/central, runs, resultados dev/prod y límites
en la evidencia de este ticket. Confirmar Swarm igual a release.json, checks
correctos, ningún pending y retiro de recursos temporales. Reutilizar evidencia
vigente de SNI-40/42 indicando su fecha, sin presentar pruebas locales como remotas.
No marcar Done mientras queden comprobaciones requeridas sin ejecutar.
