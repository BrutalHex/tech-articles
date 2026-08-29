locals {
  required_keys = [
    "org",
    "system",
    "capability",
    "environment",
    "owner",
    "cost_center",
    "data_class",
  ]

  allowed_environments = ["prod"]
  allowed_vpn_planes   = ["prod", "nonprod"]
  allowed_data_classes = ["public", "internal", "confidential", "restricted"]

  # Which VPN plane an environment is allowed to use.
  # shared units set vpn_plane explicitly (hub-prod vs hub-nonprod).
  environment_to_vpn_plane = {
    prod   = "prod"
    shared = null
  }

  defaults = {
    org          = "acme"
    system       = "platform"
    capability   = "unspecified"
    environment  = "dev"
    owner        = "platform-team"
    cost_center  = "cc-0000"
    data_class   = "internal"
    vpn_plane    = "nonprod"
    managed_by   = "terragrunt"
    repository   = "infrastructure-live"
    region_aws   = "eu-central-1"
    region_azure = "westeurope"
  }

  azure_tag_keys = {
    org         = "org"
    system      = "system"
    capability  = "capability"
    environment = "environment"
    owner       = "owner"
    cost_center = "cost_center"
    data_class  = "data_class"
    vpn_plane   = "vpn_plane"
    managed_by  = "managed_by"
  }

  aws_tag_keys = {
    org         = "Org"
    system      = "System"
    capability  = "Capability"
    environment = "Environment"
    owner       = "Owner"
    cost_center = "CostCenter"
    data_class  = "DataClass"
    vpn_plane   = "VpnPlane"
    managed_by  = "ManagedBy"
  }
}
