terraform {
  required_version = ">= 1.0.0"
  required_providers {
    nhncloud = {
      source  = "nhn-cloud/nhncloud"
      version = "~> 1.0"
    }
  }
}

# 클러스터 A(Active) - KR1(판교)
provider "nhncloud" {
  alias     = "kr1"
  user_name = var.nhncloud_user_name
  tenant_id = var.nhncloud_tenant_id
  password  = var.nhncloud_password
  auth_url  = var.nhncloud_auth_url
  region    = "KR1"
}

# 클러스터 B(Standby) - KR2(평촌)
provider "nhncloud" {
  alias     = "kr2"
  user_name = var.nhncloud_user_name
  tenant_id = var.nhncloud_tenant_id
  password  = var.nhncloud_password
  auth_url  = var.nhncloud_auth_url
  region    = "KR2"
}
