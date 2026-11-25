output "public_integration" {
  description = "Public parameters for SNI-72/73. Not a deployed runtime configuration."
  value = {
    domain        = var.tenant_domain
    issuer        = "https://${var.tenant_domain}/"
    client_id     = auth0_client.ui.id
    audience      = auth0_resource_server.snippets.identifier
    callback_path = local.callback_path
    callbacks     = auth0_client.ui.callbacks
    logout_urls   = auth0_client.ui.allowed_logout_urls
    origins       = auth0_client.ui.web_origins
  }
}
