# Arquitectura y flujos de Snippet Searcher

Los diagramas de flujo de esta carpeta conservan decisiones y propuestas de su
momento. Algunos estados de implementación son históricos. Para el inventario
actual de componentes y conexiones, con evidencia y verificaciones pendientes por
ambiente, consultar [la base de observabilidad SNI-79](observability-baseline.md).

[ADR-001 / SNI-27](adr-001-async-processing.md) establece HTTP síncrono por defecto
y Redis Streams con outbox para los casos asíncronos acordados. El
[diseño mínimo](async-processing-design.md) explica sus contratos y recuperación.
Las capacidades de outbox, trabajos y consumidores existen en el código integrado;
su habilitación efectiva se comprueba por ambiente.

Snippets coordina los casos de uso y contiene Language. Permissions mantiene
ownership y sharing en su propia base. PrintScript expone operaciones de lenguaje
por HTTP y puede usar Redis para operaciones recuperables cuando están habilitadas.
La configuración define si Snippets usa storage local o Asset. La preparación y
activación de Auth0 también se verifican por separado en cada ambiente.

## Flujos principales

Para US8–10, consultar el [contrato de ejecución incremental
(SNI-45)](./execution-contract.md) y sus [fixtures](../contracts/execution-v1.json).
Documenta los contratos y decisiones de ejecución. La evidencia de integración
y despliegue se verifica en los tickets y releases correspondientes.

| Flujo | Fuente | Diagrama |
| --- | --- | --- |
| Crear y actualizar, por archivo o editor | US1–4 | [Creación y actualización](./flows/create-update-snippet.md) |
| Listar, visualizar y descargar | US5–6, US13 | [Consultas y descargas](./flows/read-snippets.md) |
| Compartir y resolver acceso | US7 | [Sharing y permisos](./flows/sharing-permissions.md) |
| Crear tests, ejecutarlos y correrlos tras un update | US8–9, US16 | [Tests](./flows/tests.md) |
| Pedir inputs y mostrar outputs durante la ejecución | US10 | [Ejecución interactiva](./flows/interactive-execution.md) |
| Configurar reglas y generar formateado | US11–12, US13 | [Formatting](./flows/formatting.md) |
| Configurar reglas y evaluar cumplimiento | US14–15, US5–6 | [Linting](./flows/linting.md) |
| Revalidar al cambiar el parser | Consigna general | [Revalidación del parser](./flows/parser-revalidation.md) |

## Recordatorios

- Parser inválido impide guardar; incumplir lint es un resultado; un test fallido nunca revierte el update.
- HTTP síncrono para operaciones puntuales. US12/15, activación de parser y US16 usan eventos con Redis Streams y outbox cuando sus componentes están habilitados.
- US9/10 necesitan salida incremental; la sesión interactiva además recibe inputs durante la ejecución.
- Conservar original y formateado. Asociar resultados a revisión de código, reglas y procesador; no publicar resultados obsoletos como actuales.
- El contrato con la UI para US1–7 está en [ui-integration.md de Snippets](https://github.com/JJT-INGSIS/snippets-service/blob/dev/docs/ui-integration.md) (SNI-26).
- Verificar contratos de UI/reglas, retención de revisiones, identidad del procesador y capacidad compartida en el código y release efectivos.

Para actualizar un diagrama, editar su bloque `mermaid`. Los enlaces entre archivos son relativos; desde Google Docs se utilizan enlaces absolutos de GitHub a estos mismos archivos.
