#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# 마스터 노드에서, kubeadm init 직후에 실행. Calico CNI를 설치한다.
# (CNI가 없으면 노드가 계속 NotReady 상태로 남는다)
# ---------------------------------------------------------------------------
set -euo pipefail

# 설치 시점에 https://github.com/projectcalico/calico/releases 에서 최신 stable로 갱신할 것.
CALICO_VERSION="v3.32.1"

# CRD 번들 용량이 커서 kubectl apply는 request 크기 제한에 걸릴 수 있다 (Calico 공식 권장: create 사용).
kubectl create -f "https://raw.githubusercontent.com/projectcalico/calico/${CALICO_VERSION}/manifests/tigera-operator.yaml"

# eBPF 데이터플레인(custom-resources-bpf.yaml)은 이 프로젝트 규모엔 과함.
# 표준 iptables 기반 데이터플레인이면 충분하다.
kubectl create -f "https://raw.githubusercontent.com/projectcalico/calico/${CALICO_VERSION}/manifests/custom-resources.yaml"

echo
echo "설치가 끝날 때까지 몇 분 걸릴 수 있습니다. 아래 명령으로 진행 상황을 확인하세요:"
echo "  kubectl get tigerastatus"
echo "모든 항목이 AVAILABLE=True가 되면, 다음으로 워커 노드를 조인하세요 (04-worker-join.sh)."
