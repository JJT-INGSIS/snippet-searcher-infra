locals {
  dashboard_environment = "{{environment}}"
  dashboard_apm         = "capture(appName, r'.* [(](?P<environment>dev|prod)[)]') = ${local.dashboard_environment}"
  dashboard_browser     = "appName = concat('snippet-searcher-', ${local.dashboard_environment}, '-ui')"
  dashboard_functional  = "checkName = concat('snippet-searcher-', ${local.dashboard_environment}, '-functional-listing')"
  dashboard_synthetics  = "capture(monitorName, r'snippet-searcher-(?P<environment>dev|prod)-.*') = ${local.dashboard_environment}"
  dashboard_scoped      = "environment = ${local.dashboard_environment}"
  dashboard_native      = "label.environment = ${local.dashboard_environment}"

  dashboards = {
    app = {
      name        = "Aplicación y experiencia"
      description = "Disponibilidad pública, listado real, SLI, latencia, errores y trazas de los servicios."
      widgets = [
        {
          title         = "API (7 d) · <${local.slos.api.volume} solicitudes: muestra insuficiente"
          visualization = "viz.billboard"
          query         = "FROM Log SELECT percentage(count(*), WHERE ${local.http_success}) AS 'SLI (%) · objetivo ${local.slos.api.target}%', count(*) AS 'Solicitudes válidas', count(*) * ${(100 - local.slos.api.target) / 100} - filter(count(*), WHERE ${local.http_failure}) AS 'Presupuesto restante (solicitudes)' WHERE ${local.dashboard_scoped} AND ${local.api_valid} SINCE 7 days ago"
          fixed_window  = true
        },
        {
          title         = "Listado (7 d) · <${local.slos.functional.volume} resultados: muestra insuficiente"
          visualization = "viz.billboard"
          query         = "FROM SnippetFunctionalCheck SELECT percentage(count(*), WHERE result = 'SUCCESS') AS 'SLI (%) · objetivo ${local.slos.functional.target}%', count(*) AS 'Resultados', count(*) * ${(100 - local.slos.functional.target) / 100} - filter(count(*), WHERE result = 'FAILURE') AS 'Presupuesto restante (resultados)' WHERE ${local.dashboard_scoped} AND ${local.dashboard_functional} AND ${local.functional_valid} SINCE 7 days ago"
          fixed_window  = true
        },
        {
          title         = "HTTP 2xx y 5xx por ruta"
          visualization = "viz.line"
          query         = "FROM Log SELECT filter(count(*), WHERE ${local.http_success}) AS '2xx', filter(count(*), WHERE ${local.http_failure}) AS '5xx' WHERE ${local.dashboard_scoped} AND ${local.api_valid} FACET route TIMESERIES"
          fixed_window  = false
        },
        {
          title         = "Latencia HTTP de ingreso p50, p95 y p99 (ms)"
          visualization = "viz.line"
          query         = "FROM Log SELECT percentile(request_time * 1000, 50, 95, 99) WHERE ${local.dashboard_scoped} AND ${local.api_valid} FACET route TIMESERIES"
          fixed_window  = false
        },
        {
          title         = "Monitores públicos: último resultado"
          visualization = "viz.table"
          query         = "FROM SyntheticCheck SELECT latest(result), latest(timestamp) WHERE ${local.dashboard_synthetics} FACET monitorName, location"
          fixed_window  = false
        },
        {
          title         = "Listado de Cypress · último resultado en 7 días"
          visualization = "viz.table"
          query         = "FROM SnippetFunctionalCheck SELECT latest(result) AS 'Resultado', latest(timestamp) AS 'Hora del chequeo', latest(durationMs) AS 'Duración (ms)' WHERE ${local.dashboard_scoped} AND ${local.dashboard_functional} AND ${local.functional_valid} SINCE 7 days ago"
          fixed_window  = true
        },
        {
          title         = "Listado de Cypress · fallos por categoría en 7 días"
          visualization = "viz.table"
          query         = "FROM SnippetFunctionalCheck SELECT count(*) AS 'Fallos', latest(timestamp) AS 'Último fallo' WHERE ${local.dashboard_scoped} AND ${local.dashboard_functional} AND result = 'FAILURE' FACET failureCategory SINCE 7 days ago"
          fixed_window  = true
        },
        {
          title         = "Tráfico y errores APM por servicio"
          visualization = "viz.line"
          query         = "FROM Transaction SELECT rate(count(*), 1 minute) AS 'rpm', percentage(count(*), WHERE error IS true) AS 'Errores (%)' WHERE ${local.dashboard_apm} FACET appName TIMESERIES"
          fixed_window  = false
        },
        {
          title         = "Snippets hacia Permissions y PrintScript (p95 ms)"
          visualization = "viz.line"
          query         = "FROM Span SELECT percentile(duration * 1000, 95) WHERE ${local.dashboard_apm} AND (name LIKE 'External/permissions-service%' OR name LIKE 'External/printscript-service%' OR name LIKE 'External/UnknownHost/%') FACET name TIMESERIES LIMIT 10"
          fixed_window  = false
        },
        {
          title         = "Carga web p75 (ms)"
          visualization = "viz.line"
          query         = "FROM PageViewTiming SELECT percentile(largestContentfulPaint * 1000, 75) WHERE ${local.dashboard_browser} AND timingName = 'largestContentfulPaint' TIMESERIES"
          fixed_window  = false
        },
        {
          title         = "Errores JavaScript por intervalo"
          visualization = "viz.line"
          query         = "FROM JavaScriptError SELECT count(*) WHERE ${local.dashboard_browser} TIMESERIES"
          fixed_window  = false
        },
        {
          title         = "Altas de snippets: errores técnicos y request ID"
          visualization = "viz.table"
          query         = "FROM Log SELECT latest(status), latest(request_time), latest(upstream_status), latest(timestamp) WHERE ${local.dashboard_scoped} AND logtype = 'nginx-ingress' AND method = 'POST' AND path = '/api/snippets' AND ${local.http_failure} FACET request_id LIMIT 10"
          fixed_window  = false
        },
        {
          title         = "Trazas de alta por resultado"
          visualization = "viz.table"
          query         = "FROM Transaction SELECT latest(name), latest(duration * 1000), latest(outcome), latest(timestamp) WHERE ${local.dashboard_apm} AND name LIKE '%snippets%POST%' AND traceId IS NOT NULL FACET traceId LIMIT 10"
          fixed_window  = false
        }
      ]
    }
    dependencies = {
      name        = "Dependencias y procesamiento"
      description = "PostgreSQL, Redis, storage y progreso de publicación, entrega y procesamiento."
      widgets = [
        {
          title         = "PostgreSQL · conexiones y límite del servidor"
          visualization = "viz.line"
          query         = "FROM PostgresqlDatabaseSample SELECT max(db.connections), max(db.maxconnections) WHERE ${local.dashboard_native} FACET label.service TIMESERIES"
          fixed_window  = false
        },
        {
          title         = "PostgreSQL · sesiones bloqueadas"
          visualization = "viz.line"
          query         = "FROM PgCustomQuerySample SELECT max(blocked_sessions) WHERE ${local.dashboard_native} FACET label.service TIMESERIES"
          fixed_window  = false
        },
        {
          title         = "JDBC · tiempo en consultas (ms)"
          visualization = "viz.line"
          query         = "FROM Span SELECT percentile(duration * 1000, 95) WHERE ${local.dashboard_apm} AND name LIKE 'Datastore/statement/Postgres/%' FACET appName TIMESERIES"
          fixed_window  = false
        },
        {
          title         = "Redis · memoria usada y límite (bytes)"
          visualization = "viz.line"
          query         = "FROM RedisSample SELECT max(system.usedMemoryBytes), max(system.maxmemoryBytes) WHERE ${local.dashboard_native} FACET label.service TIMESERIES"
          fixed_window  = false
        },
        {
          title         = "Redis · estado AOF y clientes"
          visualization = "viz.table"
          query         = "FROM RedisSample SELECT latest(db.aofLastWriteStatus), latest(db.aofLastBgrewriteStatus), latest(net.connectedClients) WHERE ${local.dashboard_native} FACET label.service"
          fixed_window  = false
        },
        {
          title         = "Storage · último estado y espacio disponible (%)"
          visualization = "viz.table"
          query         = "FROM SnippetStorageSample SELECT latest(up), latest(contentOk), latest(availableBytes * 100 / totalBytes) AS 'Libre (%)', latest(timestamp) WHERE ${local.dashboard_scoped} AND up IS NOT NULL FACET service"
          fixed_window  = false
        },
        {
          title         = "Outbox · pendientes y reintentos"
          visualization = "viz.line"
          query         = "FROM SnippetBackgroundSample SELECT max(pending), max(retrying) WHERE ${local.dashboard_scoped} AND aspect = 'outbox' AND samplerError = false TIMESERIES"
          fixed_window  = false
        },
        {
          title         = "Outbox · edad del pendiente más antiguo (s)"
          visualization = "viz.line"
          query         = "FROM SnippetBackgroundSample SELECT max(oldestPendingSeconds) WHERE ${local.dashboard_scoped} AND aspect = 'outbox' AND samplerError = false TIMESERIES"
          fixed_window  = false
        },
        {
          title         = "Redis Streams · lag conocido y entregas sin ACK"
          visualization = "viz.line"
          query         = "FROM SnippetBackgroundSample SELECT filter(max(lag), WHERE lagKnown = true) AS 'Lag conocido', max(pending) AS 'PEL' WHERE ${local.dashboard_scoped} AND aspect = 'stream' AND samplerError = false TIMESERIES"
          fixed_window  = false
        },
        {
          title         = "Trabajos · edad del elegible, progreso y PEL (s)"
          visualization = "viz.line"
          query         = "FROM SnippetBackgroundSample SELECT ${local.eligible_age} AS 'Elegible más antiguo', filter(max(stalestProgressSeconds), WHERE state = 'RUNNING') AS 'Mayor tiempo sin progreso', filter(max(oldestPendingIdleSeconds), WHERE aspect = 'stream' AND groupExists = true AND samplerError = false) AS 'Mayor idle PEL', ${local.consumer_delay} AS 'Señal de consumidor' WHERE ${local.dashboard_scoped} AND (aspect = 'stream' OR aspect = 'jobs') TIMESERIES"
          fixed_window  = false
        },
        {
          title         = "Trabajos · activos y terminados por estado"
          visualization = "viz.line"
          query         = "FROM SnippetBackgroundSample SELECT max(`count`) WHERE ${local.dashboard_scoped} AND aspect IN ('jobs', 'jobs-finished') AND samplerError = false AND state != 'all' FACET aspect, state TIMESERIES"
          fixed_window  = false
        },
        {
          title         = "Capacidad retenida por trabajos"
          visualization = "viz.line"
          query         = "FROM SnippetBackgroundSample SELECT max(heldBackground), max(unknownPermits) WHERE ${local.dashboard_scoped} AND aspect = 'capacity' AND samplerError = false TIMESERIES"
          fixed_window  = false
        }
      ]
    }
    infra = {
      name        = "Infraestructura y entrega"
      description = "Estado de la VM, réplicas, tareas, pérdida de telemetría e imágenes del release."
      widgets = [
        {
          title         = "VM · CPU y memoria (%)"
          visualization = "viz.line"
          query         = "FROM SystemSample SELECT average(cpuPercent), average(memoryUsedPercent) WHERE ${local.dashboard_scoped} TIMESERIES"
          fixed_window  = false
        },
        {
          title         = "Frescura de VM, Swarm y muestreador"
          visualization = "viz.table"
          query         = "FROM SystemSample, SnippetSwarmSample, SnippetBackgroundSample SELECT latest(timestamp), count(*) WHERE ${local.dashboard_scoped} FACET eventType()"
          fixed_window  = false
        },
        {
          title         = "Réplicas disponibles y configuradas"
          visualization = "viz.table"
          query         = "FROM SnippetSwarmSample SELECT latest(running), latest(desired), latest(timestamp) WHERE ${local.dashboard_scoped} FACET service"
          fixed_window  = false
        },
        {
          title         = "Tareas fallidas y OOM según ventana del colector"
          visualization = "viz.line"
          query         = "FROM SnippetSwarmSample SELECT max(failedTasks), max(oomKilled) WHERE ${local.dashboard_scoped} FACET service TIMESERIES"
          fixed_window  = false
        },
        {
          title         = "Digest en ejecución, esperado y concordancia"
          visualization = "viz.table"
          query         = "FROM SnippetSwarmSample SELECT latest(image), latest(expectedImage), latest(imageState) WHERE ${local.dashboard_scoped} FACET service"
          fixed_window  = false
        },
        {
          title         = "Imágenes observadas en cada intervalo de despliegue"
          visualization = "viz.line"
          query         = "FROM SnippetSwarmSample SELECT uniqueCount(image) AS 'Imágenes en ejecución', uniqueCount(expectedImage) AS 'Imágenes esperadas' WHERE ${local.dashboard_scoped} AND imageState IN ('match', 'mismatch') FACET service TIMESERIES"
          fixed_window  = false
        },
        {
          title         = "Logs de infraestructura por fuente"
          visualization = "viz.line"
          query         = "FROM Log SELECT count(*) WHERE ${local.dashboard_scoped} AND logtype IN ('host-kernel','host-docker','nginx-ingress') FACET logtype TIMESERIES"
          fixed_window  = false
        }
      ]
    }
  }
}

resource "newrelic_one_dashboard_json" "overview" {
  for_each   = local.dashboards
  account_id = var.newrelic_account_id
  json = jsonencode({
    name        = "Snippet Searcher - ${each.value.name}"
    description = each.value.description
    permissions = "PUBLIC_READ_ONLY"
    variables = [{
      name                = "environment"
      title               = "Ambiente"
      type                = "ENUM"
      isMultiSelection    = false
      replacementStrategy = "STRING"
      defaultValues       = [{ value = { string = "dev" } }]
      items = [
        { title = "DEV", value = "dev" },
        { title = "PROD", value = "prod" },
      ]
      options = { excluded = false }
    }]
    pages = [{
      name = each.value.name
      widgets = [for index, widget in each.value.widgets : {
        title         = widget.title
        visualization = { id = widget.visualization }
        layout        = { column = 1 + (index % 2) * 6, row = 1 + floor(index / 2) * 3, height = 3, width = 6 }
        rawConfiguration = merge({
          nrqlQueries = [{ accountIds = [var.newrelic_account_id], query = widget.query }]
          }, widget.fixed_window ? {
          platformOptions = { ignoreTimeRange = true }
        } : {})
      }]
    }]
  })
}

output "dashboard_links" {
  description = "Enlaces de New Relic para el equipo."
  value       = { for key, dashboard in newrelic_one_dashboard_json.overview : key => dashboard.permalink }
}
