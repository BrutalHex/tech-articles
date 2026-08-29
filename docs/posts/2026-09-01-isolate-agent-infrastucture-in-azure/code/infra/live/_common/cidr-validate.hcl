terraform {
  before_hook "validate_cidr_plan" {
    commands = ["plan", "apply", "validate"]
    execute = [
      "python3",
      "${get_parent_terragrunt_dir()}/_common/validate_cidrs.py",
    ]
  }
}
