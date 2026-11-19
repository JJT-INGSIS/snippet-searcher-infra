locals {
  threshold_conditions = {
    printscript_replicas = {
      title       = "DEV - PrintScript sin réplicas disponibles"
      description = "Thiago. En Infraestructura y entrega revisar réplicas, task rechazada, OOM e imagen; confirmar el impacto siguiendo la traza de una alta. Recuperación: dos muestras normales."
      critical    = true
      query       = "SELECT filter(count(*), WHERE running = 0 OR running < desired) FROM SnippetSwarmSample WHERE environment = 'dev' AND service = 'printscript-service'"
      threshold   = 0
      duration    = 120
    }
    other_replicas = {
      title       = "DEV - Servicio del stack sin réplicas disponibles"
      description = "Thiago. En Infraestructura y entrega identificar el servicio afectado y revisar tareas, OOM y despliegue. Recuperación: réplicas disponibles nuevamente."
      critical    = true
      query       = "SELECT filter(count(*), WHERE running = 0 OR running < desired) FROM SnippetSwarmSample WHERE environment = 'dev' AND service != 'printscript-service' FACET service"
      threshold   = 0
      duration    = 120
    }
    consumer_stalled = {
      title       = "DEV - Consumidor de Redis detenido o atrasado"
      description = "Juanchi. En Dependencias y procesamiento revisar lag conocido, edad de trabajo elegible, outbox y errores del consumidor. Recuperación: el grupo retoma el procesamiento y baja el atraso."
      critical    = true
      query       = "SELECT ${local.consumer_delay} FROM SnippetBackgroundSample WHERE environment = 'dev' AND (aspect = 'stream' OR (aspect = 'jobs' AND reaction = 'all'))"
      threshold   = 300
      duration    = 300
    }
    storage = {
      title       = "DEV - Prueba de storage local falló"
      description = "Thiago. En Dependencias y procesamiento revisar el probe, volumen, permisos y espacio. Recuperación: lectura, escritura y contenido correctos."
      critical    = true
      query       = "SELECT filter(count(*), WHERE up = 0 OR contentOk = 0) FROM SnippetStorageSample WHERE environment = 'dev' AND service = 'storage-local' AND up IS NOT NULL"
      threshold   = 0
      duration    = 120
    }
    outbox = {
      title       = "DEV - Publicador con eventos de outbox atrasados"
      description = "Juanchi. En Dependencias y procesamiento revisar la edad del outbox, reintentos y escritura en Redis. Recuperación: el pendiente más antiguo vuelve al umbral."
      critical    = false
      query       = "SELECT max(oldestPendingSeconds) FROM SnippetBackgroundSample WHERE environment = 'dev' AND aspect = 'outbox' AND samplerError = false"
      threshold   = 60
      duration    = 300
    }
    job_stalled = {
      title       = "DEV - Trabajo RUNNING sin progreso"
      description = "Juanchi. En Dependencias y procesamiento revisar lease, progreso y trazas de background. Recuperación: el trabajo vuelve a progresar o sale de RUNNING."
      critical    = false
      query       = "SELECT filter(count(*), WHERE state = 'RUNNING' AND stalestProgressSeconds > 60) FROM SnippetBackgroundSample WHERE environment = 'dev' AND aspect = 'jobs' AND samplerError = false"
      threshold   = 0
      duration    = 300
    }
    sampler_error = {
      title       = "DEV - Muestreador asíncrono con errores"
      description = "Juanchi. En Dependencias y procesamiento identificar el aspecto, comprobar Redis y PostgreSQL y revisar los logs de Snippets. Recuperación: el muestreador vuelve a entregar lecturas válidas."
      critical    = false
      query       = "SELECT filter(count(*), WHERE samplerError = true) FROM SnippetBackgroundSample WHERE environment = 'dev' FACET aspect"
      threshold   = 0
      duration    = 300
    }
    disk_free = {
      title       = "DEV - Poco espacio libre en volumen observado"
      description = "Thiago. En Dependencias y procesamiento identificar el volumen y medir crecimiento antes de liberar espacio. Recuperación: espacio libre por encima del 15%."
      critical    = false
      query       = "SELECT 100 - min(availableBytes * 100 / totalBytes) FROM SnippetStorageSample WHERE environment = 'dev' AND totalBytes > 0 FACET service"
      threshold   = 85
      duration    = 300
    }
    host_saturation = {
      title       = "DEV - Saturación sostenida de CPU o memoria"
      description = "Thiago. En Infraestructura y entrega revisar qué recurso está saturado y cruzar con réplicas, OOM y tareas. Recuperación: CPU por debajo de 85% y memoria por debajo de 90%."
      critical    = false
      query       = "SELECT filter(count(*), WHERE cpuPercent >= 85 OR memoryUsedPercent >= 90) FROM SystemSample WHERE environment = 'dev'"
      threshold   = 0
      duration    = 600
    }
    postgres_blocked = {
      title       = "DEV - PostgreSQL con sesiones bloqueadas"
      description = "Thiago. En Dependencias y procesamiento identificar la base y revisar bloqueos y duración de consultas. Recuperación: las sesiones dejan de estar bloqueadas."
      critical    = false
      query       = "SELECT max(blocked_sessions) FROM PgCustomQuerySample WHERE label.environment = 'dev' FACET label.service"
      threshold   = 0
      duration    = 300
    }
    image_mismatch = {
      title       = "DEV - Imagen desplegada difiere del release"
      description = "Thiago. En Infraestructura y entrega comparar digest real y esperado y revisar el último CD. Recuperación: imageState vuelve a match."
      critical    = false
      query       = "SELECT filter(count(*), WHERE imageState = 'mismatch') FROM SnippetSwarmSample WHERE environment = 'dev' AND imageState IN ('match', 'mismatch') FACET service"
      threshold   = 0
      duration    = 300
    }
  }

  loss_conditions = {
    host = {
      title           = "DEV - VM sin señal de infraestructura"
      description     = "Thiago. En Infraestructura y entrega cruzar la última muestra con los monitores públicos. Revisar estado de Azure y del agente. Recuperación: vuelve SystemSample."
      critical_policy = true
      query           = "SELECT count(*) FROM SystemSample WHERE environment = 'dev'"
      expiration      = 300
    }
    swarm = {
      title           = "DEV - Colector Swarm sin muestras"
      description     = "Thiago. En Infraestructura y entrega comparar con SystemSample y revisar el colector. Recuperación: vuelven las muestras de Swarm."
      critical_policy = false
      query           = "SELECT count(*) FROM SnippetSwarmSample WHERE environment = 'dev'"
      expiration      = 600
    }
    background = {
      title           = "DEV - Muestreador de trabajos sin resultados"
      description     = "Juanchi. En Dependencias y procesamiento comprobar si hubo deploy de Snippets y revisar el muestreador. Recuperación: vuelve la muestra de outbox."
      critical_policy = false
      query           = "SELECT count(*) FROM SnippetBackgroundSample WHERE environment = 'dev' AND aspect = 'outbox'"
      expiration      = 300
    }
  }
}

resource "newrelic_nrql_alert_condition" "threshold" {
  for_each = local.threshold_conditions

  account_id                   = var.newrelic_account_id
  policy_id                    = each.value.critical ? var.dev_critical_policy_id : var.dev_warning_policy_id
  type                         = "static"
  name                         = each.value.title
  description                  = each.value.description
  runbook_url                  = local.runbook_url
  aggregation_method           = "event_flow"
  aggregation_window           = 60
  aggregation_delay            = 120
  fill_option                  = "none"
  violation_time_limit_seconds = 86400

  nrql {
    query = each.value.query
  }

  dynamic "critical" {
    for_each = each.value.critical ? [each.value] : []
    content {
      operator              = "above"
      threshold             = critical.value.threshold
      threshold_duration    = critical.value.duration
      threshold_occurrences = "ALL"
    }
  }

  dynamic "warning" {
    for_each = each.value.critical ? [] : [each.value]
    content {
      operator              = "above"
      threshold             = warning.value.threshold
      threshold_duration    = warning.value.duration
      threshold_occurrences = "ALL"
    }
  }
}

resource "newrelic_nrql_alert_condition" "loss" {
  for_each = local.loss_conditions

  account_id                   = var.newrelic_account_id
  policy_id                    = each.value.critical_policy ? var.dev_critical_policy_id : var.dev_warning_policy_id
  type                         = "static"
  name                         = each.value.title
  description                  = each.value.description
  runbook_url                  = local.runbook_url
  aggregation_method           = "event_flow"
  aggregation_window           = 60
  aggregation_delay            = 120
  expiration_duration          = each.value.expiration
  open_violation_on_expiration = true
  violation_time_limit_seconds = 86400

  nrql {
    query = each.value.query
  }
}

resource "newrelic_nrql_alert_condition" "create_snippet_errors" {
  account_id                   = var.newrelic_account_id
  policy_id                    = var.dev_warning_policy_id
  type                         = "static"
  name                         = "DEV - Errores técnicos reiterados al crear snippets"
  description                  = "Juanchi. En Aplicación y experiencia revisar 5xx en POST y usar request ID y traza para identificar la dependencia. Recuperación: una ventana con altas sin errores reiterados."
  runbook_url                  = local.runbook_url
  aggregation_method           = "event_timer"
  aggregation_window           = 300
  aggregation_timer            = 120
  violation_time_limit_seconds = 86400

  nrql {
    query = "SELECT filter(count(*), WHERE ${local.http_failure}) FROM Log WHERE environment = 'dev' AND logtype = 'nginx-ingress' AND path = '/api/snippets' AND method = 'POST'"
  }

  warning {
    operator              = "above"
    threshold             = 1
    threshold_duration    = 300
    threshold_occurrences = "AT_LEAST_ONCE"
  }
}

locals {
  api_warnings = {
    errors = {
      title       = "DEV - Proporción elevada de errores HTTP en la API"
      description = "Juanchi. En Aplicación y experiencia comparar rutas, APM y dependencias. Recuperación: una ventana representativa vuelve al umbral."
      query       = "SELECT clamp_max(floor(count(*) / 20), 1) * percentage(count(*), WHERE ${local.http_failure}) FROM Log WHERE environment = 'dev' AND ${local.api_valid}"
      threshold   = 5
    }
    latency = {
      title       = "DEV - API con solicitudes lentas"
      description = "Juanchi. En Aplicación y experiencia revisar p95 por ruta y seguir trazas hasta la dependencia lenta. Recuperación: una ventana representativa vuelve al umbral."
      query       = "SELECT clamp_max(floor(count(*) / 20), 1) * percentage(count(*), WHERE request_time > 2) FROM Log WHERE environment = 'dev' AND ${local.api_valid} AND request_time IS NOT NULL"
      threshold   = 5
    }
  }
}

resource "newrelic_nrql_alert_condition" "api_warning" {
  for_each = local.api_warnings

  account_id                   = var.newrelic_account_id
  policy_id                    = var.dev_warning_policy_id
  type                         = "static"
  name                         = each.value.title
  description                  = each.value.description
  runbook_url                  = local.runbook_url
  aggregation_method           = "event_timer"
  aggregation_window           = 300
  aggregation_timer            = 120
  violation_time_limit_seconds = 86400

  nrql {
    query = each.value.query
  }

  warning {
    operator              = "above"
    threshold             = each.value.threshold
    threshold_duration    = 300
    threshold_occurrences = "AT_LEAST_ONCE"
  }
}
