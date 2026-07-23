# ---------------------------------------------------------------------------
# 클러스터 하나(마스터 1대 + 워커 3대) 분량의 인스턴스를 만드는 모듈.
# 루트 모듈에서 provider만 다르게(kr1/kr2) 이 모듈을 두 번 호출해서 멀티 클러스터를 구성한다.
#
# 네트워크는 새로 만들지 않고, 이미 인터넷 게이트웨이가 연결된 기존 VPC/서브넷을 재사용한다.
# (NHN Cloud는 인터넷 게이트웨이를 라우팅테이블 하나에만 연결할 수 있고, Terraform
#  프로바이더에 게이트웨이 생성 리소스가 없어서 새 VPC에는 외부 통신을 붙일 수 없다.)
# ---------------------------------------------------------------------------

variable "cluster_label" {
  description = "리소스 이름에 붙일 접두사 (예: kr1, kr2)"
  type        = string
}

variable "existing_vpc_id" {
  description = "인스턴스를 배치할 기존 VPC ID (인터넷 게이트웨이가 연결된 'Default Network' VPC)"
  type        = string
}

variable "existing_subnet_id" {
  description = "위 VPC 안에서 인스턴스가 붙을 기존 서브넷 ID"
  type        = string
}

variable "availability_zone" {
  description = "콘솔 Compute > Instance > 인스턴스 생성 화면에서 확인 (예: kr-pub-a)"
  type        = string
}

variable "image_name" {
  description = "콘솔 인스턴스 생성 화면에 표시되는 정확한 이미지 이름"
  type        = string
}

variable "flavor_name" {
  description = "예: \"r2.c4m16\" (4 vCPU / 16GB) - 콘솔 Compute > Instance > Flavor 목록에서 확인"
  type        = string
}

variable "key_pair_name" {
  description = "이 클러스터 인스턴스들에 등록할 키페어 이름"
  type        = string
}

variable "ssh_public_key" {
  description = "SSH 공개키 내용 (RSA만 지원 - ssh-rsa AAAA... 형태. ed25519는 NHN Cloud가 거부함)"
  type        = string
}

variable "admin_cidr" {
  description = "SSH(22)/kube API(6443) 접근을 허용할 관리자 IP 대역 (예: 1.2.3.4/32)"
  type        = string
}
