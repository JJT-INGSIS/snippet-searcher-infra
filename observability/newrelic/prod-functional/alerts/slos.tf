locals {
  slos = {
    api = {
      name        = "Snippet Searcher PROD - Disponibilidad HTTP de la API"
      description = "99% en 7 días. Ingreso API y ejecuciones; 2xx / (2xx + 5xx), excluido el probe de lenguajes. Interpretar con volumen y Synthetics."
      from        = "Log"
      valid       = "environment = 'prod' AND ${local.api_valid}"
      good        = "environment = 'prod' AND ${local.api_valid} AND ${local.http_success}"
      target      = 99
      volume      = 100
    }
    functional = {
      name        = "Snippet Searcher PROD - Disponibilidad del listado autenticado"
      description = "96% en 7 días. SUCCESS / (SUCCESS + FAILURE) del chequeo real de Cypress. La ausencia se alerta por separado."
      from        = "SnippetFunctionalCheck"
      valid       = "${local.functional_identity} AND ${local.functional_valid}"
      good        = "${local.functional_identity} AND result = 'SUCCESS'"
      target      = 96
      volume      = 25
    }
  }
}

resource "newrelic_service_level" "prod" {
  for_each = local.slos

  guid        = var.prod_snippets_guid
  name        = each.value.name
  description = each.value.description

  events {
    account_id = var.newrelic_account_id

    valid_events {
      from  = each.value.from
      where = each.value.valid
    }

    good_events {
      from  = each.value.from
      where = each.value.good
    }
  }

  objective {
    name   = each.value.name
    target = each.value.target

    time_window {
      rolling {
        count = 7
        unit  = "DAY"
      }
    }
  }
}
