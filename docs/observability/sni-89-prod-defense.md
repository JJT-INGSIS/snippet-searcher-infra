# SNI-89 — Guía corta de monitoreo para la defensa

Estado del 23/11/2026: **preparación parcial verificada; ensayo y recepción humana pendientes**.
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
| UI/API pública inaccesible con réplicas sanas | **Sin checks públicos PROD acreditados**: panel Sintéticos exige Full con advertencia de cargos | Administrador debe resolver acceso incluido en el plan o acordar alternativa antes de activar costos. Un check manual 200 no reemplaza monitoreo periódico. |
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

## Ensayo: pendiente de acuerdo, no ejecutado

Propuesta explicada al usuario: detener sólo las réplicas de UI hasta 6 min,
recuperación automática de respaldo a los 8 min. Interrumpe la página, mantiene
API, bases y contenido. **No está aprobado el corte**; tampoco se programó un timer.
Primero confirmar receptor y ventana, ausencia de despliegues concurrentes,
réplicas originales, salud inicial y recuperación independiente de la conexión.

Registrar: comienzo UTC, condición, enlace del incidente, workflow, `Sent` de cada
canal, quién confirmó recepción y hora (idealmente pantalla bloqueada), recuperación
HTTP/Swarm y cierre automático del incidente. `Sent` prueba envío, no recepción.
Un mensaje de prueba del workflow tampoco acredita detección de la falla real.
Todavía no hay un incidente PROD de ensayo para usar como respaldo en la defensa.
La prueba del workflow indicó que el filtro no coincide con incidentes pasados;
no se acreditó ningún envío de muestra ni se generó un incidente artificial.
La lista de muting rules, sin filtros restrictivos, estaba vacía durante esta
revisión. Volver a comprobarla al acordar la ventana y tras la promoción final.

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
SNI-89 continúa en progreso hasta completar acceso/cobertura y evidencia humana.
