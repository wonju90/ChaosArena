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

# tigera-operator.yaml이 CRD를 만들지만, API 서버가 이를 등록하기까지 몇 초 걸린다.
# 바로 custom-resources를 적용하면 'no matches for kind Installation' 레이스가 발생하므로,
# Installation CRD가 established 될 때까지 기다린다.
kubectl wait --for condition=established --timeout=120s crd/installations.operator.tigera.io

# custom-resources.yaml의 기본 ipPool CIDR은 192.168.0.0/16 이라 노드 서브넷과 겹친다.
# 내려받아서 POD_CIDR로 치환한 뒤 적용한다.
# (eBPF 데이터플레인은 이 규모엔 과하므로 표준 iptables 데이터플레인 사용)
curl -fsSL "https://raw.githubusercontent.com/projectcalico/calico/${CALICO_VERSION}/manifests/custom-resources.yaml" \
  | sed "s#192.168.0.0/16#${POD_CIDR}#g" \
  | kubectl create -f -

echo
echo "설치가 끝날 때까지 몇 분 걸릴 수 있습니다. 아래 명령으로 진행 상황을 확인하세요:"
echo "  kubectl get tigerastatus"
echo "모든 항목이 AVAILABLE=True가 되면, 다음으로 워커 노드를 조인하세요 (04-worker-join.sh)."
