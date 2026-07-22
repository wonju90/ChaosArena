locals {
  worker_count = 3
}

resource "nhncloud_compute_keypair_v2" "kp" {
  name       = var.key_pair_name
  public_key = var.ssh_public_key
}

data "nhncloud_images_image_v2" "os" {
  name        = var.image_name
  most_recent = true
}

data "nhncloud_compute_flavor_v2" "flavor" {
  name = var.flavor_name
}

resource "nhncloud_compute_instance_v2" "master" {
  name              = "${var.cluster_label}-master"
  key_pair          = nhncloud_compute_keypair_v2.kp.name
  image_id          = data.nhncloud_images_image_v2.os.id
  flavor_id         = data.nhncloud_compute_flavor_v2.flavor.id
  security_groups   = [nhncloud_networking_secgroup_v2.sg.name]
  availability_zone = var.availability_zone

  network {
    uuid = nhncloud_networking_vpc_v2.vpc.id
  }

  block_device {
    uuid                  = data.nhncloud_images_image_v2.os.id
    source_type           = "image"
    destination_type      = "volume"
    boot_index            = 0
    volume_size           = 30
    delete_on_termination = true
  }

  depends_on = [nhncloud_networking_vpcsubnet_v2.subnet]
}

resource "nhncloud_compute_instance_v2" "worker" {
  count             = local.worker_count
  name              = "${var.cluster_label}-worker-${count.index + 1}"
  key_pair          = nhncloud_compute_keypair_v2.kp.name
  image_id          = data.nhncloud_images_image_v2.os.id
  flavor_id         = data.nhncloud_compute_flavor_v2.flavor.id
  security_groups   = [nhncloud_networking_secgroup_v2.sg.name]
  availability_zone = var.availability_zone

  network {
    uuid = nhncloud_networking_vpc_v2.vpc.id
  }

  block_device {
    uuid                  = data.nhncloud_images_image_v2.os.id
    source_type           = "image"
    destination_type      = "volume"
    boot_index            = 0
    volume_size           = 30
    delete_on_termination = true
  }

  depends_on = [nhncloud_networking_vpcsubnet_v2.subnet]
}

resource "nhncloud_networking_floatingip_v2" "master_fip" {
  pool = "Public Network"
}

resource "nhncloud_networking_floatingip_associate_v2" "master_fip_assoc" {
  floating_ip = nhncloud_networking_floatingip_v2.master_fip.address
  port_id     = nhncloud_compute_instance_v2.master.network[0].port
}

resource "nhncloud_networking_floatingip_v2" "worker_fip" {
  count = local.worker_count
  pool  = "Public Network"
}

resource "nhncloud_networking_floatingip_associate_v2" "worker_fip_assoc" {
  count       = local.worker_count
  floating_ip = nhncloud_networking_floatingip_v2.worker_fip[count.index].address
  port_id     = nhncloud_compute_instance_v2.worker[count.index].network[0].port
}
