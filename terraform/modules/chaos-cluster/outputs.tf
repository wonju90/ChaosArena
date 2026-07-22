output "master_public_ip" {
  value = nhncloud_networking_floatingip_v2.master_fip.address
}

output "master_private_ip" {
  value = nhncloud_compute_instance_v2.master.network[0].fixed_ip_v4
}

output "worker_public_ips" {
  value = nhncloud_networking_floatingip_v2.worker_fip[*].address
}

output "worker_private_ips" {
  value = nhncloud_compute_instance_v2.worker[*].network[0].fixed_ip_v4
}
