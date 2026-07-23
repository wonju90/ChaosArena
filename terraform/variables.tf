# ---------------------------------------------------------------------------
# 실제 값은 terraform.tfvars(gitignore 대상)에 채워 넣는다.
# terraform.tfvars.example을 복사해서 시작할 것.
# ---------------------------------------------------------------------------

variable "nhncloud_user_id" {
  description = "Compute > Instance > Management > API 엔드포인트 설정에서 확인하는 'API 사용자 ID' (콘솔 로그인 이메일이 아님)"
  type        = string
}

variable "nhncloud_tenant_id" {
  description = "Compute > Instance > Management > API 엔드포인트 설정에서 확인하는 Tenant ID"
  type        = string
}

variable "nhncloud_password" {
  description = "API 엔드포인트 설정에서 저장한 API Password (콘솔 로그인 비밀번호와 다름)"
  type        = string
  sensitive   = true
}

variable "nhncloud_auth_url" {
  description = "NHN Cloud Identity URL (Keystone v3). 콘솔의 신원 서비스 URL이 /v2.0으로 표시되더라도, 실제 인증은 v3만 지원하므로 /v3를 사용한다."
  type        = string
  default     = "https://api-identity-infrastructure.nhncloudservice.com/v3"
}

variable "ssh_public_key" {
  description = "클러스터 인스턴스에 등록할 SSH 공개키 내용 (ssh-rsa AAAA... 형태)"
  type        = string
}

variable "admin_cidr" {
  description = "SSH(22)/kube API(6443) 접근을 허용할 관리자 IP 대역 (예: 1.2.3.4/32)"
  type        = string
}

# --- 클러스터 A (KR1, Active) ---

variable "kr1_availability_zone" {
  description = "콘솔 인스턴스 생성 화면에서 확인 (예: kr-pub-a)"
  type        = string
  default     = "kr-pub-a"
}

variable "kr1_internet_gateway_id" {
  description = "콘솔 Network > Internet Gateway에서 확인한 KR1 게이트웨이 ID"
  type        = string
}

variable "kr1_image_name" {
  description = "콘솔에 표시되는 정확한 이미지 이름"
  type        = string
}

variable "kr1_flavor_name" {
  description = "예: u2.c2m4 (2 vCPU / 4GB)"
  type        = string
}

# --- 클러스터 B (KR2, Standby) ---

variable "kr2_availability_zone" {
  description = "콘솔 인스턴스 생성 화면에서 확인"
  type        = string
  default     = "kr-pub-a"
}

variable "kr2_internet_gateway_id" {
  description = "콘솔 Network > Internet Gateway에서 확인한 KR2 게이트웨이 ID"
  type        = string
}

variable "kr2_image_name" {
  description = "콘솔에 표시되는 정확한 이미지 이름"
  type        = string
}

variable "kr2_flavor_name" {
  description = "예: u2.c2m4 (2 vCPU / 4GB)"
  type        = string
}
