#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# 마스터 노드에서 실행. kubectl top nodes/pods 를 쓰기 위한 metrics-server 설치.
# (기본 kubeadm 클러스터엔 포함되지 않는 선택 컴포넌트 - Chaos 모드의 CPU 부하를
#  눈으로 확인하는 용도로 사용)
# ---------------------------------------------------------------------------
set -euo pipefail

kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml

# kubeadm 자체 구축 클러스터는 kubelet 인증서가 metrics-server 기본 설정이 신뢰하는
# CA로 서명되어 있지 않은 경우가 많아, --kubelet-insecure-tls 옵션이 필요하다.
kubectl patch deployment metrics-server -n kube-system --type='json' \
  -p='[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}]'

echo
echo "파드가 Running 되고 지표가 모이기까지 30초~1분 걸릴 수 있습니다:"
echo "  kubectl get pods -n kube-system -l k8s-app=metrics-server"
echo "  kubectl top nodes"
echo "  kubectl top pods"
