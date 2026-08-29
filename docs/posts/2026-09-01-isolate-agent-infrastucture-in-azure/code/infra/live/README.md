
├── root.hcl                               # common generate/remote_state helpers
├── common.hcl                             # org name, default tags, catalog version pin
├── catalogs.hcl                           # git sources + default refs
│
├── _common/                               # org-wide, not a unit
│   ├── tags.hcl
│   ├── cidr-plan.hcl                      # allocated CIDRs per env/cloud
│   └── naming.hcl
│
├── aws/
│   ├── providers.hcl                      # how AWS provider is generated
│   ├── backend.hcl                        # S3 + DynamoDB state pattern
│   │
│   ├── management/                        # AWS account
│   │   ├── account.hcl
│   │   └── _global/
│   │       ├── organizations/
│   │       ├── iam-sso/
│   │       └── cloudtrail/
│   │
│   ├── shared-services/                   # DNS, hybrid connectivity, images
│   │   ├── account.hcl
│   │   ├── _global/
│   │   │   ├── route53-public/
│   │   │   └── iam-oidc-github/
│   │   └── eu-central-1/
│   │       ├── region.hcl
│   │       ├── network-hub/
│   │       │   └── terragrunt.stack.hcl
│   │       ├── vpn-to-azure/
│   │       │   └── terragrunt.hcl
│   │       └── dns-resolver/
│   │
│   ├── prod/
│   │   ├── account.hcl
│   │   ├── _global/
│   │   └── eu-central-1/
│   │       ├── region.hcl
│   │       ├── env.hcl                    # if you keep env under region
│   │       ├── networking/
│   │       │   └── spoke/
│   │       │       └── terragrunt.stack.hcl
│   │       ├── kubernetes/
│   │       │   └── platform/
│   │       │       └── terragrunt.stack.hcl
│   │       └── data/
│   │           └── postgres/
│   │
│   └── nonprod/
│       └── …same shape, smaller sizes…
│
├── azure/
│   ├── providers.hcl
│   ├── backend.hcl                        # azurerm storage pattern
│   │
│   ├── platform/                          # connectivity + identity subscription
│   │   ├── subscription.hcl
│   │   ├── _global/
│   │   │   ├── management-groups/
│   │   │   └── entra-id/
│   │   └── westeurope/
│   │       ├── region.hcl
│   │       ├── network-hub/
│   │       ├── vpn-to-aws/
│   │       └── private-dns/
│   │
│   ├── prod/
│   │   ├── subscription.hcl
│   │   └── westeurope/
│   │       ├── networking/spoke/
│   │       ├── kubernetes/platform/
│   │       └── data/postgres/
│   │
│   └── nonprod/
│
└── hybrid/                                # orchestration only, no cloud provider of its own
    └── connectivity/
        └── aws-azure-vpn/
            └── README.md                  # documents unit paths + apply order