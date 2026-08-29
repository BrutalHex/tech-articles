locals {
  common       = read_terragrunt_config(find_in_parent_folders("common.hcl"))
  cloud_vars   = read_terragrunt_config(find_in_parent_folders("providers.hcl"))
  account_vars = try(read_terragrunt_config(find_in_parent_folders("account.hcl")),
                     read_terragrunt_config(find_in_parent_folders("subscription.hcl")))
  region_vars  = read_terragrunt_config(find_in_parent_folders("region.hcl"))
  env_vars     = try(read_terragrunt_config(find_in_parent_folders("env.hcl")), { locals = {} })

  cloud        = local.cloud_vars.locals.cloud          # "aws" | "azure"
  catalog_ref  = local.common.locals.catalog_ref        # "v0.3.0"
}

include "cidr_validate" {
  path = "${get_parent_terragrunt_dir()}/_common/cidr-validate.hcl"
}

# remote_state chosen by cloud — S3 vs azurerm
remote_state {
  backend = local.cloud_vars.locals.backend
  config  = merge(
    local.cloud_vars.locals.backend_config,
    { key = "${path_relative_to_include()}/tofu.tfstate" }
  )
  generate = {
    path      = "backend.tf"
    if_exists = "overwrite_terragrunt"
  }
}

generate "provider" {
  path      = "provider.tf"
  if_exists = "overwrite_terragrunt"
  contents  = local.cloud_vars.locals.provider_hcl
}
