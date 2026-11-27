terraform {
  required_version = ">= 1.7.0"

  # Remote state (R03-07). Partial configuration: bucket, key, region, credentials
  # and the optional endpoint come from `terraform init -backend-config=...` in
  # release.yml (see backend.hcl.example). `terraform validate` in ci.yml runs
  # with -backend=false.
  backend "s3" {}

  required_providers {
    null = {
      source  = "hashicorp/null"
      version = ">= 3.2.2"
    }
  }
}
