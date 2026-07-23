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
# NHN Cloud Identity는 Keystone v3만 지원한다. v3 인증은 user_id + project(tenant_id)
# 조합으로 하며, user_id/tenant_id 모두 전역 고유값이라 별도 domain 지정이 필요 없다.
provider "nhncloud" {
  alias     = "kr1"
  user_id   = var.nhncloud_user_id
  tenant_id = var.nhncloud_tenant_id
  password  = var.nhncloud_password
  auth_url  = var.nhncloud_auth_url
  region    = "KR1"
  # user_id로 인증할 때는 domain을 함께 주면 안 된다. 프로바이더가 default_domain을
  # "default"로 자동 주입하므로 명시적으로 비워서 충돌을 막는다.
  default_domain = ""
}

# 클러스터 B(Standby) - KR2(평촌)
provider "nhncloud" {
  alias          = "kr2"
  user_id        = var.nhncloud_user_id
  tenant_id      = var.nhncloud_tenant_id
  password       = var.nhncloud_password
  auth_url       = var.nhncloud_auth_url
  region         = "KR2"
  default_domain = ""
}
