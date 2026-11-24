# SNI-89 — Guía corta de monitoreo para la defensa

Estado del 23/11/2026: **ensayo ejecutado y cierre verificado; recepción humana confirmada, cobertura restante pendiente**.
Cuenta New Relic US `8718557`. Usar UTC para correlacionar evidencias.

## Qué está comprobado

PROD estaba desasignada y se encendió para la revisión. A las 13:14:18Z estaban
saludables NGINX, UI, Snippets, Permissions, PrintScript y ambas bases; colector
1/1, agente y logs activos. Release sin journal pendiente, Auth0 y APM habilitados,
contenido **local**, sin Redis ni Asset. No se promovieron imágenes en esta revisión.

New Relic recibió datos recientes de host, Swarm, storage, PostgreSQL, APM y logs
con ambiente PROD. La UI cargó y `/api/languages` respondió 200 con TLS válido.
La visita controlada produjo `PageView` y `PageViewTiming` de
`snippet-searcher-prod-ui` a las 13:17:24Z. Esto no acredita un login ni el check
funcional autenticado. Ver [evidencia](../evidence/sni89-prod-2026-11-23.json).

## Cobertura y recuperación

Política [snippet-searcher-prod-disponibilidad](https://one.newrelic.com/redirect/entity/ODcxODU1N3xBSU9QU3xQT0xJQ1l8ODM2OTgyNg?account=8718557), ID `8369826`.
Estaba vacía: se agregaron condiciones y un workflow dedicado filtrado por ese ID.
El correo utiliza el destino grupal existente. El push inicialmente reutiliza el
destino de Juanfran. Se creó `snippet-searcher-thiago-prod-push` para la cuenta
de Thiago, pero no se asoció al workflow: Thiago confirmó que todavía no tiene
la app móvil y prefiere dejar la confirmación a Juanfran después. Crear ese destino
no cambia el push compartido de DEV ni acredita un dispositivo registrado.

| Falla | Condición / demora aproximada | Primera acción y recuperación |
| --- | --- | --- |
| Falta una réplica de UI/API/PrintScript/Permissions/DB/NGINX | `PROD - Servicio del stack sin replicas disponibles`, ID `70091549`; incumplimiento sostenido 2 min, ventana 60 s, retraso 120 s: estimar 4–6 min más notificación | Abrir Infraestructura y entrega, elegir PROD, identificar servicio y tareas. Recuperar la réplica/configuración mediante el procedimiento revisado, conservando volúmenes; comprobar HTTP y muestras normales. |
| Host/agente deja de enviar datos | `PROD - VM sin senal de infraestructura`, ID `70091779`; pérdida de señal 5 min, más entrega | Revisar Azure, agente, red e ingesta. No asumir que sólo puede ser VM apagada. Recuperar el componente afectado y comprobar nuevas muestras del host correcto. |
| Storage local falla | `PROD - Prueba de storage local fallo`, ID `70091854`; probe con `up=0` o `contentOk=0` sostenido 2 min, ventana 60 s y retraso 120 s: estimar 4–6 min más entrega. Configurada, no ensayada | Abrir Dependencias y procesamiento en PROD; revisar permisos, mount y espacio. No borrar datos ni llenar el disco real para demostrarlo. |
| UI/API pública inaccesible con réplicas sanas | Ping UI/API con resultados periódicos `SUCCESS` verificados a las 19:27:44Z. Condiciones habilitadas UI `70092793` / API `70093035`: Critical >0 fallos al menos una vez en 5 min | Revisar resultados del monitor y acceso público. Estas condiciones nuevas todavía no tienen ensayo de falla acreditado; el ensayo anterior utilizó réplicas. |
| Listado autenticado devuelve datos incorrectos | **Sin chequeo funcional PROD acreditado** | Requiere identidad/fixture PROD y resultados mínimos; no reutilizar credenciales DEV. Revisar SNI-85 con acceso autorizado. |
| Colector privado detenido mientras el agente de host sigue sano | **Sin condición específica de ausencia de Swarm/storage completada** | Las alertas de valores no detectan por sí solas que el colector dejó de publicar. Agregar pérdida de señal específica y ensayarla antes de ofrecer ese escenario. |
| Base con réplica sana pero conexión/bloqueos incorrectos | **Sin condición específica de dependencia SQL PROD completada** | Las métricas nativas llegan; eso no prueba alertas ni acceso de negocio. Revisar señales PostgreSQL/JDBC y acordar un ensayo aislado que no altere datos. |
| Redis/Asset/consumidor | **No aplica al inventario PROD de esta revisión** | Revalidar si la promoción final incorpora estos componentes; no demostrar una dependencia que no corre allí. |

Tableros compartidos, siempre seleccionar **PROD**:
[Aplicación y experiencia](https://one.newrelic.com/redirect/entity/ODcxODU1N3xWSVp8REFTSEJPQVJEfGRhOjEzNTk1OTkz),
[Dependencias y procesamiento](https://one.newrelic.com/redirect/entity/ODcxODU1N3xWSVp8REFTSEJPQVJEfGRhOjEzNTk1OTky),
[Infraestructura y entrega](https://one.newrelic.com/redirect/entity/ODcxODU1N3xWSVp8REFTSEJPQVJEfGRhOjEzNTk1OTkx).
Su configuración compartida ya incluye selector de ambiente; todavía se debe
acreditar el recorrido completo y los SLO propios de PROD con el acceso disponible.
Se verificó Infraestructura y entrega con **PROD** seleccionado: siete servicios
1/1, muestras Swarm a las 13:32:49Z, host y muestreador recientes y tabla de digests.
Llegar a `SnippetBackgroundSample` no demuestra que publicador/consumidor estén activos.

## Ensayo ejecutado: UI restaurada y cierre verificado

El usuario aprobó detener sólo UI hasta 6 min, con restauración independiente de
respaldo a los 8 min. **El ensayo ya ocurrió; no repetirlo al retomar.**
Sólo se cambió la cantidad de réplicas de UI 1→0→1, bajo el lock de despliegue.

| Hecho | Hora UTC del 23/11/2026 |
| --- | --- |
| Corte UI; página 502 y API `/api/languages` 200 | 13:50:11.587Z |
| Evento de apertura de incidente, faceta `ui` | 13:55:46.900Z |
| Push de activación `SUCCESS`, “Sent to 1 devices” | 13:55:57.310Z |
| Correo de activación `SUCCESS` | 13:55:57.734Z |
| Restauración iniciada | 13:56:11.563Z |
| Siete servicios saludables; UI nuevamente 200 | 13:56:17.979Z |
| Evento de cierre del incidente | 14:01:43.733Z |
| Push de cierre `SUCCESS`, “Sent to 1 devices” | 14:01:51.640Z |
| Correo de cierre `SUCCESS` | 14:01:56.826Z |

Incidente [949a7fc6-c98c-4b52-8973-4e45b07fd703](https://aiops.service.newrelic.com/accounts/8718557/incidents/949a7fc6-c98c-4b52-8973-4e45b07fd703/redirect),
issue `9ce1b606-d2c9-43dd-8bc2-75a35a952698`, condición de réplicas `70091549`.
Cierre comprobado mediante `NrAiIncident`; activación y cierre mediante
`NrAiNotification`, consultados a las 19:27Z. `openTime=13:52Z` y
`closeTime=13:56Z` son tiempos de la señal agregada; no son el momento de
procesamiento del evento ni la hora física de restauración.

El receipt remoto histórico quedó `RESTORED_AWAITING_ALERT_EVIDENCE`:
`allSevenHealthy`, `templateUnchanged` y `releaseUnchanged` son verdaderos.
Colector 1/1, unidad del ensayo terminada con éxito y timer de respaldo detenido
tras comprobar recuperación. No se cambiaron imágenes, bases, volúmenes ni contenido.
El receipt no fue reescrito; la evidencia posterior de cierre está en el JSON.

**Recepción humana confirmada por Thiago:** «sí, Juanfran lo vio».
Juanfran continúa como receptor móvil; no se lo contactó desde esta verificación.
No se informó la hora de lectura ni se confirmó cada mensaje por separado.
La confirmación se agrega a los envíos y al cierre ya verificados; no se repitió el corte. El intento previo de test del workflow no encontró incidentes;
el ensayo real posterior sí produjo los envíos de la tabla.

## Ping públicos verificados después del ensayo

A las 19:27:44Z, `SyntheticCheck` mostró dos muestras de cada monitor en los
30 minutos anteriores, desde `AWS_SA_EAST_1`: API último `SUCCESS` a las
19:16:00.824Z y UI último `SUCCESS` a las 19:18:01.217Z.
Las condiciones habilitadas UI `70092793` y API `70093035` pertenecen a la política
`8369826`, cuentan `result='FAILED'`, excluyen `isMuted` y agrupan por ubicación
y monitor. Disparan Critical >0 al menos una vez en cinco minutos.
Esto describe el umbral, no garantiza entrega al celular dentro de cinco minutos.
El ensayo de réplicas no valida por sí solo el disparo de estas condiciones nuevas.
También se revalidaron manualmente UI y `/api/languages`: HTTP 200, TLS válido.

La barrera Full/cargos observada a las 13:xxZ queda como antecedente; ya hay
resultados Ping periódicos comprobados. Esta continuación sólo leyó New Relic,
sin activar planes ni funciones pagas; no auditó cambios comerciales de otros operadores.
El chequeo autenticado, SLO, recorrido completo de tableros, pérdida independiente
del colector y alerta SQL específica siguen sin acreditarse.

## Antes de la presentación y después de la promoción final

1. Acordar que DEV y PROD permanezcan encendidos durante la demo y confirmar salud
   de aplicaciones/dependencias. No usar el inventario histórico como prueba actual.
2. Contrastar release/digests, storage y flags efectivos. Comprobar fechas de
   muestras de host, servicios, dependencias, APM/logs y Browser. Consultas en
   [prod-defense.nrql](../../observability/newrelic/prod-defense.nrql).
3. Comprobar resultados recientes de los checks públicos y funcional, una vez
   disponibles, condiciones/workflow activos, sin silencios aplicables al ensayo
   y destinos con receptor disponible. Revalidar permisos y notificaciones móviles.
4. Abrir el dashboard en PROD y tener un incidente de ensayo **real y cerrado** a
   mano. Las ventanas y frecuencia de los checks pueden demorar una alerta en vivo.
5. Al recuperar, exigir página/API normales, réplicas y muestras normales y cierre
   del incidente. Anotar cualquier cobertura pendiente en lugar de declararla sana.

## Decisiones y límites

Se reutiliza la instrumentación y los destinos existentes, con filtro PROD propio:
reduce cambios durante el cierre, a costo de depender de sus permisos y del canal
de terceros. Un destino separado para Thiago agrega configuración, pero evita
alterar los avisos que utiliza DEV. Se conserva la ventana/retraso de DEV para
réplicas: amortigua reinicios transitorios y demora el aviso. No se convierte la
ausencia de muestras en cero réplicas sanas. El host tiene una condición de pérdida
de señal; la pérdida independiente del colector sigue siendo una brecha explícita.

Consumo observado de toda la cuenta en `NrConsumption`, ventana de un día:
aproximadamente 0,298 GB, sumando categorías redondeadas visibles. La muestra
tiene demora y mezcla ambientes; no es costo mensual, presupuesto garantizado
ni autorización de un upgrade. Mantener el presupuesto de SNI-79 separado del
límite comercial que anuncie el plan.

Marco conceptual: análisis de trade-offs y registro de decisiones, capítulos 2/21
del [índice de Fundamentals of Software Architecture, 2.ª ed.](https://www.oreilly.com/library/view/fundamentals-of-software/9781098175504/).
La aplicación concreta es nuestra. No se activó Full, plan pago ni credencial nueva.
SNI-89 continúa en progreso por cobertura pendiente y revalidación final. La
recepción móvil ya fue confirmada por Thiago.

## Continuación de aceptación — 23/11, 21:36Z–21:40Z

Se recorrieron Dependencias y Aplicación seleccionando PROD. Ambas bases figuran
en conexiones/bloqueos; storage local `up=1`, `contentOk=1`, disco libre 69,842%,
con muestras de las 21:36:55Z. No hay muestras Redis, coherente con el inventario
PROD local anterior. No se infiere por ello el inventario actual de DEV.

Aplicación muestra Ping públicos SUCCESS. La fórmula API de siete días arroja
94,44% sobre 54 solicitudes: volumen insuficiente según el mínimo de 100 del
tablero. El chequeo autenticado tiene cero resultados. La fórmula del tablero
no acredita un recurso SLO nativo; éste sigue pendiente de comprobar/configurar.

La continuación por Azure/New Relic se interrumpió porque la Mac se bloqueó.
SSH PROD rechazó la identidad disponible y DEV agotó el tiempo de conexión; no
se modificaron claves ni reglas de red, ni se dedujo el estado de la VM del timeout.
Quedan pendientes el inventario/mounts/backups actuales y la identidad/fixture
propios de PROD para el chequeo autenticado.

## Chequeo autenticado preparado

El runner independiente está en
[prod-functional](../../observability/newrelic/prod-functional/README.md), con
fixture SNI-89, configuración privada y unidades systemd exclusivamente PROD.
Conserva el patrón de DEV: login real, listado HTTP 200, nombre exacto y contenido
esperado; publicación mínima de resultado. La raíz de condiciones/SLO es
independiente y no modifica el plan DEV. La frecuencia prevista es cada seis horas.

Validación local: 341 pruebas Python, incluidas tres garantías de privacidad y
credencial ausente; sintaxis de los specs/configuración comprobada. Terraform
1.13.5 fmt/validate aprobado con credencial ficticia sólo para validación local;
no se ejecutó plan/apply ni se llamó a New Relic para crear recursos. Esto no acredita
instalación ni éxito del chequeo. Falta acceso administrativo al tenant Auth0
`jjt-snippet-searcher` para verificar/provisionar una identidad propia de PROD:
la sesión de Thiago en el tenant del proyecto tiene el rol Editor - Specific Apps,
sin User Management; sólo muestra las aplicaciones DEV. El acceso al tenant
fue recuperado, pero ese rol no permite verificar ni crear el usuario dedicado.

Service Levels sigue mostrando la barrera Full con advertencia de cargos.
Plan Summary y Plans & Pricing no pudieron cargar la información de la cuenta.
No se activó acceso pago ni se supuso un costo. Los SLO nativos preparados
conservan los objetivos ya usados en DEV: 99% API y 96% listado, en siete días.
