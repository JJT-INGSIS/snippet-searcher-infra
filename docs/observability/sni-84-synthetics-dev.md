# SNI-84 — Monitoreo externo de DEV

Estado al 10/11/2026: monitores y condiciones DEV activos. Se probó el flujo de
UI hasta recibir avisos de apertura y cierre; API y certificado aún requieren una
prueba de alerta específica. No se ha probado llamada telefónica.

## Monitores creados

En la cuenta New Relic compartida, con una ubicación pública en São Paulo:

| Nombre | Tipo y frecuencia | Comprobación |
| --- | --- | --- |
| `snippet-searcher-dev-ui-disponibilidad` | Ping, 15 minutos | HTTPS de la raíz DEV, validación TLS y GET |
| `snippet-searcher-dev-api-disponibilidad` | Ping, 15 minutos | HTTPS de `/api/languages`, validación TLS, GET, sin redirecciones y respuesta con `printscript` |
| `snippet-searcher-dev-certificado` | Certificate Check, diario | Certificado de DEV; umbral de 14 días antes de vencer |

Los dos ping se incluyen en el nivel Free según la documentación del proveedor.
La consola estimó 30 checks/mes para el monitor diario de certificado, con una
ubicación, frente a los 500 checks incluidos que mostraba la cuenta para estos
tipos de monitor. Esto no es un límite automático de gasto: comprobar el consumo
total y condiciones vigentes antes de agregar monitores o aumentar frecuencias.

## Alertas y destinos

- La política `snippet-searcher-dev-disponibilidad` contiene la condición
  `DEV - UI publica no disponible`, **activa al comprobarla nuevamente**.
  Su consulta usa `SyntheticCheck`, filtra el monitor concreto y cuenta fallas;
  agrega en ventanas de cinco minutos con event timer de 60 segundos y dispara
  un evento crítico si hay una falla registrada. New Relic documenta que un
  resultado fallido del monitor requiere tres intentos fallidos en esa ubicación.
  El ensayo de UI mostró que la apertura puede llegar después de la recuperación;
  considerar esa demora al usarlo para diagnóstico.
- El destino de correo `snippet-searcher-equipo-alertas` contiene las cuentas
  de los tres integrantes; no registrar sus direcciones en este repositorio.
- El destino `snippet-searcher-juanfran-push` apunta a la cuenta del responsable;
  se confirmó una notificación de prueba con el teléfono bloqueado. En un ensayo
  posterior de corte, el usuario confirmó la recepción de una notificación tras
  indicar que había bloqueado el teléfono.
- La condición `DEV - API publica no disponible` (ID 69670105) se creó en la misma
  política con ventana de cinco minutos, temporizador de 60 segundos y umbral crítico
  de al menos una falla. Se habilitó y aún no fue probada de extremo a extremo.
- La condición `DEV - Certificado requiere revision` (ID 69670214) está habilitada
  en la política independiente `snippet-searcher-dev-warnings`. Una falla del
  monitor puede indicar vencimiento próximo u otra falla de conectividad: revisar
  el resultado antes de decidir que el certificado venció. La política usa el
  workflow `snippet-searcher-dev-warnings-equipo`, solo por correo y con avisos
  configurados para apertura y cierre; aún falta probarlo de extremo a extremo.
- El workflow `snippet-searcher-dev-avisos-equipo` está habilitado para el ensayo y
  filtrado por la política DEV. Correo y push están configurados para apertura y
  cierre, no para cada cambio de estado.

## Evidencia de conectividad y seguridad

La VM DEV estaba encendida y las tareas del stack figuraban 1/1. Desde la VM,
ambas rutas HTTPS respondieron 200 con el hostname real y validación de certificado;
el catálogo de lenguajes incluyó `printscript`. Desde el exterior el HTTPS venció
por timeout y New Relic registró un fallo de UI. El puerto 80 devolvió redirección
308; UFW figuraba inactivo.

En Azure se observó la regla `AllowTeamWeb` de DEV para TCP 443 limitada a IP
del equipo y denegación predeterminada. Es consistente con el fallo de New Relic,
pero debe verificarse con un nuevo check tras cambiar la regla. No publicar direcciones
residenciales. Con autorización expresa del usuario se creó la regla adicional
`AllowNewRelicSynthetics` en el NSG de DEV, prioridad 320, TCP 443 y los cuatro
rangos oficiales de São Paulo publicados al momento. Se conservó `AllowTeamWeb`
sin abrir 443 a todo Internet. El cambio se hizo en Azure y sigue administrado
manualmente. Para reproducirlo, en el NSG de DEV crear `AllowNewRelicSynthetics`,
prioridad 320, dirección entrante, TCP, puerto destino 443 y los cuatro rangos
oficiales vigentes de São Paulo como origen. Conservar `AllowTeamWeb` y las demás
reglas; verificar prioridades, conflictos y rangos actuales antes de guardar.
No copiar la regla a PROD sin revisar su configuración.
Las IP pueden cambiar; New Relic recomienda permitir la lista global para cubrir
contingencias, por lo que limitar a una región tiene un riesgo de falsos positivos.
Tras el cambio, el monitor de UI registró respuestas exitosas y la ejecución manual
del monitor de API finalizó correctamente. La validación manual del monitor de
certificado desde São Paulo también resultó exitosa; no sustituye comprobar la
ejecución programada ni el aviso de vencimiento.

## Reconstruir la configuración manual

1. En **Synthetic Monitoring → Monitors**, crear el monitor `snippet-searcher-dev-certificado`
   como **Certificate Check** para `jjt-snippets-dev.duckdns.org`. Elegir São Paulo,
   frecuencia diaria y umbral de 14 días. Validar el monitor desde esa ubicación.
2. En **Alerts → Alert Policies**, recrear las políticas de disponibilidad y
   warnings con los nombres de arriba. Crear una condición NRQL por monitor con
   la consulta siguiente, usando el GUID del monitor correspondiente.

   ```sql
   SELECT filter(count(*), WHERE result = 'FAILED') AS 'Failures'
   FROM SyntheticCheck
   WHERE entityGuid = '<GUID_DEL_MONITOR>' AND NOT isMuted
   FACET location, monitorName
   ```

   Usar ventana de cinco minutos, agregación **Event timer** de 60 segundos y
   umbral mayor a cero al menos una vez en cinco minutos. Para UI y API, usar
   severidad crítica en la política de disponibilidad. Para certificado, usar
   severidad warning en la política de warnings.
3. En **Alerts → Workflows**, filtrar cada workflow por su política DEV. Agregar
   al workflow de disponibilidad el correo de los tres integrantes y el destino
   móvil de Juanfran. Agregar al workflow de warnings solo el correo del equipo.
   Para cada destino habilitar los eventos de apertura y cierre. En los detalles
   personalizados del correo de disponibilidad, indicar ambiente DEV, responsable
   técnico Juanfran y primer diagnóstico: revisar el synthetic, HTTPS, NGINX y
   la disponibilidad de la UI o API. Conservar el enlace al incidente en el correo.

## Ensayo de indisponibilidad

Con autorización se redujo temporalmente a cero la réplica de UI de DEV. New Relic
registró HTTP 502 desde São Paulo. El incidente crítico apareció con demora, después
de restaurar la UI; el usuario confirmó que recibió el push de activación. La
consola también identificó al correo como destino notificado. El historial de New
Relic registra `Sent` por destinatario tanto al abrir como al cerrar. Posteriormente,
Juanfran confirmó que el correo llegó a su casilla y que Juanchi y Thiago también lo
recibieron. No se verificó por separado la entrega de cada evento a cada integrante.
El evento de alerta luego figuró cerrado; no se
atribuyó ese cierre automáticamente a la recuperación porque la condición se había
deshabilitado durante el diagnóstico. Una comprobación pública manual posterior
terminó correctamente y la UI quedó en 1/1. Se canceló el temporizador de respaldo
y se devolvió el monitor a 15 minutos. El workflow y la condición de UI figuran
activos al comprobarlos nuevamente. El ensayo posterior verificó el cierre con
la condición activa.

En un segundo ensayo se programó la restauración de respaldo `sni84-ui-restore-test2`
para escalar la UI a una réplica a los ocho minutos. La revisión automática no pudo
aprobar la comprobación remota siguiente por límite de uso, por lo que no se realizó
ningún corte. No se confirmó ni canceló ese temporizador; si aún está pendiente,
ejecutará el ajuste a una réplica. Posteriormente se verificó y canceló el temporizador.
El monitor se devolvió a 15 minutos.

En un nuevo ensayo autorizado se estableció `sni84-ui-restore-test3` como respaldo y
se redujo UI a cero. Al perder el acceso a la vista de New Relic se restauró la UI de
inmediato, se comprobó 1/1 y se canceló el temporizador. El 10/11/2026, en hora de
Buenos Aires, el monitor registró HTTP 502 entre las 16:05 y las 16:07 y volvió a
dar resultados exitosos a partir de las 16:08. New Relic abrió el incidente crítico
a las 16:11, seis minutos después del primer check fallido. Juanfran confirmó la
recepción del aviso con el teléfono bloqueado y luego la del aviso de cierre.
La vista móvil mostró `Critical / Closed` con última actualización a las 16:12.
Esa hora corresponde a la actualización del incidente. La hora exacta de entrega
del push no quedó registrada. El monitor volvió a su frecuencia de 15 minutos.

El aviso móvil identifica el componente y el ambiente por el nombre
`DEV - UI publica no disponible`. El correo de las 16:11 del mismo ensayo muestra
el componente, el ambiente, el gráfico de la falla, el enlace **Ir al problema**,
el responsable técnico y la primera acción de diagnóstico en **Custom details**.
En **Alerts → Issues & Activity** de la cuenta
del equipo, se puede buscar por ese nombre y localizar el ensayo del 10/11/2026
mediante el identificador de incidente `1794337863244002`.
El responsable de los monitores y avisos es Juanfran. Ante una alerta de UI,
abrir los resultados del monitor, comprobar el código HTTP y contrastar la raíz
con `/api/languages`. Si la API responde y la raíz devuelve 502, revisar primero
el estado de la tarea de UI y su ruta en el proxy. Si fallan ambos checks,
comprobar el acceso a la VM y al proxy.

## Seguimiento

- Probar los avisos de API y certificado por separado y ensayar el procedimiento
  de silenciamiento durante el próximo apagado planificado de DEV.
- Los monitores de UI y API ya se importaron en Terraform. El plan y las diferencias
  de lectura están registrados en la [guía de Terraform](../../observability/newrelic/README.md).

## Operación de DEV y preparación de la defensa

Las condiciones de UI, API y certificado están activas. Antes de probar avisos,
confirmar que DEV está encendido y que UI y API tienen checks exitosos. Comprobar
que el workflow pertinente está habilitado y apunta a su política DEV. Registrar
caída, aviso, restauración y cierre en cada prueba controlada.

### Apagar y volver a encender DEV

1. Antes de apagar, entrar a **Alerts → Alert Conditions** y desactivar mediante
   **Enabled** las tres condiciones: `DEV - UI publica no disponible`,
   `DEV - API publica no disponible` y `DEV - Certificado requiere revision`.
   Confirmar que las tres casillas figuran desactivadas. Los monitores siguen
   ejecutándose y registrando resultados; las condiciones suspenden sus alertas.
2. Encender DEV y comprobar en **Synthetic Monitoring → Results** que UI y API
   vuelven a tener resultados exitosos. El certificado se comprueba diariamente;
   ejecutar una validación manual si hace falta comprobarlo sin esperar.
3. Volver a **Alert Conditions**, activar las tres casillas y verificar los
   workflows de disponibilidad y warnings. No modificar condiciones de PROD.

Una regla de silenciamiento acotada y con vencimiento es otra posibilidad, pero
no fue ensayada. Deshabilitar condiciones puede cerrar incidentes abiertos: revisar
antes y no interpretar el cierre como recuperación real. Si New Relic ya generó o
encoló avisos, podrían llegar después de deshabilitarlas. El aviso de certificado
usa un workflow de warning separado para no disparar el push crítico.

El monitor de API puede fallar por DNS, red, TLS, proxy o por la propia API; revisar
primero el detalle de Synthetic y luego el componente involucrado. El monitor de UI
tiene la misma limitación. Una verificación de contenido del catálogo ayuda a
distinguir un 200 incorrecto, pero no prueba el flujo autenticado de usuario.

Referencias: [límites de Synthetics](https://docs.newrelic.com/docs/synthetics/synthetic-monitoring/getting-started/monitor-limits/),
[reintentos de Synthetics](https://docs.newrelic.com/docs/synthetics/synthetic-monitoring/troubleshooting/troubleshoot-isolated-monitor-failures/),
[IPs públicas de Synthetics](https://docs.newrelic.com/docs/synthetics/synthetic-monitoring/administration/synthetic-public-minion-ips/)
y [reglas DEV previas](../sni-39-dns-red.md).
