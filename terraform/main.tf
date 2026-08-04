# KR1(판교): 메모리 쿼터가 빠듯해 정식 스펙(r2.c4m16) 대신 최소 스펙(m2.c2m4, 2vCPU/4GB)으로
# 우선 테스트 구축한다. 멀티클러스터+GSLB 파이프라인 검증 후 쿼터 확보되면 4c16으로 재구축 예정.
module "cluster_kr1" {
  source = "./modules/chaos-cluster"
  providers = {
    nhncloud = nhncloud.kr1
  }

  cluster_label      = "kr1"
  existing_vpc_id    = var.kr1_vpc_id
  existing_subnet_id = var.kr1_subnet_id
  availability_zone  = var.kr1_availability_zone
  image_name         = var.kr1_image_name
  flavor_name        = var.kr1_flavor_name
  key_pair_name      = "chaos-arena-kr1"
  ssh_public_key     = var.ssh_public_key
  admin_cidr         = var.admin_cidr
}

module "cluster_kr2" {
  source = "./modules/chaos-cluster"
  providers = {
    nhncloud = nhncloud.kr2
  }

  cluster_label      = "kr2"
  existing_vpc_id    = var.kr2_vpc_id
  existing_subnet_id = var.kr2_subnet_id
  availability_zone  = var.kr2_availability_zone
  image_name         = var.kr2_image_name
  flavor_name        = var.kr2_flavor_name
  key_pair_name      = "chaos-arena-kr2"
  ssh_public_key     = var.ssh_public_key
  admin_cidr         = var.admin_cidr
}
