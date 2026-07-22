#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# 워커 노드 3대 각각에서 실행 (01-node-common-setup.sh를 먼저 실행해둔 상태여야 함).
#
# 아래 JOIN_COMMAND 자리에, 마스터 노드에서 아래 명령으로 발급받은 결과를 그대로 붙여넣으세요:
#   kubeadm token create --print-join-command
# (02-master-init.sh 실행 직후 출력되는 join 명령어를 써도 되지만, 토큰은 24시간 후
#  만료되므로 시간이 지났다면 위 명령으로 새로 발급받아야 한다)
# ---------------------------------------------------------------------------
set -euo pipefail

JOIN_COMMAND='kubeadm join <마스터-private-ip>:6443 --token <token> --discovery-token-ca-cert-hash sha256:<hash>'

if [[ "$JOIN_COMMAND" == *"<마스터-private-ip>"* ]]; then
  echo "먼저 이 파일의 JOIN_COMMAND를 마스터에서 발급받은 실제 join 명령어로 바꿔주세요." >&2
  exit 1
fi

sudo $JOIN_COMMAND
