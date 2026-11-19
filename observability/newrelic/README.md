# Monitores New Relic de DEV

Esta carpeta prepara la configuración de los dos monitores Ping existentes.
Se ejecutó `terraform init`, `terraform validate` y `terraform fmt -check` con
Terraform 1.13.5 y el proveedor bloqueado en 3.75.4. Los dos monitores fueron
importados al estado local y se revisó un primer plan: propone cero altas, dos
actualizaciones y cero destrucciones. La consola de New Relic ya muestra las
opciones GET y `environment:dev` en ambos monitores y el tratamiento de
redirecciones en API, tal como se desean; aun así el plan propone agregarlos.
Esto sugiere diferencias de lectura del proveedor, pero no se confirmó su causa.
**No ejecutar `apply`** hasta conciliarlas y revisar el plan nuevamente. No incluye el monitor de certificado, alertas,
destinos, workflows ni la regla Azure; están documentados por separado.

El proveedor utiliza credenciales de New Relic suministradas fuera del repositorio.
No guardar claves, archivos de variables sensibles ni el estado de Terraform en Git.
Antes de configurar estado compartido, acordar su almacenamiento y control de acceso.

Preparación pendiente con Terraform >= 1.5 y el proveedor especificado:

1. Configurar `TF_VAR_newrelic_api_key` con una **User API key**, y las variables
   `newrelic_account_id` y `dev_base_url` por mecanismos locales seguros. No
   registrar credenciales en el código ni en logs. La variable es sensible, pero
   el estado puede contener información sensible: mantenerlo fuera de Git.
2. Ejecutar `terraform init` y `terraform validate` en el entorno de trabajo.
3. Importar cada monitor existente por su **entity GUID**, usando los destinos
   `newrelic_synthetics_monitor.dev_ui` y `newrelic_synthetics_monitor.dev_api`.
   Obtener los GUID desde la pantalla de cada monitor; no usar el UUID corto.
4. Revisar `terraform plan` completo y conciliar cualquier diferencia antes de
   aplicar. No ejecutar un plan que proponga reemplazar recursos existentes.

Los detalles y limitaciones de los monitores se encuentran en
[`docs/observability/sni-84-synthetics-dev.md`](../../docs/observability/sni-84-synthetics-dev.md).

## SNI-85 — Chequeo funcional autenticado de DEV

El Scripted Browser `snippet-searcher-dev-funcional` queda deshabilitado.
**Validate** conservó valores ficticios de `code` y `state` en la URL y de
`code_verifier` y `password` en el cuerpo del POST. La validación también
generó una captura. [Seguridad de Synthetics](https://docs.newrelic.com/docs/synthetics/synthetic-monitoring/getting-started/security-synthetic-monitoring/)

### Ejecución y privacidad

El [chequeo Cypress](dev-functional/functional.cy.js) inicia sesión en la UI
real, busca `SNI-85 Synthetic`, exige HTTP 200, abre el resultado exacto y
compara el contenido de prueba. Usa la conexión de usuario y contraseña de
Auth0. La prueba negativa de contrato, con un 200 simulado, sigue en la UI.

Se verificó en `vm-snippet-dev` el HTTPS al hostname de DEV por loopback, el
egreso a Auth0 y el egreso a Event API. El timer de systemd ejecuta un contenedor
efímero de Cypress al iniciar la VM y cada seis horas. Docker usa el hostname
real sobre `127.0.0.1`, validación TLS y límites de una CPU y 1,5 GB de RAM.
Los runners públicos de GitHub no forman parte de la lista HTTPS aprobada.

El código del chequeo se instala en `/opt/snippet-observability/dev/functional`
junto con las unidades `snippet-functional-dev.service` y
`snippet-functional-dev.timer` de `systemd/`. Para repetir la instalación,
descargar la imagen fijada en `run.py`, copiar los cinco archivos del runner
(`run.py`, `cypress.config.cjs`, `journey.js` y los dos `.cy.js`), instalar las
unidades y ejecutar `systemctl daemon-reload`. El timer se habilita al terminar
la verificación del circuito.

El operador puede cargar la cuenta con
[`Save-DevFunctionalCredential.ps1`](dev-functional/Save-DevFunctionalCredential.ps1).
Lee la contraseña de forma oculta y envía las credenciales por stdin y SSH a
`/etc/snippet-observability/dev/functional-auth0.json`, propiedad de root con
modo `0600`. El contenedor monta solo ese archivo y el spec en lectura. El
perfil, caché y artefactos del navegador usan tmpfs; screenshots, videos y
logs de Cypress están desactivados o descartados. La licencia de ingesta
existente de la VM permanece disponible solo para el publicador en el host.

### Evento, alertas y SLI de SNI-86

[`run.py`](dev-functional/run.py) publica `SnippetFunctionalCheck` mediante
Event API en la cuenta de New Relic de DEV. Los cinco atributos del chequeo
son `environment`, `checkName`, `result`, `durationMs` y `failureCategory`.

| Atributo | Valores |
| --- | --- |
| `environment` | `dev` |
| `checkName` | `snippet-searcher-dev-functional-listing` |
| `result` | `SUCCESS`, `FAILURE` |
| `durationMs` | Duración entera en milisegundos |
| `failureCategory` | `NONE`, `CONFIGURATION`, `RUNNER`, `AUTH0_LOGIN`, `LISTING_HTTP`, `SNIPPET_MISSING`, `DETAIL_CONTENT` |

El proceso termina con `0` para éxito confirmado por Event API, `1` para
fallo del chequeo confirmado por Event API y `2` si falla el envío. La pérdida
de señal cubre los eventos que no llegan. Comprobar la ingesta con NRQL,
porque el acuse HTTP precede al análisis del evento.
[Event API](https://docs.newrelic.com/docs/data-apis/ingest-apis/event-api/introduction-event-api/)

[Las condiciones](functional-dev.tf) se asocian a la política DEV existente
(`dev_alert_policy_id`). La primera detecta cualquier `FAILURE` con un timer
de eventos de un minuto. La segunda abre un incidente al pasar 13 horas sin
un `SUCCESS` ni un `FAILURE`. Silenciar la condición de ausencia durante un
apagado planificado de la VM y volver a ejecutar el chequeo al iniciar DEV.
Si las condiciones se crean desde la consola, importar sus IDs antes de
aplicar Terraform para conservar una instancia de cada una.

La política DEV `8318071` tiene la condición de fallo `69952989` y la de
pérdida de señal `69953021`, ambas verificadas.

```sql
FROM SnippetFunctionalCheck
SELECT percentage(count(*), WHERE result = 'SUCCESS') AS 'Disponibilidad funcional %'
WHERE environment = 'dev' AND checkName = 'snippet-searcher-dev-functional-listing'
  AND result IN ('SUCCESS', 'FAILURE')
```

El denominador incluye las ejecuciones recibidas. Un intervalo sin resultados
se muestra como ausencia de señal, con la condición específica de pérdida.
Para investigar, consultar `count(*) FACET result, failureCategory` sobre el
mismo evento. Los monitores públicos de SNI-84 conservan `SyntheticCheck`.

### Ensayo controlado para SNI-87

En la VM, ejecutar como root `python3 -B /opt/snippet-observability/dev/functional/run.py`.
Para preparar el fixture, ejecutar ese mismo comando con `--fixture prepare`.
Esa operación crea un snippet de PrintScript 1.1 con un marcador dedicado. Las
opciones `--fixture hide` y `--fixture restore` verifican el nombre, el marcador
y el código antes de operar. Las operaciones sobre el fixture no emiten eventos.

1. Ejecutar el chequeo sano y confirmar que llega `SUCCESS`.
2. Ejecutar `--fixture hide` y volver a lanzar el chequeo. Confirmar `FAILURE`
   con categoría `SNIPPET_MISSING` y la apertura de la alerta.
3. Ejecutar `--fixture restore` incluso si el paso anterior falla por otro
   motivo. Comprobar que llega `SUCCESS` y se recupera la condición.
4. Para un ensayo de pérdida de señal, usar una ventana breve acordada, sembrar
   un resultado real y observar la ausencia. Restaurar el umbral de 13 horas
   y volver a publicar un resultado sano al terminar.

El renombre en DEV demuestra la ausencia de un dato esperado con HTTP 200.
La prueba negativa de Cypress conserva la simulación de un listado incorrecto.

### Evidencia de DEV del 18 de noviembre

- La ejecución real emitió `SUCCESS` con el fixture presente, `FAILURE` y
  `SNIPPET_MISSING` tras un HTTP 200 con el fixture renombrado, y `SUCCESS`
  después de restaurarlo. `keyset()` confirmó los cinco campos y el `timestamp`
  asignado por New Relic.
- `NrAiIncident` registró la apertura y el cierre del incidente por umbral de
  fallo (`80176c27-0cab-4aee-a1c3-6d90ad023b8c`) y del incidente por expiración
  (`8ca1f50c-1a20-4059-a117-f6f59b5aeee3`). La
  prueba de ausencia usó tres minutos y el umbral final es de 13 horas.
- El timer `snippet-functional-dev.timer` quedó habilitado y activo. Su primer
  disparo publicó `SUCCESS` en 21,6 segundos. La
  simulación de un error en Event API devolvió código `2` y registró solo el
  error de envío. Se comprobó la lista fija de campos en el publicador.

### Telemetría de Browser en DEV

El [despliegue de UI](https://github.com/JJT-INGSIS/snippet-searcher-ui/actions/runs/44433488594)
sirvió el agente y New Relic recibió `PageView`, `PageViewTiming` y
`JavaScriptError`. Un ensayo de Cypress sobre la UI desplegada, sin iniciar
sesión, generó `SNI-85 DEV Browser controlled error`. La consulta de
`JavaScriptError` por ese mensaje devolvió un evento. En la muestra pública
se observaron URL de página, tiempos,
tipo de navegador, datos de red y ubicación inferida del ISP. Los eventos de
error también incluyen mensaje y stack trace. La muestra no tuvo eventos
`AjaxRequest` ni atributos de credenciales, identidad de la aplicación o
contenido de snippets.
[Seguridad de Browser](https://docs.newrelic.com/docs/browser/new-relic-browser/performance-quality/security-browser-monitoring/)
