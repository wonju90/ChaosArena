#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# 마스터 노드에서, 워커 3대가 전부 Ready 상태가 된 뒤 실행. MetalLB를 설치한다.
# ---------------------------------------------------------------------------
set -euo pipefail

# 설치 시점에 https://github.com/metallb/metallb/releases 에서 최신 stable로 갱신할 것.
METALLB_VERSION="v0.14.9"

kubectl apply -f "https://raw.githubusercontent.com/metallb/metallb/${METALLB_VERSION}/config/manifests/metallb-native.yaml"

echo "metallb-system 파드가 준비될 때까지 대기 중..."
kubectl wait --namespace metallb-system \
  --for=condition=ready pod \
  --selector=app=metallb \
  --timeout=180s

echo
echo "===================================================================="
echo "이어서 k8s/metallb-ipaddresspool.yaml 의 IP 대역을 NHN Cloud Subnet에서"
echo "인스턴스에 할당되지 않은 자유 IP 범위로 수정한 뒤 적용하세요:"
echo "  kubectl apply -f k8s/metallb-ipaddresspool.yaml"
echo
echo "주의: L2(ARP) 모드가 NHN Cloud 가상 네트워크에서 막혀 있을 수 있습니다."
echo "몇 분 기다려도 Service의 EXTERNAL-IP가 <pending>이면, k8s/service-nodeport.yaml로"
echo "폴백하세요 (kubectl apply -f k8s/service-nodeport.yaml)."
echo "===================================================================="
