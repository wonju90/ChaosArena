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
