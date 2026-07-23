output "kr1_master_public_ip" {
  description = "클러스터 A(Active) 마스터 - SSH로 01/02/03번 스크립트를 실행할 대상"
  value       = module.cluster_kr1.master_public_ip
}

output "kr1_master_private_ip" {
  description = "02-master-init.sh 실행 시 --apiserver-advertise-address로 넘길 값"
  value       = module.cluster_kr1.master_private_ip
}

output "kr1_worker_private_ips" {
  description = "클러스터 A 워커 3대 사설IP - 마스터를 점프호스트로 SSH 접속 (ssh -J)"
  value       = module.cluster_kr1.worker_private_ips
}

output "kr2_master_public_ip" {
  description = "클러스터 B(Standby) 마스터"
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
