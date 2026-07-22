#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# 마스터 노드에서만 1회 실행. 클러스터를 초기화하고 kubeconfig를 세팅한다.
# (01-node-common-setup.sh를 먼저 실행해서 kubeadm/kubelet/containerd가 준비된 상태여야 함)
#
# 사용법:
#   ./02-master-init.sh <마스터 private IP>
# ---------------------------------------------------------------------------
set -euo pipefail

MASTER_PRIVATE_IP="${1:?사용법: ./02-master-init.sh <마스터 private IP>}"

# --pod-network-cidr=192.168.0.0/16 은 Calico 기본 CIDR (03-install-calico.sh와 짝을 이룸)
sudo kubeadm init \
  --pod-network-cidr=192.168.0.0/16 \
  --apiserver-advertise-address="${MASTER_PRIVATE_IP}"

mkdir -p "$HOME/.kube"
sudo cp /etc/kubernetes/admin.conf "$HOME/.kube/config"
sudo chown "$(id -u):$(id -g)" "$HOME/.kube/config"

echo
echo "===================================================================="
echo "다음 순서:"
echo "  1) ./03-install-calico.sh 실행 (CNI 없이는 노드가 NotReady 상태로 남음)"
echo "  2) 워커 조인 명령어 발급:"
echo "       kubeadm token create --print-join-command"
echo "     (토큰은 24시간 뒤 만료되므로, 워커를 조인할 때 다시 실행해도 됨)"
echo "     출력된 'kubeadm join ...' 명령어를 04-worker-join.sh의 JOIN_COMMAND에"
echo "     붙여넣고 워커 3대 각각에서 실행하세요."
echo "===================================================================="
