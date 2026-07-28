# ChaosArena 처음부터 직접 구축하기 (초보자용 실행 가이드)

이 문서는 **직접 손으로 따라 하면서 인프라를 구축**하기 위한 문서다. `docs/CONCEPTS.md`가 "왜 이렇게
설계했는가"를 발표용으로 정리한 문서이고 `docs/PROJECT_LOG.md`가 "무엇을 결정했고 어떤 장애물을
어떻게 풀었는가"를 기록한 히스토리라면, 이 문서는 **"지금 내 손으로 뭘 타이핑해야 하는가"**에 집중한다.

## 이 문서를 쓰는 법

- 위에서부터 순서대로 진행한다. 각 Part는 이전 Part가 끝났다는 전제로 이어진다.
- 명령어 앞뒤의 설명을 반드시 읽고 실행할 것 — 특히 "왜?"라고 적힌 부분은 나중에 응용할 때 꼭 필요한 이유다.
- 각 단계 끝에는 "✅ 확인" 항목이 있다. 이게 통과해야 다음 단계로 넘어간다.
- `<이렇게_꺾쇠로_된_것>`은 본인 환경 값으로 바꿔야 하는 자리다.
- 이 프로젝트는 KR1(판교)/KR2(평촌) 두 클러스터를 거의 똑같이 반복해서 짓는다. Part 2~4는 그래서
  "한 클러스터 기준"으로 설명하고, 다른 클러스터에도 반복하라는 표시를 해뒀다.
- 아직 안 만든 기능(TLS, ArgoCD 등)은 문서 맨 아래 "다음에 추가될 내용"에 표시해뒀다. 실제로 진행할
  때마다 이 문서에 새 Part를 계속 추가할 것.

---

## Part 0. 시작 전 준비물

**계정/권한**
- NHN Cloud 계정 + API 사용자 인증 정보(user_id/tenant_id/password) — 콘솔의
  `Compute > Instance > Management > API 엔드포인트 설정` 화면에서 확인. user_id는 로그인 이메일이 아니라
  "API 사용자 ID" 값이다.

**로컬(내 컴퓨터)에 설치할 것**
```bash
# Terraform, kubectl, helm, cosign, python3(json 파싱용) — macOS 기준 예시
brew install terraform kubectl helm cosign
```

**SSH 키 (RSA만 지원, ed25519는 NHN Cloud가 거부한다)**
```bash
ssh-keygen -t rsa -b 4096 -f ~/.ssh/chaos-arena -C "chaos-arena"
```

---

## Part 1. Terraform으로 서버 인프라 만들기

### 1.1 왜 Terraform인가

서버를 콘솔에서 마우스로 클릭해서 만들면, 나중에 "똑같은 걸 하나 더" 만들 때 그 클릭 과정을 기억해서
반복해야 하고 실수도 나고 기록도 안 남는다. Terraform은 인프라 구성을 **코드로 적어두고 실행하면 그대로
만들어지게** 한다. 이 프로젝트는 `terraform/modules/chaos-cluster` 모듈 하나를 만들어서, provider(리전)만
바꿔 KR1/KR2에 **같은 클러스터를 두 번 찍어낸다**.

### 1.2 설정 파일 준비

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars
```

`terraform.tfvars`를 열어서 채운다:
- `nhncloud_user_id` / `nhncloud_tenant_id` / `nhncloud_password`: 위 API 인증정보
- `ssh_public_key`: `cat ~/.ssh/chaos-arena.pub` 결과
- `admin_cidr`: 본인 공인 IP + `/32` (예: `203.0.113.4/32`) — SSH/API 접속을 이 IP로만 제한하기 위함.
  **본인 IP가 바뀌면(카페 이동, 재부팅 등) 이 값도 매번 갱신해야 접속이 계속 됨**
- `kr1_vpc_id`/`kr1_subnet_id`, `kr2_vpc_id`/`kr2_subnet_id`: 콘솔 `Network > VPC/Subnet`에서 확인.
  인터넷 게이트웨이가 연결된 기존 VPC(보통 "Default Network")를 재사용한다 — 새로 만들 필요 없음
- `kr1_flavor_name`/`kr2_flavor_name`: 정식 스펙은 `r2.c4m16`(4vCPU/16GB)이지만, 리전 RAM 쿼터가
  빠듯하면 `m2.c2m4`(2vCPU/4GB) 같은 최소 스펙으로 우선 테스트해도 된다(kubeadm 최소 요구는 2vCPU 이상)

### 1.3 적용

```bash
terraform init      # 프로바이더 다운로드
terraform plan       # 뭐가 만들어질지 미리 확인 (실제로 아무것도 안 바꿈, 안전)
terraform apply      # 확인 후 yes 입력 — 실제로 서버 4대(마스터1+워커3) × 2세트 생성
```

**⚠️ 왜 `plan`을 꼭 먼저 보는가**: `apply`는 되돌리기 어려운 작업이다(서버 생성/삭제/재설치). `plan`
출력에서 "of add / to change / to destroy" 개수를 꼭 확인하고, 예상 밖의 항목이 있으면 apply하지 말고
원인을 먼저 파악할 것 — 이 프로젝트도 실제로 이유를 모르고 적용했으면 운영 서버가 통째로 재설치될 뻔한
사고가 있었다(`docs/PROJECT_LOG.md` 4.17절).

### ✅ 확인
```bash
terraform output
```
`kr1_master_public_ip`, `kr2_master_public_ip` 등이 출력되면 성공. 이 IP들을 이후 단계에서 계속 쓴다.

---

## Part 2. kubeadm으로 쿠버네티스 클러스터 구축

**이 Part는 KR1과 KR2 양쪽에 각각 반복한다.** 아래는 한 클러스터(예: KR2) 기준 설명이고, 명령어의
`kr2` 자리를 `kr1`로 바꾸면 그대로 반복 가능하다.

### 2.1 왜 관리형(NKS) 대신 kubeadm으로 직접 짓는가

관리형 클러스터는 편하지만 "구축 과정"을 배울 수 없다. kubeadm으로 서버 4대를 직접 조립하면 어렵지만
쿠버네티스가 내부적으로 어떻게 동작하는지 이해하게 된다 — 비용 절감도 덤.

### 2.2 마스터 1대 + 워커 3대, 모든 노드 공통 준비

마스터, 워커 **4대 전부**에 SSH로 접속해서 실행(`scripts/01-node-common-setup.sh`):

```bash
scp scripts/01-node-common-setup.sh ubuntu@<노드_IP>:~/
ssh ubuntu@<노드_IP> "sudo ./01-node-common-setup.sh"
```

이 스크립트가 하는 일: swap 끄기(kubeadm 필수 조건) → 커널 모듈/네트워크 설정 → containerd 설치
(cgroup 드라이버를 systemd로) → kubeadm/kubelet/kubectl 설치(`apt-mark hold`로 자동 업데이트 방지).

**왜 워커는 공인IP를 안 붙이는가**: 이 프로젝트는 비용 절감을 위해 마스터에만 플로팅(공인) IP를 붙인다.
워커는 마스터를 점프호스트로 삼아 SSH 접속한다:
```bash
ssh -J ubuntu@<마스터_공인IP> ubuntu@<워커_사설IP>
```

### 2.3 마스터 초기화

마스터에서만(`scripts/02-master-init.sh`):
```bash
ssh ubuntu@<마스터_공인IP>
./02-master-init.sh <마스터_사설IP>   # terraform output의 kr2_master_private_ip
```
Pod 네트워크 CIDR을 `172.16.0.0/16`으로 지정하는데, 노드가 속한 서브넷(`192.168.0.0/24`)과 안 겹치게
일부러 고른 값이다 — 겹치면 파드 IP와 노드 IP가 충돌한다.

### 2.4 Calico(CNI) 설치 — 마스터에서, init 직후

```bash
./03-install-calico.sh
kubectl get tigerastatus   # 모든 항목이 AVAILABLE=True 될 때까지 몇 분 대기
```

**왜 CNI가 필요한가**: 쿠버네티스는 "파드 간 네트워크"를 스스로 제공하지 않고 CNI 플러그인에게 맡긴다.
CNI가 없으면 노드가 계속 `NotReady`로 남는다.

**왜 VXLAN 모드로 바꿨는가(중요)**: 이 스크립트는 Calico 기본 encapsulation(`VXLANCrossSubnet`, "같은
서브넷끼리는 캡슐화 안 함")을 `VXLAN`(항상 캡슐화)으로 바꾼다. 이 클러스터의 노드 4대가 전부 같은
서브넷인데, NHN Cloud(OpenStack)의 포트 보안(anti-spoofing)이 파드 IP를 출발지로 하는 노드 간 패킷을
캡슐화 없이 보내면 차단해버린다 — 증상은 "calico-node는 Running인데 파드 IP로 노드 간 curl이 타임아웃".
VXLAN으로 감싸면 패킷 겉봉투의 출발지가 노드 자신의 IP가 되어 통과한다(`docs/PROJECT_LOG.md` 4.8절).

### 2.5 워커 3대 조인

마스터에서 join 명령어 발급:
```bash
kubeadm token create --print-join-command
```
출력된 `kubeadm join ...` 명령을 **워커 3대 각각**에서 실행(`scripts/04-worker-join.sh`에 붙여넣고
실행해도 되고, 그냥 SSH로 직접 실행해도 됨):
```bash
ssh ubuntu@<워커_사설IP>
sudo kubeadm join <마스터_사설IP>:6443 --token <token> --discovery-token-ca-cert-hash sha256:<hash>
```
토큰은 24시간 후 만료되므로, 시간이 지났다면 위 발급 명령을 다시 실행해서 새 토큰을 받을 것.

### ✅ 확인
```bash
kubectl get nodes
```
마스터 1대 + 워커 3대 전부 `Ready`면 성공.

### 2.6 (선택) MetalLB — 시도했지만 이 환경에선 안 됨, 참고만

```bash
./05-install-metallb.sh
```
**참고**: 이 클라우드 네트워크에서 MetalLB의 L2(ARP) 모드가 막혀 `EXTERNAL-IP`가 계속 `<pending>`이었다.
몇 분 기다려도 안 되면 `k8s/service-nodeport.yaml`(NodePort)로 폴백 — 이 프로젝트는 실제로 처음부터
NodePort를 실제 접속 경로로 쓰고 있다(Part 3.5, 8절 참고).

### 2.7 metrics-server (HPA/`kubectl top`에 필요)

```bash
./07-install-metrics-server.sh
kubectl top nodes   # 지표가 보이면 성공 (30초~1분 걸릴 수 있음)
```
kubeadm 자체 구축 클러스터는 kubelet 인증서가 metrics-server가 기본으로 신뢰하는 CA로 서명돼있지 않은
경우가 많아서, 스크립트가 `--kubelet-insecure-tls` 옵션을 자동으로 패치해준다.

---

## Part 3. 앱을 클러스터에 배포하기

### 3.1 네임스페이스 (필요시)

이 앱은 `default` 네임스페이스에 배포한다 — 별도 네임스페이스 생성 불필요.

### 3.2 RBAC — 앱이 쿠버네티스 API를 부를 수 있게

이 앱(Flask)이 "Chaos 버튼"으로 파드를 조회/삭제하려면 쿠버네티스 API 권한이 필요하다.
```bash
kubectl apply -f k8s/rbac.yaml
```
`ServiceAccount`(신분증) + `Role`(get/list/delete pods 권한) + `RoleBinding`(둘을 묶음) 3종 세트.
쿠버네티스는 기본적으로 모든 접근을 막기 때문에 "딱 필요한 권한만" 담은 신분증을 발급하는
최소 권한 원칙이다.

### 3.3 비공개 레지스트리(NCR) 준비 — 콘솔 작업

1. NHN Cloud 콘솔에서 **Container Registry(NCR)** 생성 (레지스트리 이름 예: `chaosarena-registry`)
2. 로컬에서 이미지 빌드 + 태그 + 푸시:
   ```bash
   docker build -t <registry-endpoint>/chaosarena-registry/chaos-arena:v1 .
   docker login <registry-endpoint>   # NCR 계정으로 로그인
   docker push <registry-endpoint>/chaosarena-registry/chaos-arena:v1
   ```
3. 클러스터에 pull 인증 정보를 Secret으로 등록(마스터에서):
   ```bash
   kubectl create secret docker-registry ncr-secret \
     --docker-server=<registry-endpoint> \
     --docker-username=<NCR_사용자> \
     --docker-password=<NCR_비밀번호_또는_토큰> \
     -n default
   ```

**왜 비공개로 바꿨는가**: 처음엔 Docker Hub 공개 이미지를 썼지만, 회사 앱을 아무나 보는 공개 창고에
두는 건 실무에서 부적절하다 — 비공개 레지스트리 + 인증 열쇠(`ncr-secret`) 조합으로 바꿨다.

### 3.4 이미지 서명 — cosign (공급망 보안)

"우리가 만든 진짜 이미지"인지 구분하기 위해 서명을 붙인다. 이 프로젝트는 cosign **v2.4.1**을 고정해서
쓴다(최신 버전 호환성 문제를 겪었음, `PROJECT_LOG.md` 4.13절).

```bash
cosign generate-key-pair          # cosign.key(개인키) / cosign.pub(공개키) 생성, 비밀번호 입력
cosign sign --key cosign.key --registry-referrers-mode=legacy \
  <registry-endpoint>/chaosarena-registry/chaos-arena:v1
```
- `cosign.key`는 **레포에 절대 커밋하지 않는다.** Jenkins에서 쓸 땐 k8s Secret으로 등록해서 마운트한다
  (Part 7 Jenkins 절 참고).
- 레지스트리의 "서명 안 된 이미지는 pull 금지" 정책(content-trust)을 켜두면, 서명 없는 이미지는
  애초에 배포가 안 된다 — 실수로 서명 안 한 이미지가 나가는 걸 막는 안전장치.

### 3.5 Deployment + Service 적용

```bash
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service-nodeport.yaml
```
`deployment.yaml`을 열어서 본인 환경에 맞게 확인/수정할 것:
- `image`: 위에서 push한 실제 이미지 주소
- `env.APP_VERSION`: 클러스터 구분용 배지 값(예: KR2는 `kr2`)
- `env.EXPECTED_REPLICAS`: `spec.replicas`와 반드시 같은 값

**왜 `maxSurge: 0`인가**: replica 수(3)가 워커 노드 수(3)와 같고, `podAntiAffinity`(선호 방식)로
노드당 파드 분산을 유도하기 때문에, 기본 롤링 업데이트(새 파드 먼저 띄움)는 4번째 파드가 갈 자리가
없어 교착될 수 있다. `maxSurge: 0`은 "기존 파드를 먼저 비우고 그 자리에 새 파드"를 강제한다.

**(선택) Slack 알림**: `k8s/secret-slack.example.yaml`을 `secret-slack.yaml`로 복사해서 실제 Webhook
URL을 채운 뒤 `kubectl apply -f k8s/secret-slack.yaml` — 없어도 앱은 정상 동작한다(`optional: true`).

### ✅ 확인
```bash
kubectl get pods -l app=chaos-demo -o wide   # 3개 다른 노드에 하나씩 Running
curl http://<마스터_공인IP>:30080/health      # {"status":"ok"}
```
브라우저로 `http://<마스터_공인IP>:30080` 접속해서 게임 화면이 뜨는지도 확인.

---

## Part 4. 모니터링 — Prometheus + Grafana + Slack 알림

### 4.1 kube-prometheus-stack 설치 (Helm)

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
helm install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  --namespace monitoring --create-namespace \
  --set grafana.service.type=NodePort --set grafana.service.nodePort=30030 \
  --set prometheus.service.type=NodePort --set prometheus.service.nodePorts.http=30090
```

### 4.2 앱 지표를 Prometheus가 긁어가게 연결

```bash
kubectl apply -f k8s/servicemonitor.yaml
kubectl apply -f k8s/prometheusrule.yaml
```
**⚠️ 함정**: kube-prometheus-stack은 기본적으로 `release: <helm 릴리즈 이름>` 라벨이 붙은
ServiceMonitor/PrometheusRule만 인식한다(`serviceMonitorSelectorNilUsesHelmValues=true`가 기본값).
두 파일 모두 `labels.release: kube-prometheus-stack`이 이미 들어있는데, **helm install 때 릴리즈
이름을 다르게 했다면 이 라벨 값도 그에 맞게 바꿔야 한다** — 안 그러면 타겟 0개인데 에러조차 없이
조용히 무시된다(`PROJECT_LOG.md` 4.11절, 이 프로젝트가 실제로 겪은 함정).

### 4.3 (선택) Slack 알림

```bash
kubectl create secret generic slack-webhook -n monitoring \
  --from-literal=url="https://hooks.slack.com/services/xxx/yyy/zzz"

helm upgrade kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --set grafana.service.type=NodePort --set grafana.service.nodePort=30030 \
  --set prometheus.service.type=NodePort --set prometheus.service.nodePorts.http=30090 \
  -f k8s/alertmanager-slack-values.yaml
```
**⚠️ `--reuse-values`를 쓰지 말 것**: `-f` 파일을 무시해버리는 함정이 있어서, 최초 설치 때 준 `--set`
값을 매번 전부 다시 명시하고 `-f`로 합치는 방식을 쓴다(`PROJECT_LOG.md` 4.12절).

### ✅ 확인
```bash
kubectl get pods -n monitoring
```
전부 Running이면 `http://<마스터_공인IP>:30030`(Grafana), `:30090`(Prometheus)으로 접속 확인.

---

## Part 5. 멀티클러스터 + GSLB (클러스터가 통째로 죽어도)

### 5.1 KR1도 Part 1~4를 그대로 반복

파드 하나 죽는 건 자가치유로 복구되지만 리전 전체가 죽으면 못 막는다. 그래서 KR1(판교)에도 Part 1~4를
그대로 반복해서 두 번째 클러스터를 만든다. `deployment.yaml`의 `APP_VERSION`만 클러스터마다 다르게
(`kr1-active` 등) 채운다.

### 5.2 Active/Standby로 정하고 GSLB 구성 — NHN 콘솔에서 직접

**왜 Active/Active가 아닌가**: 이 앱은 게임 기록/상태를 파드 메모리에 저장해서, 두 클러스터가 동시에
서비스하면 평소에도 상태가 안 맞는 게 드러난다. 하나만 서비스하고 나머지는 대기시키는 게 데모상 깔끔하다.

**⚠️ Terraform으로 안 됨**: GSLB의 Pool/헬스체크/FAILOVER 기능은 Terraform provider에 리소스 자체가
없다(`terraform providers schema`로 확인). NHN 콘솔의 **"GSLB" 탭**(DNS 탭과 다름, 헷갈리기 쉬움)에서
직접 구성해야 한다.

1. **Health Check**: HTTP GET `/health`:30080, KR1/KR2용 각각 생성
2. **Pool**: `kr1-active`(우선순위 1) / `kr2-standby`(우선순위 2), 각각 위 헬스체크 연결
   - 엔드포인트 주소는 **포트 없이 IP만** 입력(`133.186.144.246`처럼) — 포트는 헬스체크 쪽에서 따로 설정
3. **GSLB**: 라우팅 규칙 `FAILOVER`, TTL 30초로 생성, 위 Pool 2개를 우선순위로 연결
   → 자체 도메인이 발급된다(예: `xxxxxx.toastgslb.com`)
4. **DNS 레코드**: 가비아 등에서 관리하는 실제 도메인의 `www` 레코드를 **CNAME으로 위 GSLB 도메인에 연결**

### ✅ 확인
```bash
./scripts/06-test-gslb-failover.sh http://www.<본인도메인> 3
```
켜놓은 상태에서 Active 클러스터를 강제로 내려본다:
```bash
kubectl scale deployment/chaos-demo --replicas=0   # Active 클러스터에서
```
약 80초 내로 응답이 Standby로 바뀌는 `🔀 FAILOVER 감지` 로그가 뜨면 성공. 다시 `--replicas=3`으로
되돌리면 자동으로 failback되는 것까지 확인.

---

## Part 6. Jenkins CI/CD — push 한 번으로 빌드→서명→배포 자동화

### 6.1 사전 준비 — 시크릿/PV/RBAC

```bash
kubectl create namespace jenkins

# 기존 default 네임스페이스의 ncr-secret을 jenkins 네임스페이스에도 복사
kubectl get secret ncr-secret -n default -o yaml \
  | sed 's/namespace: default/namespace: jenkins/' \
  | kubectl apply -f -

# cosign 서명용 개인키를 시크릿으로 (Part 3.4에서 만든 cosign.key)
kubectl create secret generic cosign-key -n jenkins \
  --from-file=cosign.key=./cosign.key \
  --from-literal=password='<cosign.key 만들 때 입력한 비밀번호>'
```
```bash
kubectl apply -f k8s/jenkins-pv.yaml            # hostPath PV (아래 사전 준비 필요)
kubectl apply -f k8s/jenkins-deploy-rbac.yaml   # jenkins-deployer ServiceAccount + 권한
```
**hostPath PV 사전 준비** (StorageClass가 없는 bare-metal 클러스터라 수동 PV 필요):
```bash
ssh ubuntu@<워커1_사설IP-를-마스터경유로>
sudo mkdir -p /data/jenkins && sudo chown 1000:1000 /data/jenkins
```

### 6.2 Jenkins 설치 (Helm)

```bash
helm repo add jenkins https://charts.jenkins.io
helm repo update
helm install jenkins jenkins/jenkins -n jenkins -f k8s/jenkins-values.yaml
```
`nodeSelector`가 hostPath PV와 같은 노드(`chaosarena-worker1-kr2`)를 가리키는지 꼭 확인 — 다른 노드에
뜨면 PV를 못 찾는다.

### ✅ 확인 및 초기 설정 (콘솔 작업)
```bash
kubectl -n jenkins get secret jenkins -o jsonpath='{.data.jenkins-admin-password}' | base64 -d
```
위 비밀번호로 `http://<마스터_공인IP>:30880` 접속(계정: `admin`) → 아래는 웹 UI에서:
1. GitHub 저장소 Settings → Webhooks → `http://<마스터_공인IP>:30880/github-webhook/` 등록
2. Jenkins에서 Pipeline Job 생성, SCM을 본인 저장소/브랜치로 지정, `Jenkinsfile`(레포 루트)을 그대로 사용

### 6.3 Jenkinsfile이 하는 일 (이미 레포에 있음, 구조만 이해)

`Jenkinsfile`은 Kubernetes Cloud로 **빌드 전용 파드를 그때그때 동적으로** 띄운다:
- **Build & Push**: Kaniko 컨테이너(워커가 containerd라 docker.sock을 못 쓰기 때문 — 데몬 없이 빌드)
- **Sign**: cosign v2.4.1로 서명
- **Deploy**: kubectl 컨테이너가 파드 자신의 ServiceAccount 토큰으로 `kubectl set image` + `rollout status`

### ✅ 확인
더미 커밋을 push하고 Jenkins에서 빌드가 자동으로 트리거되어 SUCCESS로 끝나는지, 앱이 새 이미지로
바뀌었는지(`/api/status`의 `build_number`) 확인.

---

## Part 7. HPA — 부하에 따라 자동으로 파드 늘리기/줄이기

### 7.1 사전 조건 확인

```bash
kubectl top pods   # metrics-server가 동작해야 함 (Part 2.7)
kubectl get deployment chaos-demo -o jsonpath='{.spec.template.spec.containers[0].resources}'
# requests/limits가 이미 있어야 함 (deployment.yaml에 이미 포함돼 있음)
```

### 7.2 ⚠️ 막히는 지점 — 먼저 anti-affinity부터 완화

`deployment.yaml`의 `podAntiAffinity`가 `requiredDuringScheduling`(강제)면, 워커 노드 수만큼만 채워진
상태에서 HPA가 그 이상 늘리려 해도 자리가 없어 영원히 `Pending`이 된다. **적용 전에 반드시**
`preferredDuringSchedulingIgnoredDuringExecution`(weight: 100)로 바꿔야 한다(현재 `k8s/deployment.yaml`은
이미 이렇게 돼 있음).

### 7.3 HPA 적용

```bash
kubectl apply -f k8s/hpa.yaml
kubectl get hpa chaos-demo -w
```
`minReplicas`는 `EXPECTED_REPLICAS`(=3)와 반드시 같게 — 안 그러면 미션 완료 판정 로직과 어긋난다.

### ✅ 확인
앱 화면의 "🔥 CPU 부하" 버튼을 켜고 지켜보면 `REPLICAS`가 3 → 6으로 늘고(`kubectl get pods -o wide`로
노드당 2개씩 분산 확인), 버튼을 끄면 5분(기본 안정화 창) 뒤 3으로 줄어든다.

---

## Part 8. Ingress — 포트 번호 없이 접속하기

### 8.1 왜 필요한가

지금까지는 `:30080`이라는 포트 번호가 URL에 그대로 노출됐다(NodePort는 30000-32767 범위만 가능).
Ingress를 쓰면 표준 포트(80/443)로 라우팅 규칙 기반 접속이 가능해진다.

### 8.2 ingress-nginx 설치 (Helm)

```bash
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
helm repo update
helm install ingress-nginx ingress-nginx/ingress-nginx \
  -n ingress-nginx --create-namespace \
  -f k8s/ingress-nginx-values.yaml \
  --set controller.nodeSelector.'kubernetes\.io/hostname'=<마스터_노드_이름>
```
**왜 마스터 노드에 고정하는가**: 포트 없는 URL을 쓰려면 진짜 80번 포트가 필요한데, NodePort로는
30000-32767 범위만 가능해서 hostPort(노드 실제 네트워크에 직접 바인딩)를 써야 한다. 이 프로젝트는
워커에 공인IP를 안 붙였기 때문에(비용 절감), 공인IP가 있는 **마스터 노드**에만 이 파드를 스케줄링해야
한다. Jenkins를 hostPath PV 때문에 특정 워커에 고정했던 것과 같은 이유의 결정이다.

### 8.3 기존 NodePort Service를 ClusterIP로 전환 (포트 반납)

```bash
kubectl apply -f k8s/service-nodeport.yaml   # 이미 ClusterIP로 수정된 버전
```
GSLB Pool의 헬스체크가 `IP:30080` 조합을 그대로 고정해서 참조하기 때문에, **포트 번호(30080)를
ingress-nginx가 그대로 재사용**하게 만들면 GSLB/보안그룹을 하나도 안 건드리고 전환할 수 있다.

### 8.4 Ingress 리소스 적용

```bash
kubectl apply -f k8s/chaos-demo-ingress.yaml
```
`host` 필드를 일부러 지정하지 않은 catch-all 규칙이다 — GSLB 헬스체커가 Host 헤더 없이(또는 다른 값)
`/health`를 찌를 때 "모르는 host"로 취급돼 404 나는 걸 방지한다.

### ✅ 확인
```bash
curl http://<마스터_공인IP>/api/status          # 포트 없이!
curl http://<마스터_공인IP>:30080/api/status    # 기존 경로도 여전히 살아있는지(회귀 확인)
curl http://www.<본인도메인>/api/status          # 실제 도메인도 포트 없이
```
전부 200이면 성공. KR1(GSLB Active 쪽)에도 반드시 같은 작업을 반복해야 실제 도메인으로 확인 가능하다.

---

## Part 9. ArgoCD(GitOps) — Jenkins는 CI만, 배포는 Pull 방식으로

### 9.1 왜 바꾸는가 — Push(지금) vs Pull(ArgoCD)

지금까지 Jenkins는 빌드→서명→**배포**(`kubectl set image`를 직접 실행)까지 전부 했다(Push 모델).
이 말은 곧 Jenkins가 클러스터를 배포할 수 있는 진짜 권한(`jenkins-deployer`)을 들고 있었다는 뜻이다.
Jenkins는 외부 GitHub 웹훅을 받는 시스템이라 공격 표면이 넓은 편인데, 여기가 뚫리면 그 배포 권한이
그대로 악용될 수 있다.

**Pull 모델(ArgoCD)**은 Jenkins가 "이미지가 준비됐다"는 사실을 **Git 커밋으로만 남기고 끝**낸다.
클러스터 안에 떠있는 ArgoCD가 그 Git 저장소를 스스로 지켜보다가 변경을 발견하면 **자기가** 클러스터
상태를 그에 맞춘다. 핵심 이점 두 가지:
1. **배포 권한이 클러스터 밖(Jenkins)으로 안 나간다** — Jenkins는 이제 Git에 쓰기 권한만 있으면 된다.
2. **Git이 항상 진실이다(GitOps)** — 누가 `kubectl`로 몰래 바꿔놔도 ArgoCD가 Git과 다르다는 걸 감지해
   자동으로 되돌린다(self-heal).

### 9.2 매니페스트 레포 분리 준비

이 레포(`ChaosArena`)의 `k8s/`는 계속 "처음 배우는 템플릿"으로 남겨두고(Part 1~8을 나중에 또
따라 하려면 필요), **실제 GitOps가 지켜볼 레포는 새로 분리**한다. `k8s/` 안엔 순수 K8s 매니페스트와
Helm values 파일(`apiVersion`/`kind`가 없는 값 파일)이 섞여 있는데, ArgoCD는 후자를 처리 못 하므로
폴더를 나눠서 옮긴다:

```bash
mkdir -p /tmp/ChaosArena-manifests/argocd-managed /tmp/ChaosArena-manifests/helm-values
cd /Users/<본인>/workspaces/ChaosArena   # 이 레포 경로

cp k8s/deployment.yaml k8s/rbac.yaml k8s/hpa.yaml k8s/chaos-demo-ingress.yaml \
   k8s/service-nodeport.yaml k8s/servicemonitor.yaml k8s/prometheusrule.yaml \
   /tmp/ChaosArena-manifests/argocd-managed/

cp k8s/jenkins-values.yaml k8s/ingress-nginx-values.yaml \
   k8s/alertmanager-slack-values.yaml k8s/metallb-ipaddresspool.yaml \
   /tmp/ChaosArena-manifests/helm-values/
```
**왜 Helm values는 안 옮기고 따로 두는가**: Jenkins/ingress-nginx/모니터링 스택은 원래도 Helm으로
설치했지 `kubectl apply`가 아니었다. 이번 ArgoCD 도입은 "Jenkins가 매 빌드 바꾸는 것"(=앱
Deployment)에만 GitOps를 적용하는 최소 범위다 — Helm 차트까지 ArgoCD로 관리하려면 차트별로 별도
`Application`(source.helm)을 만들어야 하는데, 이건 자연스러운 다음 확장 과제로 남겨둔다.

### 9.3 새 GitHub 레포 생성 + 푸시

```bash
cd /tmp/ChaosArena-manifests
git init -b main
git add .
git commit -m "Initial GitOps manifests"

gh repo create ChaosArena-manifests --public --source=. --remote=origin --push
# gh CLI가 없거나 웹에서 만들고 싶으면: github.com에서 새 레포 생성 후
#   git remote add origin https://github.com/<본인계정>/ChaosArena-manifests.git
#   git push -u origin main
```

### 9.4 ArgoCD 설치 (KR2)

```bash
kubectl create namespace argocd
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
kubectl -n argocd rollout status deploy/argocd-server
```

노출(기존 NodePort 패턴처럼):
```bash
kubectl -n argocd patch svc argocd-server -p '{"spec": {"type": "NodePort", "ports": [{"port": 443, "targetPort": 8080, "nodePort": 30443, "name": "https"}]}}'
```

초기 admin 비밀번호 확인:
```bash
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d
```
`https://<마스터_공인IP>:30443`으로 접속(계정 `admin`) — 자체 서명 인증서라 브라우저 경고가 뜨는데, 지금
단계에선 정상이다(TLS는 아직 안 붙임).

### 9.5 Application 등록 — 이 레포에 이미 있는 파일 적용

```bash
kubectl apply -f k8s/argocd-application.yaml
```
적용 전에 `k8s/argocd-application.yaml`의 `spec.source.repoURL`을 본인이 만든
`ChaosArena-manifests` 레포 주소로 바꿔야 한다. `syncPolicy.automated`(prune+selfHeal)로 돼있어서
사람이 "Sync" 버튼을 누를 필요 없이 Git 변경이 곧바로 반영된다.

**폴링 지연 없애기(웹훅)**: ArgoCD는 기본적으로 3분마다 Git을 폴링한다. Jenkins 웹훅 때처럼 즉시
반영되게 하려면, `ChaosArena-manifests` 레포에도 Webhook을 등록한다: GitHub 저장소 Settings →
Webhooks → Payload URL `https://<마스터_공인IP>:30443/api/webhook`, Content type
`application/json`.

### 9.6 Jenkins가 매니페스트 레포에 쓸 수 있게 — GitHub PAT 등록

1. GitHub → Settings → Developer settings → Personal access tokens → Fine-grained token 생성,
   `ChaosArena-manifests` 레포에 대해 **Contents: Read and write** 권한만 부여(최소 권한)
2. Jenkins 웹 UI → Manage Jenkins → Credentials → 새 Credential 추가
   - 종류: Secret text, 값: 위에서 만든 토큰
3. 이 토큰을 클러스터 Secret으로도 등록(Jenkinsfile의 `git` 컨테이너가 읽는 값):
   ```bash
   kubectl create secret generic manifests-repo-token -n jenkins \
     --from-literal=token='<위에서 만든 PAT>'
   ```
4. `Jenkinsfile` 상단의 `MANIFESTS_REPO` 변수를 본인 레포 주소로 수정 (레포에 이미 있는 파일, 코드
   편집만 하면 됨)

### ✅ 확인

더미 커밋을 push하고:
```bash
# 1) Jenkins 빌드가 SUCCESS로 끝나는지, ChaosArena-manifests 레포에 새 커밋이 생겼는지 확인
# 2) ArgoCD Application 상태 확인
kubectl -n argocd get application chaos-demo
# STATUS: Synced, HEALTH: Healthy 면 성공

# 3) 실제 클러스터에 반영됐는지
kubectl get deployment chaos-demo -o jsonpath='{.spec.template.spec.containers[0].image}'
# 방금 ChaosArena-manifests에 커밋된 이미지 태그와 일치해야 함
```
앱의 `/cicd` 탭에서 빌드 번호/배포 랭크도 그대로 올라오는지 확인 — 이제 이 값은 "Jenkins가
빌드+서명+매니페스트 커밋까지 끝낸 시간"을 의미한다(실제 클러스터 반영은 ArgoCD가 그 뒤에 한다).

기존 접속 경로(`:30080`, 포트 없는 80, `www.<본인도메인>`)도 전부 회귀 없이 그대로 동작하는지 확인.

### 9.7 자동 롤백 (참고) — 새 설치 없이 Jenkinsfile만으로 동작

Jenkinsfile에 `Verify Deployment` 스테이지가 이미 추가돼 있다(코드 반영 완료, 새로 설치할 인프라
없음). 배포 후 앱의 `/api/status`(클러스터 내부 Service DNS로 직접 호출)에서 `build_number`가 방금
push한 빌드 번호로 바뀌는지 약 2분간 확인하고, 안 바뀌면 자동으로 이전 버전으로 되돌리는 커밋을
push한다. 자세한 설계 이유는 `docs/CONCEPTS.md` 17절 참고.

**직접 확인해보는 법** — 일부러 헬스체크가 실패하는 변경을 하나 만들어서 push해보면 된다:
```bash
# 예: app.py의 /health 핸들러를 잠깐 500을 반환하도록 바꿔서 커밋+push
git commit --allow-empty -m "test: 자동 롤백 검증용 (실제로는 /health를 깨는 변경)"
```
Jenkins 빌드는 `Update Manifests Repo`까지 SUCCESS로 진행되지만(이미지 빌드 자체는 문제없으니까),
`Verify Deployment`에서 새 `build_number`가 안 나타나 타임아웃되고, `ChaosArena-manifests`에
`ROLLBACK: ...` 커밋이 자동으로 생기는지, ArgoCD가 그걸 감지해 이전 이미지로 되돌리는지, Jenkins
빌드가 최종적으로 FAILURE(빨간 배지)로 끝나는지 확인한다. 확인 후엔 `/health`를 원래대로 되돌리는
커밋을 잊지 말고 push할 것.

### 9.8 CI/CD 탭 배포 히스토리 — 최초 1회 ConfigMap 부트스트랩

9.7절의 자동 롤백은 실제로 잘 동작하지만, 롤백이 일어나도 CI/CD 탭 화면에는 그 흔적이 안 남는다 —
그냥 빌드 번호가 하나 줄어든 정상 배포처럼 보인다. 그래서 배포 성공/롤백 이력을 최신순으로 보여주는
**타임라인**을 CI/CD 탭에 추가했다(설계 이유는 `docs/CONCEPTS.md` 18절 참고). 코드
(`k8s/rbac.yaml`, `k8s/deploy-history-configmap.yaml`, `Jenkinsfile`, `app.py`, `templates/cicd.html`)는
이미 이 레포에 반영돼 있지만, **딱 하나 최초 1회 수동 단계가 필요하다.**

**왜 수동 단계가 필요한가**: Jenkins는 이력을 기록할 때 `deploy-history-configmap.yaml` 파일의 *내용만*
`yq`로 고친다 — 파일 자체가 `ChaosArena-manifests` 레포에 없으면 `yq`가 그냥 에러를 내고 멈춘다(9.2절의
`deployment.yaml`처럼, "레포에 이미 있는 파일을 고치는" 전제로 설계했기 때문). 그래서 이 파일을
Jenkins가 처음 건드리기 전에, 사람이 딱 한 번 레포에 심어둬야 한다. 마침 이번에 `k8s/rbac.yaml`에도
"이 앱이 ConfigMap을 읽을 수 있다"는 권한 한 줄이 추가됐으니, 두 파일을 같이 반영한다.

**1) 두 파일을 매니페스트 레포로 복사 + push** — 9.2절에서 로컬에 만들어뒀던 클론 폴더(예:
`/tmp/ChaosArena-manifests`)가 있으면 그 위치로 `cd`하면 되고, 없으면(며칠 지나 `/tmp`가 정리됐거나
다른 컴퓨터라면) 아래처럼 GitHub에서 새로 clone하면 된다 — 9.3절에서 이미 push해뒀으니 레포 자체는
GitHub에 그대로 남아있다:
```bash
# 기존 클론이 남아있으면: cd /tmp/ChaosArena-manifests 로 이동해서 아래 cp부터 이어서 진행
# 없으면(디렉토리가 안 보이면) 아래처럼 새로 clone
git clone https://github.com/wonju90/ChaosArena-manifests.git /tmp/ChaosArena-manifests
cd /tmp/ChaosArena-manifests

# 이 레포(ChaosArena) 쪽의 최신 파일을 그대로 복사해온다
cp /Users/wonju/workspaces/ChaosArena/k8s/rbac.yaml argocd-managed/rbac.yaml
cp /Users/wonju/workspaces/ChaosArena/k8s/deploy-history-configmap.yaml argocd-managed/deploy-history-configmap.yaml

git add argocd-managed/rbac.yaml argocd-managed/deploy-history-configmap.yaml
git commit -m "Add deploy-history ConfigMap + RBAC read permission"
git push
```
9.5절에서 켜둔 `syncPolicy.automated`(selfHeal) 덕분에, push하고 나면 ArgoCD가 알아서(웹훅을 등록해
뒀다면 거의 즉시, 아니면 최대 3분 내) 이 두 리소스를 클러스터에 반영한다 — 여기서 따로 `kubectl apply`할
필요는 없다.

**2) ArgoCD가 실제로 반영했는지 확인**
```bash
kubectl get configmap chaos-deploy-history -n default -o yaml
# data.history.jsonl 키가 보이면 ConfigMap 자체는 반영된 것 (아직 내용은 비어있는 게 정상)

kubectl get role pod-manager -n default -o yaml
# rules 목록에 resources: [configmaps] 항목이 추가돼 있는지 확인
```

**3) 권한이 실제로 통하는지 확인** — RBAC는 반영됐다고 항상 바로 통하는 게 아니라서, 앱이 쓰는
ServiceAccount 입장에서 직접 확인하는 게 제일 확실하다:
```bash
kubectl auth can-i get configmaps/chaos-deploy-history \
  --as=system:serviceaccount:default:chaos-dashboard-sa -n default
# yes 가 나와야 정상. no가 나오면 위 1)~2)가 아직 안 끝난 것이니 잠시 뒤 재확인
```

**4) 정상 배포로 성공(✅) 이벤트 확인**
```bash
git commit --allow-empty -m "test: 배포 히스토리 타임라인 확인용"
git push
```
Jenkins 빌드가 SUCCESS로 끝나면(`Verify Deployment`까지 정상 통과), `/cicd` 탭의 "배포 히스토리"
패널에 `✅ 빌드 #N 성공` 항목이 최신순 맨 위에 새로 뜨는지 확인한다.

**5) (선택) 롤백(🔁) 이벤트까지 확인** — 9.7절의 롤백 테스트를 다시 한 번 해보면, 이번엔 화면에
`🔁 빌드 #N 롤백` + `⚠️ 헬스체크 실패 → #M로 자동 복구` 문구가 같이 남는 것까지 확인할 수 있다. 확인
후엔 9.7절과 마찬가지로 `/health`를 원래대로 되돌리는 커밋을 잊지 말고 push할 것.

---

## 다음에 추가될 내용 (아직 미착수)

- **TLS(HTTPS)**: cert-manager + Let's Encrypt. 443 포트를 보안그룹에 추가로 열어야 함(80은 이미 열려있음).
  ArgoCD 자체 UI(9.4절)도 지금은 자체 서명 인증서인데, 이때 같이 정리 가능
- **Helm 차트도 ArgoCD로 관리**: Jenkins/ingress-nginx/모니터링 스택까지 GitOps 대상으로 확장(차트별
  `Application` 추가)
- **KR1 정식 재구축**: RAM 쿼터 확보 후 `r2.c4m16` 스펙, 워커 3대로, 그리고 이 ArgoCD 구성도 반복

작업을 진행할 때마다 이 문서에 새 Part를 이어서 추가한다. 개념 설명이 더 필요하면 `docs/CONCEPTS.md`,
그 과정에서 겪은 장애물의 자세한 진단 과정은 `docs/PROJECT_LOG.md`를 참고할 것.
