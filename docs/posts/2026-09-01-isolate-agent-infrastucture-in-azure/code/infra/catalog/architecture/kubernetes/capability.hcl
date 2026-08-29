locals {
  capability = "kubernetes-platform"
  required_outputs = [
    "cluster_endpoint",
    "cluster_ca",
    "oidc_issuer",
    "network_id",
    "private_subnet_ids",
    "dns_zone_id",
  ]
  allowed_sbbs = [
    "modules/azure/aks",
  ]
  allowed_stacks = [
    "stacks/azure/kubernetes-platform",
  ]
}
