# All resources are mocked. No provider credentials or Auth0 requests are needed.
mock_provider "auth0" {}

variables {
  tenant_domain                 = "fixture.us.auth0.com"
  api_audience                  = "https://snippets.fixture.invalid"
  database_connection_id        = "con_fixture"
  access_token_lifetime_seconds = 600
  ui_origins                    = ["http://localhost:5173", "https://dev.fixture.invalid"]
}

run "development_login_contract" {
  command = plan

  assert {
    condition = toset(auth0_client.ui.callbacks) == toset([
      "http://localhost:5173/auth/callback",
      "https://dev.fixture.invalid/auth/callback"
      ]) && toset(auth0_client.ui.allowed_logout_urls) == toset([
      "http://localhost:5173/", "https://dev.fixture.invalid/"
    ])
    error_message = "Callback and logout URLs must match the same exact reviewed origins."
  }
  assert {
    condition     = auth0_client.ui.app_type == "spa" && toset(auth0_client.ui.grant_types) == toset(["authorization_code"]) && auth0_client_credentials.ui.authentication_method == "none" && !auth0_resource_server.snippets.allow_offline_access
    error_message = "The browser must use a public authorization-code client without password/implicit/M2M/refresh grants."
  }
  assert {
    condition     = auth0_resource_server.snippets.signing_alg == "RS256" && auth0_resource_server.snippets.identifier == var.api_audience
    error_message = "The API must issue asymmetric JWTs for the intended Snippets audience."
  }
}

run "reject_wildcard_callback_origin" {
  command = plan
  variables {
    ui_origins = ["https://*.fixture.invalid"]
  }
  expect_failures = [var.ui_origins]
}

run "reject_remote_http" {
  command = plan
  variables {
    ui_origins = ["http://dev.fixture.invalid"]
  }
  expect_failures = [var.ui_origins]
}

run "reject_origin_with_path" {
  command = plan
  variables {
    ui_origins = ["https://dev.fixture.invalid/auth/callback"]
  }
  expect_failures = [var.ui_origins]
}

run "reject_issuer_as_domain_url" {
  command = plan
  variables {
    tenant_domain = "https://fixture.us.auth0.com/"
  }
  expect_failures = [var.tenant_domain]
}
