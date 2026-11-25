# Guía de defensa

Prepará dos sesiones Auth0 de prueba, un archivo `.prs` válido y un snippet de prueba que puedas editar. Confirmá qué versión está desplegada, que la UI y Snippets responden y, para los trabajos de fondo, que Redis, el publicador y el consumidor están activos en el ambiente elegido. [Operación por ambiente](operations.md)

Usá PROD para mostrar los flujos que estén verificados allí. Para trabajos de fondo, activación del parser y fallos controlados, usá DEV con el worker activo o el entorno local de integración. El último [relevamiento documentado de PROD](observability/README.md#evidencia-y-defensa) acreditó ingreso, telemetría y notificaciones, con Redis y Asset inactivos en ese momento. Volvé a comprobar el inventario después de promover.

| Historias | Ambiente de demostración | Recorrido y qué comprobar | Prueba o evidencia |
| --- | --- | --- | --- |
| US1 y US3 · Alta por archivo y por editor | DEV | Creá un snippet de cada forma. Elegí lenguaje y versión, guardá y abrí el detalle para comprobar el código original. | [Prueba con backend real](https://github.com/JJT-INGSIS/snippet-searcher-ui/blob/dev/cypress/e2e/backend/usability.cy.ts) |
| US2 y US4 · Actualización por archivo y por editor | DEV | En el mismo detalle, reemplazá el código desde un archivo y luego editá desde el editor. Comprobá que se conserva el ID. Intentá guardar código inválido y verificá el diagnóstico y la conservación del último guardado válido. | [Prueba de navegador](https://github.com/JJT-INGSIS/snippet-searcher-ui/blob/dev/cypress/e2e/contracts/snippet-update.cy.ts) |
| US5 y US6 · Listado y detalle | DEV | Buscá por nombre, cambiá relación, orden y página, y abrí un resultado autorizado. Revisá contenido y capacidades del detalle. | [Consultas y permisos](architecture/flows/read-snippets.md) · [Prueba con backend real](https://github.com/JJT-INGSIS/snippet-searcher-ui/blob/dev/cypress/e2e/backend/usability.cy.ts) |
| US7 · Compartir | PROD | El propietario busca y comparte con la otra sesión. El lector lo encuentra en compartidos y puede ver código y tests; el detalle muestra sólo lectura. | [Aceptación con dos cuentas en PROD](https://linear.app/snippet-searcher/issue/SNI-90) |
| US8 · Definir tests y US9 · Ejecutarlos | DEV | Guardá entradas y salidas esperadas. Ejecutá el test desde el detalle y verificá eventos y comparación final. Usá una expectativa distinta para mostrar un test desaprobado. | [Prueba con backend real](https://github.com/JJT-INGSIS/snippet-searcher-ui/blob/dev/cypress/e2e/backend/execution.cy.ts) |
| US10 · Ejecución interactiva | DEV | Corré código que emita un mensaje y pida una entrada. Verificá que el primer resultado aparezca antes de responder, enviá el input y comprobá el estado terminal. | [Flujo NDJSON](architecture/flows/interactive-execution.md) · [Prueba con backend real](https://github.com/JJT-INGSIS/snippet-searcher-ui/blob/dev/cypress/e2e/backend/execution.cy.ts) |
| US11 · Reglas de formato, US12 · Reformateo y US13 · Descarga | DEV con worker | Guardá una regla para un lenguaje y versión. Mostrá la confirmación del guardado y después el progreso del lote. Desde el detalle descargá la variante formateada y el original para comparar. | [Prueba con Redis y backend real](https://github.com/JJT-INGSIS/snippet-searcher-ui/blob/dev/cypress/e2e/backend/formatting.cy.ts) |
| US14 · Reglas de lint y US15 · Cumplimiento | DEV con worker | Guardá una regla que produzca una infracción en un snippet de prueba. Esperá el lote y comprobá el diagnóstico en detalle y el filtro por estado en listado. | [Prueba con backend real](https://github.com/JJT-INGSIS/snippet-searcher-ui/blob/dev/cypress/e2e/backend/lint.cy.ts) |
| US16 · Tests automáticos | DEV con worker | Actualizá un snippet con tests guardados. Mostrá que el guardado confirma primero y que después aparecen el progreso y la comparación correspondientes a esa actualización. | [Prueba con backend real](https://github.com/JJT-INGSIS/snippet-searcher-ui/blob/dev/cypress/e2e/backend/automatic-tests.cy.ts) |

Los enlaces a pruebas permiten reproducir el comportamiento. Para correr las de backend con Cypress, seguí la [configuración de UI](https://github.com/JJT-INGSIS/snippet-searcher-ui/blob/dev/README.md) y usá el stack local con los proveedores que requiere cada caso.

## Revalidación del parser

En un entorno local aislado con Redis activo, prepará un snippet de prueba y obtené la revisión efectiva de la capacidad `validate` de PrintScript. El operador autorizado activa esa revisión para el lenguaje y versión, consulta el trabajo y comprueba el avance. El lote registra el diagnóstico y conserva el código y la propiedad. Mostrar por separado los resultados inválidos y las fallas técnicas. Un despliegue por sí solo no activa la revisión. [Flujo y comando operativo](architecture/flows/parser-revalidation.md) · [Pruebas de revalidación](https://github.com/JJT-INGSIS/snippets-service/tree/dev/src/test/kotlin/com/jjt/ingsis/snippets/revalidation)

## Observabilidad

Mostrá un Trace ID de un alta de DEV y ubicá Snippets, Permissions y PrintScript. Para demostrar alertas, seguí una señal hasta su condición, incidente, correo o push y cierre tras la recuperación. La guía de New Relic enlaza los ensayos y distingue lo verificado en DEV y PROD. [Evidencia y consultas](observability/README.md#evidencia-y-defensa)
