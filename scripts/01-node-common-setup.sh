#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# 모든 노드(마스터 1대 + 워커 3대)에서 공통으로 실행하는 사전 준비 스크립트.
# kubeadm이 요구하는 최소 조건(swap 끄기, 커널 모듈, containerd, kubeadm/kubelet/kubectl)을 맞춘다.
#
# 사용법 (4대 인스턴스 전부에서 동일하게):
#   sudo ./01-node-common-setup.sh
# ---------------------------------------------------------------------------
set -euo pipefail

# kubeadm/kubelet/kubectl 버전. 설치 시점에 https://pkgs.k8s.io 에서 최신 stable로 갱신할 것.
K8S_VERSION="1.33"

echo "[1/5] swap 비활성화 (kubeadm 필수 조건)..."
swapoff -a
sed -i '/ swap /s/^/#/' /etc/fstab

echo "[2/5] 커널 모듈 및 네트워크 파라미터 설정..."
cat <<EOF > /etc/modules-load.d/k8s.conf
overlay
br_netfilter
EOF
modprobe overlay
modprobe br_netfilter

cat <<EOF > /etc/sysctl.d/k8s.conf
net.bridge.bridge-nf-call-iptables  = 1
net.bridge.bridge-nf-call-ip6tables = 1
net.ipv4.ip_forward                 = 1
EOF
sysctl --system

echo "[3/5] containerd 설치 및 systemd cgroup 드라이버로 전환..."
apt-get update
apt-get install -y containerd
mkdir -p /etc/containerd
containerd config default > /etc/containerd/config.toml
# kubeadm 클러스터는 cgroup 드라이버를 systemd로 맞춰야 kubelet과 충돌이 없다.
sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml
systemctl restart containerd
systemctl enable containerd

echo "[4/5] kubeadm/kubelet/kubectl 설치 (pkgs.k8s.io, v${K8S_VERSION})..."
apt-get install -y apt-transport-https ca-certificates curl gpg
mkdir -p /etc/apt/keyrings
curl -fsSL "https://pkgs.k8s.io/core:/stable:/v${K8S_VERSION}/deb/Release.key" \
  | gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
echo "deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v${K8S_VERSION}/deb/ /" \
  > /etc/apt/sources.list.d/kubernetes.list

apt-get update
apt-get install -y kubelet kubeadm kubectl
apt-mark hold kubelet kubeadm kubectl   # 자동 업데이트로 버전이 틀어지는 것 방지

echo "[5/5] 완료."
echo "마스터 노드라면 02-master-init.sh, 워커 노드라면 마스터 초기화가 끝날 때까지 대기하세요."
