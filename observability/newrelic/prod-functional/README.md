# Chequeo autenticado y SLO de PROD — SNI-89

Preparación para la cuenta US 8718557 y política 8369826. El código reutiliza
el recorrido probado en DEV sin cambiar sus archivos ni su timer. Usa cuenta,
fixture, hostname, configuración privada y nombres exclusivamente de PROD.
No está desplegado ni acreditado por tener estos archivos.

## Cuenta y privacidad

Se necesita una cuenta Auth0 dedicada de PROD con login usuario/contraseña.
No usar la credencial de DEV ni una cuenta personal para el timer.
Un operador debe provisionar la credencial por un canal privado en la VM;
no pegarla en chat, Run Command, repositorio o logs de pipelines.
`Save-ProdFunctionalCredential.ps1` lee la contraseña oculta y transmite por
stdin a través de SSH verificado, usando una identidad autorizada de PROD.
El runner la guarda como root con modo 0600 en
`/etc/snippet-observability/prod/functional-auth0.json`.

El fixture es `SNI-89 Synthetic`, código `println("SNI-89 OK");`, marcador
`Fixture dedicado para observabilidad en PROD (SNI-89)`.
`--fixture prepare` sólo crea ese contenido de prueba o comprueba el existente.
Antes de renombrar, exige código y marcador exactos. No usar `hide` como ensayo
sin coordinarlo: aunque sólo toca el fixture, puede abrir una alerta.

## Activación después de provisionar identidad

Copiar run.py, journey.js, cypress.config.cjs y ambos specs a
`/opt/snippet-observability/prod/functional/`. Descargar la imagen Cypress
fijada en run.py después de revisar espacio y memoria disponibles. El ejecutor
usa una CPU/1,5 GB como en DEV; no se lanzan dos instancias simultáneas.

Instalar las unidades `systemd/snippet-functional-prod.{service,timer}` y
recargar systemd. Primero ejecutar manualmente `run.py --fixture prepare`, luego
`run.py`. Exigir acuse de Event API y evento SUCCESS en New Relic; no habilitar
el timer antes de esa verificación. Finalmente habilitar/iniciar el timer y
comprobar su siguiente ejecución. Frecuencia heredada: cada seis horas y al boot.
El probe se ejecuta sobre HTTPS PROD por loopback, con TLS verificado y Auth0 real;
el Ping separado cubre el acceso público externo.

El host publica sólo eventType/environment/checkName/result/durationMs/
failureCategory mediante la clave de ingesta ya instalada. El navegador no recibe
la clave New Relic. No se conservan logs ni capturas del login; el perfil es tmpfs.
Un HTTP 200 de Event API sin `success=true` y receipt no se considera envío válido.

## Condiciones y SLO

`alerts/` es una raíz Terraform independiente, como la raíz existente de SNI-86:
prepararla no introduce variables obligatorias ni recursos PROD en el plan DEV.
Requiere `newrelic_account_id=8718557`, `prod_alert_policy_id=8369826` y el GUID
verificado de `snippets-service (prod)`. La User API key va sólo en el entorno
privado del operador; no es la clave de ingesta del agente.

Antes de aplicar, importar recursos que ya existan y revisar el plan. Las
condiciones previstas son fallo funcional y ausencia durante 13 horas, siguiendo
DEV. Los SLO previstos conservan objetivos de DEV: API 99% / siete días y listado
96% / siete días. El volumen mínimo se interpreta en los tableros (100/25), no
como muestra suficiente por el solo hecho de tener un porcentaje.

La UI de Service Levels exige Full y advierte cargos. No activar ese acceso ni
aplicar el plan como si estuviera autorizado un costo no informado. Estos archivos
preparan el resultado; no acreditan recursos SLO nativos ni resultados del chequeo.
Hasta resolver acceso/cuenta y observar resultados, SNI-89 sigue In Progress.
