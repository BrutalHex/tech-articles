# Units must look up an allocation here. Do not invent CIDRs in terragrunt.hcl.

locals {
  region = {
    azure = "westeurope"
    aws   = "eu-central-1"
  }

  supernets = {
    azure = "10.129.0.0/12"
    aws   = "10.150.0.0/12"
  }

  reserved_other = [
    "10.0.0.0/12",   # on-prem historic — replace with the real on-prem range
    "10.144.0.0/14", # gap between Azure and AWS supernets
  ]

  azure = {
    prod = {
      hub = {
        cidr       = "10.129.0.0/20"
        gateway    = "10.129.0.0/24" # prod VPN / vWAN gateway subnet
        firewall   = "10.129.1.0/24"
        management = "10.129.2.0/24"
        dns_in     = "10.129.3.0/26"
        dns_out    = "10.129.3.64/26"
        spare      = "10.129.4.0/22"
      }
      spoke_platform = "10.130.0.0/16"
    }

    nonprod = {
      hub = {
        cidr       = "10.131.0.0/20"
        gateway    = "10.131.0.0/24" # nonprod VPN gateway — separate from prod
        firewall   = "10.131.1.0/24"
        management = "10.131.2.0/24"
        dns_in     = "10.131.3.0/26"
        dns_out    = "10.131.3.64/26"
        spare      = "10.131.4.0/22"
      }
      #test = {
      #  spoke_platform = "10.132.0.0/16"
      #}
    }
  }

  aws = {
    prod = {
      hub = {
        cidr       = "10.150.0.0/20"
        tgw        = "10.150.0.0/24"
        vpn        = "10.150.1.0/24" # prod VPN attachment — separate from nonprod
        firewall   = "10.150.2.0/24"
        management = "10.150.3.0/24"
        dns_in     = "10.150.3.64/28"
        dns_out    = "10.150.3.80/28"
        spare      = "10.150.4.0/22"
      }
      spoke_platform = "10.151.0.0/16"
    }

    nonprod = {
      hub = {
        cidr       = "10.152.0.0/20"
        tgw        = "10.152.0.0/24"
        vpn        = "10.152.1.0/24" # nonprod VPN attachment — separate from prod
        firewall   = "10.152.2.0/24"
        management = "10.152.3.0/24"
        dns_in     = "10.152.3.64/28"
        dns_out    = "10.152.3.80/28"
        spare      = "10.152.4.0/22"
      }
      #test = {
      #  spoke_platform = "10.153.0.0/16"
      #}
    }
  }

  # Prefixes advertised on each VPN. Planes never share a list.
  vpn_advertised = {
    prod = {
      azure_to_aws = [
        "10.129.0.0/16", # prod hub
        "10.130.0.0/16", # prod spoke
      ]
      aws_to_azure = [
        "10.150.0.0/16", # prod hub
        "10.151.0.0/16", # prod spoke
      ]
    }
  }
}
