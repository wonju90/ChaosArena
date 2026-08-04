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

# ---------------------------------------------------------------------------
# 인스턴스별 포트를 기존 서브넷에 직접 만들어서, 어느 서브넷에 붙을지 확정한다.
# 보안그룹도 포트에 붙인다 (포트를 미리 만들면 인스턴스의 security_groups 설정 대신
# 포트의 security_group_ids가 적용되기 때문).
# ---------------------------------------------------------------------------
resource "nhncloud_networking_port_v2" "master_port" {
  name               = "${var.cluster_label}-master-port"
  network_id         = var.existing_vpc_id
  admin_state_up     = "true"
  security_group_ids = [nhncloud_networking_secgroup_v2.sg.id]

  fixed_ip {
    subnet_id = var.existing_subnet_id
  }
}

resource "nhncloud_networking_port_v2" "worker_port" {
  count              = local.worker_count
  name               = "${var.cluster_label}-worker-${count.index + 1}-port"
  network_id         = var.existing_vpc_id
  admin_state_up     = "true"
  security_group_ids = [nhncloud_networking_secgroup_v2.sg.id]

  fixed_ip {
    subnet_id = var.existing_subnet_id
  }
}

# image_id는 일부러 안 준다: block_device로 boot-from-volume 하면 Nova API는 서버 자체의
# image 참조를 비워두는데(볼륨이 이미지에서 만들어진 것이지 서버가 아니므로), 이 프로바이더는
# 그 상태를 image_id="Attempt to boot from volume - no image supplied"로 state에 저장한다.
# 여기에 image_id를 직접 지정해두면 plan마다 그 문자열과 실제 이미지 UUID가 달라 보여서 매번
# "변경 있음"으로 뜨고, apply하면 image_id 변경 시 이 프로바이더가 실제로 servers.Rebuild()를
# 호출해 기존 서버를 새 이미지로 재설치해버린다(디스크 내용 전부 날아감) — 4.16절 드리프트 사고 원인.
resource "nhncloud_compute_instance_v2" "master" {
  name              = "ChaosArena-master-${var.cluster_label}"
  key_pair          = nhncloud_compute_keypair_v2.kp.name
  flavor_id         = data.nhncloud_compute_flavor_v2.flavor.id
  availability_zone = var.availability_zone

  network {
    port = nhncloud_networking_port_v2.master_port.id
  }

  block_device {
    uuid                  = data.nhncloud_images_image_v2.os.id
    source_type           = "image"
    destination_type      = "volume"
    boot_index            = 0
    volume_size           = 30
    delete_on_termination = true
  }
}

resource "nhncloud_compute_instance_v2" "worker" {
  count             = local.worker_count
  name              = "ChaosArena-worker${count.index + 1}-${var.cluster_label}"
  key_pair          = nhncloud_compute_keypair_v2.kp.name
  flavor_id         = data.nhncloud_compute_flavor_v2.flavor.id
  availability_zone = var.availability_zone

  network {
    port = nhncloud_networking_port_v2.worker_port[count.index].id
  }

  block_device {
    uuid                  = data.nhncloud_images_image_v2.os.id
    source_type           = "image"
    destination_type      = "volume"
    boot_index            = 0
    volume_size           = 30
    delete_on_termination = true
  }
}

resource "nhncloud_networking_floatingip_v2" "master_fip" {
  pool = "Public Network"
}

resource "nhncloud_networking_floatingip_associate_v2" "master_fip_assoc" {
  floating_ip = nhncloud_networking_floatingip_v2.master_fip.address
  port_id     = nhncloud_networking_port_v2.master_port.id
}

# 워커에는 플로팅IP를 붙이지 않는다. NHN Cloud 인터넷 게이트웨이가 서브넷 인스턴스에
# outbound 인터넷(이미지 풀/apt)을 제공하므로 플로팅IP 없이도 클러스터 구성이 가능하다.
# 워커 접속은 마스터를 점프호스트로 사용한다 (ssh -J ubuntu@<master-fip> ubuntu@<worker-사설IP>).
