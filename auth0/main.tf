locals {
  callback_path = "/auth/callback"
}

resource "auth0_client" "ui" {
  name            = "snippet-searcher-dev-ui"
  description     = "Snippet Searcher development SPA; managed by Terraform (SNI-71)."
  app_type        = "spa"
  is_first_party  = true
  oidc_conformant = true
  grant_types     = ["authorization_code"]

  callbacks           = sort([for origin in var.ui_origins : "${origin}${local.callback_path}"])
  allowed_logout_urls = sort([for origin in var.ui_origins : "${origin}/"])
  web_origins         = sort(tolist(var.ui_origins))
  allowed_origins     = sort(tolist(var.ui_origins))

  lifecycle {
    prevent_destroy = true
  }
}

resource "auth0_client_credentials" "ui" {
  client_id             = auth0_client.ui.id
  authentication_method = "none"
}

resource "auth0_resource_server" "snippets" {
  name                 = "snippet-searcher-dev-api"
  identifier           = var.api_audience
  signing_alg          = "RS256"
  token_dialect        = "access_token"
  token_lifetime       = var.access_token_lifetime_seconds
  allow_offline_access = false
  enforce_policies     = false

  # User login is allowed. M2M callers require separate, explicit client grants.
  subject_type_authorization {
    user {
      policy = "allow_all"
    }
    client {
      policy = "require_client_grant"
    }
  }

  lifecycle {
    prevent_destroy = true
  }
}

# Add one association, rather than replacing all clients on a shared connection.
resource "auth0_connection_client" "ui" {
  connection_id = var.database_connection_id
  client_id     = auth0_client.ui.id
}

# The existing M2M application and its Management API grant must be imported,
# not recreated: its current secret is already in use by the team.
resource "auth0_client" "dev_directory" {
  name        = "snippet-searcher-dev-directory"
  app_type    = "non_interactive"
  grant_types = ["client_credentials"]

  lifecycle {
    prevent_destroy = true
  }
}

resource "auth0_client_grant" "dev_directory_management" {
  client_id = auth0_client.dev_directory.id
  audience  = "https://${var.tenant_domain}/api/v2/"
  scopes    = ["read:users"]

  lifecycle {
    prevent_destroy = true
  }
}
