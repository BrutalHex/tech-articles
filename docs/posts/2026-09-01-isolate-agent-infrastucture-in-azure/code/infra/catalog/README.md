├── architecture/                          # ABBs — contracts, not providers
│   ├── README.md                          # capability catalog + allowed SBBs
│   ├── networking/
│   │   ├── capability.hcl                 # inputs/outputs the capability must expose
│   │   └── README.md
│   ├── dns/
│   ├── connectivity/                      # VPN, peering, hubs
│   ├── identity/
│   ├── kubernetes/
│   ├── data-platform/
│   ├── observability/
│   └── security/
│
├── modules/                               # SBBs — OpenTofu/Terraform only
│   ├── aws/                               # AWS-only
│   │   ├── organization/
│   │   ├── iam/
│   │   ├── vpc/
│   │   ├── transit-gateway/
│   │   ├── vpn-site-to-site/
│   │   ├── route53-zone/
│   │   ├── route53-resolver/
│   │   ├── eks/
│   │   ├── eks-addons/
│   │   ├── rds-postgres/
│   │   ├── s3-bucket/
│   │   ├── kms/
│   │   └── guardduty/
│   ├── azure/                             # Azure-only
│   │   ├── management-groups/
│   │   ├── entra-id/
│   │   ├── resource-group/
│   │   ├── vnet/
│   │   ├── vwan-hub/
│   │   ├── vpn-gateway/
│   │   ├── private-dns-zone/
│   │   ├── dns-resolver/
│   │   ├── aks/
│   │   ├── aks-addons/
│   │   ├── postgres-flexible/
│   │   ├── storage-account/
│   │   ├── key-vault/
│   │   └── defender/
│   └── shared/                            # truly cloud-agnostic (no aws/azurerm provider)
│       ├── k8s-platform/                  # helm/kustomize: ingress, cert-manager, gitops
│       ├── policy-pack/                   # OPA/Conftest for module inputs
│       └── naming/
│
├── units/                                 # Terragrunt wrappers around one module
│   ├── aws/
│   │   ├── vpc/
│   │   │   └── terragrunt.hcl
│   │   ├── eks/
│   │   ├── route53-zone/
│   │   └── vpn-site-to-site/
│   ├── azure/
│   │   ├── vnet/
│   │   ├── aks/
│   │   ├── private-dns-zone/
│   │   └── vpn-gateway/
│   └── shared/
│       └── k8s-platform/
│
└── stacks/                                # compose units into patterns (TOGAF solutions)
    ├── aws/
    │   ├── landing-zone/                  # identity + logging + baseline
    │   ├── network-hub/
    │   ├── spoke-network/
    │   ├── kubernetes-platform/           # vpc + eks + addons + dns
    │   └── data-store-postgres/
    ├── azure/
    │   ├── landing-zone/
    │   ├── network-hub/
    │   ├── spoke-network/
    │   ├── kubernetes-platform/           # vnet + aks + addons + dns
    │   └── data-store-postgres/
    └── hybrid/
        ├── dns-split-horizon/
        └── vpn-aws-azure/                 # wires aws/vpn + azure/vpn