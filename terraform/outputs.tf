# [일시 비활성화] KR1(판교) 클러스터 미구축. main.tf의 cluster_kr1 주석과 함께 해제할 것.
# output "kr1_master_public_ip" {
#   description = "클러스터 A(Active) 마스터 - SSH로 01/02/03번 스크립트를 실행할 대상"
#   value       = module.cluster_kr1.master_public_ip
# }
#
# output "kr1_master_private_ip" {
#   description = "02-master-init.sh 실행 시 --apiserver-advertise-address로 넘길 값"
#   value       = module.cluster_kr1.master_private_ip
# }
#
# output "kr1_worker_private_ips" {
#   description = "클러스터 A 워커 3대 사설IP - 마스터를 점프호스트로 SSH 접속 (ssh -J)"
#   value       = module.cluster_kr1.worker_private_ips
# }

output "kr2_master_public_ip" {
  description = "KR2(평촌) 마스터 공인IP - SSH 진입점"
  value       = module.cluster_kr2.master_public_ip
}

output "kr2_master_private_ip" {
  description = "02-master-init.sh 실행 시 --apiserver-advertise-address로 넘길 값"
  value       = module.cluster_kr2.master_private_ip
}

output "kr2_worker_private_ips" {
  description = "클러스터 B 워커 3대 사설IP - 마스터를 점프호스트로 SSH 접속 (ssh -J)"
  value       = module.cluster_kr2.worker_private_ips
}
