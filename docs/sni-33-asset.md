# SNI-33 — Runtime persistente de Asset Service

> Integración operativa posterior: [SNI-43](sni-43-cd.md). Instalar Asset/Azurite
> no cambia el proveedor activo de Snippets ni migra contenido. La evidencia
> local de este documento no acredita activación remota.

## Alcance y estado

Asset Service oficial + Azurite, imágenes fijas, red interna y volumen persistente.
La aprobación de Thiago del 24/10/2026 permite usar el modelo oficial también en
prod: **no equivale a autorizar activar el proveedor, migrar o borrar datos**.

SNI-19 ya implementa el adaptador en Snippets. Este ticket no cambia Kotlin,
contratos HTTP, referencias, esquema de BD ni flujos de negocio. No incorpora
NGINX, Azure SDK propio, Redis ni autenticación. El volumen local anterior sigue
montado; `local` sigue siendo el proveedor por defecto.

La base de esta rama es infra/dev `c2180b28abc1b44b9aecfdf855ff7af544339523`,
que contiene el CD de SNI-25. Se preservaron los otros checkouts y sus cambios.

## Modelo y decisiones

```text
Snippets --HTTP :8080--> Asset Service --Blob :10000--> Azurite
    |                                                   |
    +--> PostgreSQL: referencia UUID                  /data
                                                        |
                                                  volumen asset_blobs
```

* Asset expone aplicación 8080 y administración 9090 **sólo en la red interna**.
  Azurite usa sólo Blob 10000; no arrancamos Queue/Table innecesariamente.
* Asset no autoriza usuarios: Snippets sigue consultando Permissions. No hay
  ruta pública hacia Asset ni blobs; NGINX no deberá agregarlas.
* La configuración oficial usa `AZURE_HOST=http://azurite`, cuenta pública del
  emulador `devstoreaccount1` y endpoint `:10000/devstoreaccount1`. Esa cuenta no
  es una credencial de Azure real. No recibe tokens de Packages, passwords de BD
  ni secretos de la VM. New Relic está deshabilitado.
* Asset y Azurite están fijados a los mismos digests probados en SNI-19. No se
  usa `latest`. Para cambiarlos hay que repetir contrato y persistencia.
* Azurite fija `--location /data` y monta el volumen exactamente allí. No se copia
  el `/workspace` del ejemplo suponiendo que basta para persistir. Se conserva
  `--skipApiVersionCheck` del fixture ya probado en SNI-19; es compatibilidad del
  emulador con el SDK, no una promesa de equivalencia con todos los servicios Azure.

| Elección | Beneficio | Costo y alternativa |
| --- | --- | --- |
| Asset + Azurite también en prod, aprobado por Thiago | Sigue el modelo suministrado y evita cuenta/costos/configuración adicional | Emulador autogestionado; no tiene alta disponibilidad ni garantías de Azure Storage administrado. No afirmamos que la cátedra haya certificado su uso productivo. |
| Proveedor explícito y runtime opt-in en Compose | Preserva los datos y arranques actuales | Requiere dos pasos conscientes: levantar runtime y aprobar cambio de proveedor; no lo activamos automáticamente. |
| Complemento `swarm/stack.asset.yaml` | Permite revisar/renderizar la ampliación sin romper bootstrap/CD de cinco servicios | Hasta SNI-43 no se despliega con herramientas operativas. Integrarlo directamente hoy haría que los verificadores antiguos rechazaran o ignoraran componentes. |
| Volumen local y una réplica de Azurite | Mínimo operativo acorde al Swarm independiente de un nodo | No replica archivos ni reemplaza backups; una caída de VM deja blobs indisponibles. Azure real/almacenamiento compartido requiere otra decisión. |
| Nodo `asset_storage=true` y actualización `stop-first` | Mantiene el disco en ubicación controlada y evita dos escritores sobre el volumen | Hay interrupción al actualizar; etiquetar varios nodos no comparte el disco. Mantener exactamente un nodo elegible por ambiente. |
| Probe aislado sin reconstruir aplicaciones | Verifica red, contrato y disco con rapidez, sin credenciales | No acredita todo el recorrido UI/Permissions/Snippets, que sigue en SNI-36. |

La división en archivos complementarios y el runner de prueba son detalles
reversibles de entrega de este plan; no cambian las garantías aprobadas de SNI-19.
No se agregan reintentos de PUT/DELETE: un timeout puede dejar resultado incierto.

Fuentes oficiales revisadas:
[Compose](https://github.com/austral-ingsis/asset-service/blob/96c08767c47f8969c7285b5322f834f97978e7a3/docker-compose.yml),
[configuración](https://github.com/austral-ingsis/asset-service/blob/96c08767c47f8969c7285b5322f834f97978e7a3/src/main/resources/application.yaml),
[contrato del adaptador y transición de SNI-19](https://github.com/JJT-INGSIS/snippets-service/blob/dev/docs/asset-storage.md).

## Compose: preparar no es activar

Las variables opcionales están en `.env.example`:

| Variable | Default |
| --- | --- |
| `STORAGE_PROVIDER` | `local` |
| `STORAGE_ASSET_BASE_URL` | `http://asset-service:8080` |
| `STORAGE_ASSET_CONTAINER` | `snippets` |
| `STORAGE_ASSET_CONNECT_TIMEOUT` | `2s` |
| `STORAGE_ASSET_READ_TIMEOUT` | `5s` |
| `STORAGE_ASSET_MAX_CONTENT_BYTES` | `1048576` |

No hay secretos nuevos que completar. El `.env` existente sigue siendo necesario
para construir/arrancar las aplicaciones; no se sobrescribe. Levantar sólo runtime:

```bash
docker compose --profile assets up -d --wait asset-service azurite
```

Esto **no cambia el proveedor**. Sólo tras inventario, respaldo/copia y aprobación,
seleccionar `STORAGE_PROVIDER=asset` en el `.env` del ambiente local y recrear Snippets
con una imagen que incluya SNI-19:

```bash
docker compose --profile assets up -d snippets-service asset-service azurite
```

No confundir `STORAGE_ASSET_BASE_URL` con `AZURE_HOST`: la primera apunta a Asset;
la segunda, usada sólo por Asset, apunta a Azurite. El navegador no usa ninguna.
`docker compose up` sin el perfil mantiene el comportamiento previo; al seleccionar
Asset es responsabilidad del arranque incluir sus servicios. No usamos una cadena
de dependencia rígida en Swarm: un outage debe producir un error técnico observable.

Healthchecks: Asset comprueba HTTP 200 en `/actuator/health` de 9090; el probe exige
además JSON con `status=UP`. Azurite comprueba su endpoint HTTP local (400/403 son
respuestas esperadas sin autorización). Ninguno sustituye una operación Blob real:
las lecturas/escrituras del probe son la evidencia de comunicación con el backend.

## Verificación rápida, sin credenciales ni VMs

Desde este checkout:

```bash
python3 -B -m unittest discover -s scripts -p 'test_*.py' -v
python3 -B scripts/validate_stack.py
python3 -B scripts/validate_asset_config.py
python3 -B scripts/verify_asset_persistence.py
```

El último comando exige Docker local mediante socket Unix; rechaza endpoints
remotos. Usa un proyecto nuevo `sni33-check-<uuid>`, ignora el `.env` real, no compila
aplicaciones y levanta sólo Asset, Azurite y probes temporales. No publica puertos.

1. Espera salud acotada y guarda tres objetos: vacío, Unicode/saltos y texto parecido
   a JSON. Todos usan la envoltura `snippet-content-v1` aprobada, no código crudo.
2. Lee y compara bytes exactos y hashes del código extraído.
3. Reemplaza realmente **ambos contenedores**, conservando el volumen, y repite lecturas.
4. Detiene sólo su Azurite de prueba: un objeto conocido debe dar fallo técnico,
   nunca 404 ni éxito. Lo reinicia y comprueba que el contenido sigue presente.
5. Borra únicamente las keys generadas bajo `infra-sni33-<uuid>`, verifica borrado
   idempotente y ausencia. No toca objetos de snippets ni usa borrado por antigüedad.
6. Retira sus contenedores y red incluso ante fallos; **no elimina ningún volumen**.
   El nombre del volumen queda impreso para diagnóstico. Si falla a mitad, puede
   conservar objetos de prueba; no hay limpieza global ni de datos ajenos.

El manifiesto de prueba circula por stdin/stdout y contiene sólo identificadores
y hashes de ejemplos conocidos. No registra código del usuario ni credenciales.
Las respuestas están acotadas y no se siguen redirects. CI repite renderizado,
suite y esta comprobación real. Su resultado local no demuestra estado de las VMs.

## Entrega concreta a SNI-43

No se modificaron `stack_release.py`, `bootstrap_swarm.py`, `deploy_service.py`,
`verify_stack.py`, journals, formato de `release.json`, ni workflows centrales.
Tampoco se editaron los registros de digests vigentes de dev/prod.

| Elemento | Contrato a integrar |
| --- | --- |
| Componentes permanentes adicionales | `asset-service`, `azurite`; no son aplicaciones arbitrarias autorizadas para CD |
| Imágenes | Digests literales en `stack.asset.yaml`, iguales a Compose; registrar referencias efectivas por ambiente |
| Red | Red por defecto del stack; ninguna publicación de 8080/9090/10000 de estos componentes |
| Persistencia | `<stack>_asset_blobs:/data`, conservar `snippets_content` y ambas bases |
| Nodo | Exactamente un nodo elegible con `asset_storage=true`, con el volumen original; no etiquetarlo automáticamente |
| Proveedor | `local` por defecto, `asset` sólo tras corte autorizado; registrar URL/container/timeouts/límite |
| Pruebas | Salud propia + Blob PUT/GET/DELETE real; seleccionar probe según proveedor, no exigir escritura local para Asset |
| Bloqueo/registro | Reutilizar lock, referencias vigentes y reconciliación de SNI-25; no reaplicar digests históricos del YAML |

`validate_asset_config.py` renderiza base + complemento en dev/prod y con ambos
proveedores. Exige imágenes fijas, mismo runtime en Compose/Swarm, ningún puerto
público ni secreto de BD/Packages nuevo, ubicación efectiva de datos y conservación
de servicios, montajes, secretos y configuración anterior. No requiere un manager.

**No ejecutar `docker stack deploy` directamente con este complemento.** El rollout
requiere SNI-43 con herramientas compatibles y referencias operativas actuales.
La regresión remota del stack ampliado pertenece a SNI-44; las observaciones del
backend/blob desplegado se registran también aquí cuando efectivamente se prueben.

## Corte y recuperación por ambiente

Se conserva el procedimiento de SNI-19, sin duplicar un migrador ni inventar una
segunda implementación del codec en infraestructura:

1. Inventariar todas las referencias y operaciones PENDING reales. No asumir que
   conteos históricos de prod=0 siguen vigentes.
2. Acordar qué conservar; por defecto conservarlo todo. Detener escritores y
   respaldar BD y contenido local, comprobando restauración.
3. Copiar cada referencia al container dedicado del ambiente con **el mismo UUID**
   y envoltura versionada. Si la key existe, verificarla; no sobrescribir diferencias.
4. Recuperar cada objeto y comparar código decodificado, tamaño y SHA-256 contra
   origen. No comparar el JSON remoto contra el archivo crudo. Verificar también PENDING.
5. Bajo herramientas compatibles/lock y aprobación, activar `asset` en dev,
   verificar, admitir escrituras y registrar resultados; luego repetir en prod.
6. Retener origen/backups. Si hubo escrituras nuevas, volver a `local` requiere
   reconciliar y copiar de regreso esas referencias: cambiar una variable no basta.

Si el inventario está vacío, registrar esa evidencia y la aprobación del ambiente;
no borrar ni recrear bases para simplificar. Un fallo de copia no autoriza limpieza
automática de blobs. Una pausa de VM no elimina volúmenes, pero éstos no son backups.

## Evidencia de esta entrega

Verificado localmente el 24/10/2026 con Docker Engine 29.3.1, Compose 5.1.1 y
Python 3.11. La suite final pasó **99 tests**, sin fallos ni omisiones (79 existentes
y 20 nuevos). Incluye HTTP controlado real, fallas, límites, protección del proyecto
de prueba y rechazo de configuración que altere datos/servicios ajenos.

* `validate_stack.py`: base dev/prod correcta.
* `validate_asset_config.py`: Compose opt-in y cuatro variantes Swarm correctas
  (dev/prod × local/asset), sin cambiar imágenes, secretos ni montajes existentes.
* `git diff --check`: correcto. Compose advierte que el campo histórico `version`
  es obsoleto; Swarm sigue renderizando ambos archivos correctamente.
* Prueba real completa: proyecto `sni33-check-ac87a1786425`. Salud de ambos servicios,
  PUT/GET con los tres contenidos, contenedores nuevos con datos idénticos,
  Azurite detenido → fallo técnico, reinicio → recuperación exacta, DELETE repetido
  y GET 404. Sin puertos publicados ni credenciales de Packages/BD.
* La primera ejecución detectó Accept incorrecto en el probe de administración
  (406) y limpieza sin perfiles activos; se corrigieron antes de la prueba final.
  Ninguna ejecución fallida se presenta como aceptación exitosa.
* Se retiraron sólo contenedores/redes de prueba y las keys generadas en las pruebas
  exitosas. Se conservaron tres volúmenes `sni33-check-…_asset_blobs`, incluidos los
  de intentos anteriores. Al terminar no quedaron contenedores SNI-33 ejecutándose;
  el único contenedor previo, `chopped_db`, conservó su estado saludable.

No se activó el proveedor en entornos persistentes, no se consultaron ni migraron
datos dev/prod y no se ejecutó un despliegue remoto. No se reconstruyeron aplicaciones
ni se acredita aquí el flujo completo Snippets → Permissions/PrintScript/Asset.
La aceptación funcional con UI y Permissions reales sigue en SNI-36. La integración
remota depende de la entrega operativa de SNI-43 y la autorización de cada ambiente.
