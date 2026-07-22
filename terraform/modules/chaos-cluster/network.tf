resource "nhncloud_networking_vpc_v2" "vpc" {
  name   = "${var.cluster_label}-chaos-vpc"
  cidrv4 = var.vpc_cidr
}

resource "nhncloud_networking_routingtable_v2" "rt" {
  name        = "${var.cluster_label}-chaos-rt"
  vpc_id      = nhncloud_networking_vpc_v2.vpc.id
  distributed = false
}

resource "nhncloud_networking_routingtable_attach_gateway_v2" "gw_attach" {
  routingtable_id = nhncloud_networking_routingtable_v2.rt.id
  gateway_id      = var.internet_gateway_id
}

resource "nhncloud_networking_vpcsubnet_v2" "subnet" {
  name            = "${var.cluster_label}-chaos-subnet"
  vpc_id          = nhncloud_networking_vpc_v2.vpc.id
  cidr            = var.subnet_cidr
  routingtable_id = nhncloud_networking_routingtable_v2.rt.id
}

resource "nhncloud_networking_secgroup_v2" "sg" {
  name = "${var.cluster_label}-chaos-sg"
}

# 클러스터 내부 통신(etcd, kubelet, API server, CNI 등)은 포트가 많고 CNI 종류에 따라
# 달라서, 같은 보안그룹 멤버끼리는 전부 허용하는 것이 kubeadm 클러스터의 일반적인 방식이다.
resource "nhncloud_networking_secgroup_rule_v2" "internal_all" {
  direction         = "ingress"
  ethertype         = "IPv4"
  security_group_id = nhncloud_networking_secgroup_v2.sg.id
  remote_group_id   = nhncloud_networking_secgroup_v2.sg.id
}

resource "nhncloud_networking_secgroup_rule_v2" "ssh" {
  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = "tcp"
  port_range_min    = 22
  port_range_max    = 22
  remote_ip_prefix  = var.admin_cidr
  security_group_id = nhncloud_networking_secgroup_v2.sg.id
}

resource "nhncloud_networking_secgroup_rule_v2" "kube_api" {
  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = "tcp"
  port_range_min    = 6443
  port_range_max    = 6443
  remote_ip_prefix  = var.admin_cidr
  security_group_id = nhncloud_networking_secgroup_v2.sg.id
}

# MetalLB(LoadBalancer, 80번 포트)와 NodePort 폴백(30000-32767)은 데모 접속용이라 공개.
resource "nhncloud_networking_secgroup_rule_v2" "http" {
  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = "tcp"
  port_range_min    = 80
  port_range_max    = 80
  remote_ip_prefix  = "0.0.0.0/0"
  security_group_id = nhncloud_networking_secgroup_v2.sg.id
}

resource "nhncloud_networking_secgroup_rule_v2" "nodeport" {
  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = "tcp"
  port_range_min    = 30000
  port_range_max    = 32767
  remote_ip_prefix  = "0.0.0.0/0"
  security_group_id = nhncloud_networking_secgroup_v2.sg.id
}
