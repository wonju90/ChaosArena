# 보안그룹만 새로 만든다. VPC/서브넷/라우팅테이블/게이트웨이는 기존 것을 재사용하므로
# 여기서 만들지 않는다.
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
