# ---------------------------------------------------------------------------
# 클러스터 하나(마스터 1대 + 워커 3대) 분량의 네트워크/인스턴스를 만드는 모듈.
# 루트 모듈에서 provider만 다르게(kr1/kr2) 이 모듈을 두 번 호출해서 멀티 클러스터를 구성한다.
# ---------------------------------------------------------------------------

variable "cluster_label" {
  description = "리소스 이름에 붙일 접두사 (예: kr1, kr2)"
  type        = string
}

variable "vpc_cidr" {
  description = "이 클러스터 VPC의 IP 대역"
  type        = string
}

variable "subnet_cidr" {
  description = "이 클러스터 Subnet의 IP 대역 (vpc_cidr에 포함되는 범위)"
  type        = string
}

variable "availability_zone" {
  description = "콘솔 Compute > Instance > 인스턴스 생성 화면에서 확인 (예: kr-pub-a)"
  type        = string
}

variable "internet_gateway_id" {
  description = <<-EOT
    콘솔 Network > Internet Gateway 메뉴에서 확인하는 기존 게이트웨이 ID.
    NHN Cloud Terraform 프로바이더에는 게이트웨이를 새로 만드는 리소스가 없어서,
    이미 있는 게이트웨이의 ID를 참조만 한다.
  EOT
  type        = string
}

variable "image_name" {
  description = "콘솔 인스턴스 생성 화면에 표시되는 정확한 이미지 이름 (예: \"Ubuntu Server 22.04.xxx LTS\")"
  type        = string
}

variable "flavor_name" {
  description = "예: \"u2.c2m4\" (2 vCPU / 4GB) - 콘솔 Compute > Instance > Flavor 목록에서 확인"
  type        = string
}

variable "key_pair_name" {
  description = "이 클러스터 인스턴스들에 등록할 키페어 이름"
  type        = string
}

variable "ssh_public_key" {
  description = "SSH 공개키 내용 (ssh-rsa AAAA... 형태)"
  type        = string
}

variable "admin_cidr" {
  description = "SSH(22)/kube API(6443) 접근을 허용할 관리자 IP 대역 (예: 1.2.3.4/32)"
  type        = string
}
