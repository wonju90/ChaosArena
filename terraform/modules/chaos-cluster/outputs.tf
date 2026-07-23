output "master_public_ip" {
  value = nhncloud_networking_floatingip_v2.master_fip.address
}

output "master_private_ip" {
  value = nhncloud_networking_port_v2.master_port.all_fixed_ips[0]
}

output "worker_public_ips" {
  value = nhncloud_networking_floatingip_v2.worker_fip[*].address
}

output "worker_private_ips" {
  value = nhncloud_networking_port_v2.worker_port[*].all_fixed_ips[0]
}
