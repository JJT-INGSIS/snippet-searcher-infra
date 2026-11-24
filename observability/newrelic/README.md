# Configuración de New Relic

El [runbook](../../docs/observability/README.md) cubre las señales, destinos y
evidencia operativa de DEV y PROD.

## Terraform

| Raíz | Recursos |
| --- | --- |
| [Este directorio](synthetics.tf) | Pings de UI/API de DEV y [alertas del chequeo funcional DEV](functional-dev.tf). |
| [sni-86](sni-86/README.md) | Condiciones operativas DEV, tableros por ambiente y SLO DEV. |
| [prod-functional/alerts](prod-functional/alerts/) | Condiciones y SLO del chequeo funcional PROD. Consultá su [procedimiento](prod-functional/README.md). |

Los Pings públicos y políticas/workflows de PROD se verifican en la cuenta.
Para cada raíz, guardá el estado y los planes en un lugar privado. Usá una
User API key solo en el proceso de Terraform y una licencia de ingesta para el
runtime. Confirmá los nombres de variables en la raíz elegida. Importá recursos
existentes antes de aplicar. Los monitores se importan por GUID en
`newrelic_synthetics_monitor.dev_ui` o `newrelic_synthetics_monitor.dev_api`.
Revisá `terraform fmt -check`, `validate` y el plan completo antes de operar.
Las condiciones referencian políticas existentes. Cotejá su ID, ambiente y
workflow en New Relic.

## Chequeo autenticado

`dev-functional` usa Cypress sobre la UI real, mediante el hostname de DEV por
loopback y TLS verificado. Inicia sesión con una identidad dedicada, consulta
el listado, abre el fixture de observabilidad y verifica su contenido. El
Scripted Browser alojado se dejó deshabilitado por la captura de datos del login.

El runner DEV se instala en `/opt/snippet-observability/dev/functional/` con
`run.py`, `journey.js`, config Cypress y ambos specs, más las
[unidades de systemd](../../systemd/). Se ejecuta al encender y cada seis horas.
[Save-DevFunctionalCredential.ps1](dev-functional/Save-DevFunctionalCredential.ps1)
entrega la credencial por SSH verificado. El host la conserva en un archivo
root 0600. El navegador corre en un contenedor efímero con tmpfs. El host
publica `SnippetFunctionalCheck` con ambiente, nombre, resultado, duración y
categoría de falla. Los secretos, tokens y contenidos quedan fuera de la ingesta.
`run.py` devuelve 0 para éxito publicado, 1 para fallo publicado y 2 para error
de publicación. El acuse se complementa con la consulta del evento en New Relic.

Para comprobar DEV, ejecutar el runner y exigir un evento `SUCCESS`. El
fixture admite `--fixture prepare`, `hide` y `restore`. Para un ensayo autorizado,
renombrar solo el fixture, comprobar `FAILURE / SNIPPET_MISSING` y la alerta,
restaurar y comprobar `SUCCESS` y cierre. La alerta separada de pérdida detecta
13 horas sin resultados. Para PROD, usar el
[runner con identidad y fixture propios](prod-functional/README.md).

La instrumentación de Browser en la UI es independiente. El monitoreo funcional
se apoya en resultados mínimos del runner, mientras Browser observa rendimiento
y errores JavaScript.
