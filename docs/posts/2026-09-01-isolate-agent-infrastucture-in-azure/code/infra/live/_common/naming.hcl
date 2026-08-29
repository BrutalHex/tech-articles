locals {
  separator         = "-"
  compact_separator = ""

  default_region = {
    aws   = "eu-central-1"
    azure = "westeurope"
  }

  region_short = {
    "eu-central-1" = "euc1"
    "westeurope"   = "weu"
  }

  # Workload envs: dev, test, prod.
  # shared = hub / VPN / DNS units that belong to a VPN plane, not a product env.
  environment_short = {
    prod   = "prd"
    shared = "shrd"
  }

  # VPN plane short codes. Prod VPN is never named like the nonprod VPN.
  vpn_plane_short = {
    prod    = "vpnprd"
    nonprod = "vpnpnp"
  }
}
