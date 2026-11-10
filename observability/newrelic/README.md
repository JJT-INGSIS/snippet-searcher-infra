# Monitores New Relic de DEV

Esta carpeta prepara la configuración de los dos monitores Ping existentes.
Se ejecutó `terraform init`, `terraform validate` y `terraform fmt -check` con
Terraform 1.13.5 y el proveedor bloqueado en 3.75.4. Los dos monitores fueron
importados al estado local y se revisó un primer plan: propone cero altas, dos
actualizaciones y cero destrucciones. La consola de New Relic ya muestra las
opciones GET y `environment:dev` en ambos monitores y el tratamiento de
redirecciones en API, tal como se desean; aun así el plan propone agregarlos.
Esto sugiere diferencias de lectura del proveedor, pero no se confirmó su causa.
**No ejecutar `apply`** hasta conciliarlas y revisar el plan nuevamente. No incluye el monitor de certificado, alertas,
destinos, workflows ni la regla Azure; están documentados por separado.

El proveedor utiliza credenciales de New Relic suministradas fuera del repositorio.
No guardar claves, archivos de variables sensibles ni el estado de Terraform en Git.
Antes de configurar estado compartido, acordar su almacenamiento y control de acceso.

Preparación pendiente con Terraform >= 1.5 y el proveedor especificado:

1. Configurar `TF_VAR_newrelic_api_key` con una **User API key**, y las variables
   `newrelic_account_id` y `dev_base_url` por mecanismos locales seguros. No
   registrar credenciales en el código ni en logs. La variable es sensible, pero
   el estado puede contener información sensible: mantenerlo fuera de Git.
2. Ejecutar `terraform init` y `terraform validate` en el entorno de trabajo.
3. Importar cada monitor existente por su **entity GUID**, usando los destinos
   `newrelic_synthetics_monitor.dev_ui` y `newrelic_synthetics_monitor.dev_api`.
   Obtener los GUID desde la pantalla de cada monitor; no usar el UUID corto.
4. Revisar `terraform plan` completo y conciliar cualquier diferencia antes de
   aplicar. No ejecutar un plan que proponga reemplazar recursos existentes.

Los detalles y limitaciones de los monitores se encuentran en
[`docs/observability/sni-84-synthetics-dev.md`](../../docs/observability/sni-84-synthetics-dev.md).
