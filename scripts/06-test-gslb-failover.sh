#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# NHN Cloud DNS Plus GSLB가 실제로 Active(클러스터 A)에서 Standby(클러스터 B)로
# failover 하는지 관찰하는 스크립트. GSLB 도메인을 주기적으로 호출해서 응답하는
# 클러스터(APP_VERSION 배지 값)가 바뀌는 순간을 로그로 남긴다.
#
# 전제: k8s/deployment.yaml의 APP_VERSION을 클러스터마다 다르게 넣어뒀어야 함
#       (예: kr1-active / kr2-standby)
#
# 사용법:
#   ./06-test-gslb-failover.sh https://chaosarena.example.com [폴링 주기(초)]
# ---------------------------------------------------------------------------
set -euo pipefail

URL="${1:?사용법: ./06-test-gslb-failover.sh <GSLB 도메인 URL> [폴링 주기(초), 기본 3]}"
INTERVAL="${2:-3}"

last_version=""
echo "GSLB 대상: ${URL}  (${INTERVAL}초 간격으로 /api/status 확인, Ctrl+C로 종료)"

while true; do
  now="$(date '+%Y-%m-%d %H:%M:%S')"
  response="$(curl -fsS --max-time 5 "${URL%/}/api/status" 2>/dev/null || true)"

  if [[ -z "$response" ]]; then
    echo "[$now] ⚠ 응답 없음 (failover 진행 중이거나 두 클러스터 모두 다운)"
    version=""
  else
    version="$(echo "$response" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("version",""))' 2>/dev/null || echo "")"
    echo "[$now] 응답 클러스터: ${version:-알수없음}"
  fi

  if [[ -n "$version" && -n "$last_version" && "$version" != "$last_version" ]]; then
    echo "===================================================================="
    echo "🔀 FAILOVER 감지: ${last_version} → ${version}"
    echo "===================================================================="
  fi
  [[ -n "$version" ]] && last_version="$version"

  sleep "$INTERVAL"
done
