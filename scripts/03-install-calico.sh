#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# 마스터 노드에서, kubeadm init 직후에 실행. Calico CNI를 설치한다.
# (CNI가 없으면 노드가 계속 NotReady 상태로 남는다)
# ---------------------------------------------------------------------------
set -euo pipefail

# 설치 시점에 https://github.com/projectcalico/calico/releases 에서 최신 stable로 갱신할 것.
CALICO_VERSION="v3.32.1"

# Pod CIDR. 02-master-init.sh의 --pod-network-cidr과 반드시 동일해야 하며,
# 노드 서브넷(192.168.0.0/24)과 겹치지 않아야 한다.
POD_CIDR="172.16.0.0/16"

# CRD 번들 용량이 커서 kubectl apply는 request 크기 제한에 걸릴 수 있다 (Calico 공식 권장: create 사용).
kubectl create -f "https://raw.githubusercontent.com/projectcalico/calico/${CALICO_VERSION}/manifests/tigera-operator.yaml"

# tigera-operator.yaml이 CRD를 만들지만, API 서버에 등록되기까지 몇 초 걸린다.
# 주의: kubectl wait는 대상이 "아예 없으면" 기다리지 않고 즉시 NotFound로 실패한다.
# 그래서 (1) CRD가 생길 때까지 폴링으로 기다린 뒤, (2) established 조건을 기다린다.
echo "Installation CRD 생성 대기 중..."
for i in $(seq 1 30); do
  kubectl get crd installations.operator.tigera.io >/dev/null 2>&1 && break
  sleep 5
done
kubectl wait --for condition=established --timeout=120s crd/installations.operator.tigera.io

# custom-resources.yaml에서 두 가지를 치환해서 적용한다:
#   1) 기본 ipPool CIDR(192.168.0.0/16)이 노드 서브넷과 겹치므로 POD_CIDR로 교체.
#   2) 기본 encapsulation(VXLANCrossSubnet)은 "같은 서브넷 노드끼리는 캡슐화 안 함"이라,
#      NHN Cloud(OpenStack)의 포트 시큐리티(anti-spoofing)가 파드 IP를 출발지로 하는
#      노드 간 패킷을 그대로 차단한다 - 우리 노드 4대가 전부 같은 서브넷이라 실제로 발생함
#      (증상: calico-node는 Running인데 파드 IP로 노드 간 curl이 타임아웃).
#      VXLAN(항상 캡슐화)로 바꾸면 패킷의 겉봉투 출발지 IP가 노드 자신의 IP가 되어 통과한다.
# (eBPF 데이터플레인은 이 규모엔 과하므로 표준 iptables 데이터플레인 사용)
curl -fsSL "https://raw.githubusercontent.com/projectcalico/calico/${CALICO_VERSION}/manifests/custom-resources.yaml" \
  | sed "s#192.168.0.0/16#${POD_CIDR}#g" \
  | sed "s#VXLANCrossSubnet#VXLAN#g" \
  | kubectl create -f -

echo
echo "설치가 끝날 때까지 몇 분 걸릴 수 있습니다. 아래 명령으로 진행 상황을 확인하세요:"
echo "  kubectl get tigerastatus"
echo "모든 항목이 AVAILABLE=True가 되면, 다음으로 워커 노드를 조인하세요 (04-worker-join.sh)."
