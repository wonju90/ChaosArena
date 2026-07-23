# [일시 비활성화] KR1(판교)는 기존 프로젝트에서 메모리 쿼터 부족으로 지금은 구축하지 않는다.
# 판교 메모리 이슈가 해결되면 아래 블록의 주석을 풀어 멀티클러스터로 확장한다.
# (outputs.tf의 kr1_* 출력도 함께 주석 해제 필요)
# module "cluster_kr1" {
#   source = "./modules/chaos-cluster"
#   providers = {
#     nhncloud = nhncloud.kr1
#   }
#
#   cluster_label      = "kr1"
#   existing_vpc_id    = var.kr1_vpc_id
#   existing_subnet_id = var.kr1_subnet_id
#   availability_zone  = var.kr1_availability_zone
#   image_name         = var.kr1_image_name
#   flavor_name        = var.kr1_flavor_name
#   key_pair_name      = "chaos-arena-kr1"
#   ssh_public_key     = var.ssh_public_key
#   admin_cidr         = var.admin_cidr
# }

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
