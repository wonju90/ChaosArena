# ChaosArena 프로젝트 로그

> K8s 장애 대응을 게임처럼 즐기는 대시보드 + 멀티 리전 자가치유(Self-Healing) 데모.
> 이 문서는 프로젝트의 아키텍처, 기술 의사결정, 그리고 실제로 부딪힌 문제와 해결 과정을 기록한다.

---

## 1. 프로젝트 개요

**ChaosArena**는 쿠버네티스의 자가치유(Self-Healing) 능력을 "게임"으로 체험하는 데모 프로젝트다.

- 파드를 일부러 죽이는 **Chaos 버튼**(이지/하드/보스전)을 누르면, 쿠버네티스가 자동으로 새 파드를 복구한다.
- 그 **복구 시간을 측정**해서 랭크(S/A/B/C), 콤보, 하이스코어로 기록하는 게임성을 입혔다.
- 앱 자신이 "장애가 나고 복구되는 워크로드"이자 동시에 "그 상태를 보여주는 대시보드"인 이중 구조.

**기술 스택**
| 영역 | 기술 |
|---|---|
| 앱 | Python Flask, Prometheus client, Kubernetes Python client |
| 프론트 | Vanilla JS (폴링 기반 실시간 대시보드), Tailwind CSS, Chart.js |
| 인프라 | NHN Cloud, Terraform(IaC), kubeadm 자체 구축 클러스터 |
| 네트워크/CNI | Calico, MetalLB |
| 멀티 리전 | NHN Cloud DNS Plus GSLB (Active/Standby failover) |

---

## 2. 애플리케이션 구조

### 2.1 단일 페이지 → 멀티 페이지 분리
초기에는 모든 기능이 한 페이지(`dashboard.html`)에 몰려 있었다. "플레이 vs 관전" 기준으로 3개 페이지로 분리:

- **`/` (게임)**: 클러스터 상태, 파드 격자, 미션 타이머, 난이도 선택, Chaos 컨트롤, 랭크 연출(컨페티/사운드)
- **`/monitor` (대시보드)**: 실시간 지표(요청수/에러율/응답시간), 응답시간·에러율 스파크라인, 에러율 게이지, 파드 요약
- **`/records` (기록)**: 하이스코어 포디움, 최근 기록 막대그래프, 콤보

Jinja2 템플릿 상속(`base.html`)으로 공통 레이아웃·네비게이션·디자인 시스템을 공유하고, 페이지별로 필요한 API만 폴링하도록 JS를 분리했다.

### 2.2 디자인 시스템 & 시각화 (운영 콘솔 리디자인)
초기 버전은 "허접해 보인다"는 피드백을 받아, **Grafana/Datadog 풍 운영 콘솔** 방향으로 전면 재설계했다.
- **앱 셸**: 좌측 사이드바 네비게이션(SVG 아이콘) + 상단바(페이지 제목 + 모든 페이지 공통 클러스터 헬스 칩) + 멀티컬럼 그리드. 좁은 화면에선 사이드바가 상단 탭바로 전환.
- **파드 토폴로지**: 초기엔 파드를 고정 크기 박스에 욱여넣어 긴 노드명(`chaosarena-worker1-kr2`)이 줄바꿈·잘림으로 지저분했다. → **노드별 그룹 카드**로 재구성하고 노드명은 헤더에서 말줄임(`…`)+툴팁, 파드는 상태 점+이름+실제 phase(`Running`/`Pending`/`ContainerCreating`) 칩으로 표시.
- **차트**: `stat-tile` KPI, Chart.js 라인 차트(호버 크로스헤어 + 최신값 직접 라벨), 도넛 게이지, 막대 차트(막대별 값 라벨). 재사용 SVG 아이콘은 `_icons.html` 매크로로 관리.
- 웹폰트 Pretendard 로드, 숫자 천단위 구분 등 타이포/가독성 디테일.
- 어느 페이지에 있어도 미션 진행을 알 수 있는 네비게이션 실시간 배지(`/api/mission/peek` — 완료 판정과 분리한 조회 전용 API로 랭크 연출과의 경쟁 방지)

---

## 3. 인프라 아키텍처 의사결정

### 3.1 관리형(NKS) vs 자체 구축 → **자체 구축(kubeadm)**
- 비용 절감 + "클러스터 구축 능력" 자체를 포트폴리오 어필 포인트로.
- 마스터 1 + 워커 3 구성. 워커 3대는 앱의 "노드별 파드 분산 시각화"와 `podAntiAffinity`에 정확히 대응.

### 3.2 단일 클러스터 vs 멀티 클러스터 → **멀티 클러스터 (Active/Standby)**
- KR1(판교, Active) + KR2(평촌, Standby) 두 리전에 각각 클러스터.
- "파드 레벨 자가치유"를 넘어 "**클러스터 전체가 죽어도 서비스가 유지되는**" 상위 스토리로 확장.
- **Active/Active가 아닌 Active/Standby를 선택한 이유**: 앱 상태(기록/미션)를 파드 메모리에 들고 있어, Active/Active면 평상시에도 클러스터 간 상태 불일치가 드러난다. Standby는 그 문제를 failover 순간으로 국한시켜 데모 스토리가 깔끔하다.

### 3.3 failover 방식 → **NHN Cloud DNS Plus GSLB (FAILOVER 정책)**
- 클러스터 간 failover 로직을 직접 구현하지 않고 NHN Cloud의 GSLB(우선순위 기반 FAILOVER + `/health` 헬스체크)로 처리.
- Pool A(KR1, priority 1) / Pool B(KR2, priority 2). Active가 죽으면 DNS가 자동으로 Standby로 전환.

### 3.4 IaC → **Terraform**
- `terraform/modules/chaos-cluster` 모듈을 provider(kr1/kr2)만 바꿔 두 번 호출해 멀티 리전 구성.
- 자격증명·VPC ID 등 민감/환경값은 `terraform.tfvars`(gitignore)로 분리, `.example`만 커밋.

### 3.5 Jenkins 호스팅 위치 → **KR2 클러스터 내부(Pod)**
- **후보**: ① KR2 클러스터 내부에 Deployment로 배포, ② 별도 VM(마스터 노드 또는 신규 인스턴스)에 직접 설치.
- **선택 이유**: KR1은 최소 스펙(2vCPU/4GB)이라 Jenkins+빌드 부하를 얹기 빠듯한 반면, KR2는 워커 3대(4vCPU/16GB)에
  여유가 충분함(`kubectl describe nodes` 확인 결과 CPU 요청 2~21%, 메모리 1% 수준). 별도 VM을 새로 프로비저닝하지
  않고 기존 클러스터 리소스를 재사용 — "자가치유 클러스터 위에 CI/CD도 함께 돈다"는 스토리도 일관됨.
- **known 제약사항**(구현 착수 전 확인):
  - `kubectl get storageclass` 결과 없음 — bare-metal kubeadm이라 CSI 드라이버 미설치. Jenkins 홈 디렉터리 영속화는
    **hostPath 기반 수동 PV + 컨트롤러 파드 nodeSelector 고정**으로 우회 예정.
  - 워커 노드 컨테이너 런타임이 **containerd**(Docker 데몬 없음) — `/var/run/docker.sock` 마운트 방식 불가.
    **Kaniko**(데몬 없이 이미지 빌드)로 대체 예정.
  - NodePort 30000-32767 전체가 이미 `0.0.0.0/0`으로 열려있음(`terraform/modules/chaos-cluster/network.tf`) —
    GitHub Webhook을 위한 별도 방화벽/Terraform 변경 불필요, Jenkins Service를 NodePort로 노출하면 끝.
- **트레이드오프(인지하고 보류)**: Jenkins 배포 단계(RBAC, kubectl 접근)는 1단계로 **KR2 전용**으로 스코프한다.
  KR1을 나중에 정식 스펙(`r2.c4m16`)으로 재구축해 진짜 멀티클러스터가 되면, Jenkins가 KR1에도 배포하려면
  ① KR1 API 서버(6443)로의 네트워크 경로(현재 보안그룹은 `admin_cidr`만 허용, KR2 파드망 → KR1 API 불가)와
  ② KR1용 별도 인증(kubeconfig/ServiceAccount)을 추가로 붙이는 후속 작업이 필요함. 지금 당장 막는 문제는 아니고,
  "KR1 정식 구축 후 확장 예정"으로 남겨둔 결정.

---

## 4. 트러블슈팅 로그 ⭐

> 이 프로젝트에서 가장 많은 시간을 쓴, 그리고 가장 많이 배운 부분.
> 각 항목은 **증상 → 원인 → 해결** 순으로 기록한다.

### 4.1 NHN Cloud API 인증 실패 (`Could not find user`)
- **증상**: Terraform이 `Authentication failed`. 직접 인증 API를 호출하니 `401 Could not find user`. 로그인 이메일, 콘솔의 'API 사용자 ID' 무엇을 넣어도 동일.
- **디버깅**: 일부러 틀린 비밀번호/랜덤 유저명을 넣어도 **똑같은** 메시지가 나오는 것을 발견 → 이 메시지는 진단에 무의미하며, 엔드포인트 자체가 문제임을 추론. Identity 서비스 루트(`/`)를 조회하니 **`v3.14`만 지원**하고 v2.0은 없음을 확인.
- **원인**: 이 계정의 Identity 서비스는 **Keystone v3 전용**인데, 설정 기본값이 죽은 `/v2.0` 엔드포인트였다.
- **해결**:
  - `auth_url`을 `/v3`로 변경
  - v3는 `user_name`이 아니라 **`user_id`**('API 사용자 ID')로 인증
  - user_id 인증 시 domain을 함께 주면 충돌하므로 `default_domain = ""`로 비움
  - 비밀번호·게이트웨이 ID는 처음부터 맞았음 (원인은 오직 엔드포인트 버전)

### 4.2 이미지 조회 실패 (`no results`)
- **증상**: `nhncloud_images_image_v2` 데이터소스가 이미지를 못 찾음.
- **원인**: 이미지 이름이 실제와 미세하게 다름. 추정(`Ubuntu Server 22.04 ... LTS`)과 실제(`Ubuntu Server 22.04.5 LTS (2026.03.10)`)의 표기가 상이.
- **해결**: 이미지 API를 직접 조회해 **정확한 이름**을 확인 후 반영. (추측 금지, 실제 조회 원칙)

### 4.3 SSH 키페어 등록 실패 (`failed to generate fingerprint`)
- **증상**: `nhncloud_compute_keypair_v2` 생성 시 400 에러.
- **원인**: **ed25519 키를 NHN Cloud(OpenStack Nova)가 지원하지 않음.**
- **해결**: RSA 4096 키로 재생성(`ssh-keygen -t rsa -b 4096`).

### 4.4 인터넷 게이트웨이 공유 불가 (`VpcInternetGatewayAlreadyInUse`, 409)
- **증상**: 새로 만든 VPC의 라우팅테이블에 기존 게이트웨이를 붙이려다 409.
- **원인**: NHN Cloud 인터넷 게이트웨이는 **라우팅테이블 하나에만** 연결 가능(1:1)한데, 지정한 게이트웨이는 이미 'Default Network' VPC에 사용 중. 게다가 **Terraform 프로바이더에 게이트웨이 생성 리소스가 없음.**
- **해결**: 새 VPC를 만드는 대신, **이미 게이트웨이가 붙어 인터넷이 되는 기존 'Default Network' VPC/서브넷을 재사용**하도록 모듈 재설계. 인스턴스는 지정 서브넷에 포트(`nhncloud_networking_port_v2`)를 만들어 배치하고, 보안그룹을 포트에 부여.

### 4.5 RAM 쿼터 초과 (`Quota exceeded for ram`)
- **증상**: KR1에서 인스턴스 생성 시 403. `Requested 16384, but already used 253952 of 262144`.
- **원인**: **공유 교육 계정**의 KR1 리전 RAM 쿼터(256GB) 중 248GB를 다른 사용자들이 이미 사용 중. 남은 8GB로는 16GB 노드 1대도 불가.
- **해결**: 여유 쿼터가 있는 **별도 프로젝트 라인을 할당**받아 이전. 프로젝트(테넌트)가 바뀌면서 tenant_id/VPC/서브넷 ID를 새 프로젝트 기준으로 재조회·교체(user_id·password는 계정 단위라 동일).

### 4.6 가용영역(AZ) 이름 불일치 (`availability zone is not available`)
- **증상**: KR2 인스턴스 생성 시 400.
- **원인**: AZ 이름을 KR1과 동일하게(`kr-pub-a`) 가정했으나, **KR2는 `kr2-pub-a`**.
- **해결**: AZ API를 조회해 리전별 실제 AZ명 확인 후 반영.

### 4.7 워커 플로팅IP 불필요 판단 (비용/구성 최적화)
- **의문**: 워커 노드마다 플로팅IP가 꼭 필요한가? NAT 게이트웨이를 따로 구성해야 하나?
- **검증**: NHN Cloud 공식 문서 확인 결과, **인터넷 게이트웨이가 서브넷 인스턴스에 outbound 인터넷을 자동 제공**(AWS와 다른 모델). 플로팅IP는 오직 inbound(외부 접속받기)용.
- **해결**: 워커는 플로팅IP 없이도 이미지 풀/apt 정상 동작. **마스터에만 플로팅IP**를 두어 단일 진입점으로 삼고, 워커는 마스터를 점프호스트(`ssh -J`)로 접속. NAT 게이트웨이 불필요, 플로팅IP 6개(리전당 3개) 절감.

### 4.8 파드 간 노드 통신 불가 (Calico Running인데 실제 트래픽은 타임아웃) ⭐
- **증상**: 앱 배포 후 파드 3개 모두 `Running`/`Ready`, Service·Endpoints도 정상 등록됐는데, NodePort(`:30080`)는 물론 **파드 IP로 직접 curl해도 타임아웃**. Calico 파드는 전부 `Running`이라 CNI 자체는 멀쩡해 보임.
- **디버깅 순서**: 클라우드 인프라 레벨(보안그룹 규칙, Floating IP 연결, 포트 바인딩)을 먼저 API로 전부 조회해 정상임을 확인 → 문제를 K8s/OS 레벨로 좁힘 → NodePort(서비스 계층) 우회해서 ClusterIP·파드 IP로 직접 curl → **파드 IP 직접 접속도 실패**로 확인되면서 "서비스 문제가 아니라 노드 간 파드 네트워크 자체의 문제"로 원인 범위를 좁힘.
- **원인**: Calico의 기본 encapsulation 모드는 `VXLANCrossSubnet` — **같은 서브넷에 있는 노드끼리는 캡슐화를 안 하고 파드 IP를 그대로 노출**해서 라우팅한다. 그런데 우리 노드 4대가 전부 같은 서브넷(`192.168.0.0/24`)에 있고, **NHN Cloud(OpenStack 기반)는 포트에 등록된 IP가 아닌 출발지를 가진 패킷을 자동 차단(anti-spoofing/포트 시큐리티)**한다. 그래서 파드 IP를 출발지로 하는 노드 간 트래픽이 클라우드 네트워크 레이어에서 조용히 버려졌다.
- **해결**: Calico Installation 리소스를 패치해 encapsulation을 `VXLAN`(Always)으로 변경 — 캡슐화된 패킷의 겉봉투 출발지 IP가 노드 자신의 IP가 되어 포트 시큐리티를 통과한다.
  ```bash
  kubectl patch installation default --type=merge -p \
    '{"spec":{"calicoNetwork":{"ipPools":[{"cidr":"172.16.0.0/16","encapsulation":"VXLAN","natOutgoing":"Enabled","nodeSelector":"all()"}]}}}'
  ```
  (patch 중 `natOutgoing`을 boolean `true`로 잘못 넣어 1차 시도가 검증 에러로 거부된 해프닝도 있었음 — 이 필드는 문자열 enum `"Enabled"/"Disabled"`여야 함)
- **재발 방지**: `scripts/03-install-calico.sh`에 `sed`로 `VXLANCrossSubnet → VXLAN` 치환을 추가해, 이후 클러스터(KR1 확장 등)는 처음부터 이 문제를 겪지 않도록 반영.
- **알아둘 점**: 이 이슈는 "Calico가 왜 이렇게 설계됐는가"보다 "**이 클라우드의 네트워크 보안 모델과 CNI의 기본 가정이 충돌**"하는 문제였다. 온프레미스/베어메탈이면 문제없었을 설정이 OpenStack 기반 클라우드에서만 드러난다.

### 4.9 롤링 업데이트 교착 (replica 수 = 노드 수 + 필수 anti-affinity) ⭐
- **증상**: 새 이미지로 `kubectl apply` 후 `rollout status`가 `Waiting ... 0 out of 3 new replicas ...`에서 멈춤. 새 파드가 `Pending`으로 스케줄되지 못함.
- **원인**: replica 3개 = 워커 노드 3대이고, `podAntiAffinity`(노드당 1개, `requiredDuringScheduling`)가 걸려 있다. 기본 롤링업데이트 전략은 `maxSurge`로 **새 파드를 먼저 띄운 뒤** 옛 파드를 내리는데, 4번째 파드가 올라갈 빈 노드가 없어 스케줄 불가 → 교착. (`FailedScheduling: didn't match pod anti-affinity rules`)
- **해결**: 전략을 `maxSurge: 0` / `maxUnavailable: 1`로 변경 — "옛 파드를 **먼저 1개 비우고** 그 노드에 새 파드를 배치"하도록 순서를 뒤집었다. 교체 중 순간적으로 2/3로 줄지만 무중단 롤아웃이 진행된다.
- **알아둘 점**: "replica 수를 노드 수에 딱 맞추고 노드당 1개 강제"라는 구성(노드 분산 시각화를 위해 의도한 것)은 기본 롤링업데이트와 상성이 나쁘다. 데모의 요구(정확한 노드 분산)와 배포 전략이 충돌한 사례.

### 4.10 NCR 이미지 Pull 실패 (`412 Precondition Failed`) ⭐
- **배경**: 임시로 쓰던 Docker Hub public 이미지를 **NHN NCR(비공개 레지스트리)**로 전환. 레지스트리 생성 → 이미지 태깅/푸시 → `ncr-secret`(docker-registry) 생성 → `deployment.yaml`에 NCR 주소 + `imagePullSecrets` 반영까지 완료.
- **증상**: 롤아웃 중 새 파드가 `ErrImagePull`/`ImagePullBackOff`. 이벤트 로그: `failed to resolve image: unexpected status from HEAD request to .../manifests/v3: 412 Precondition Failed`.
- **원인 격리**: 에러가 401/403(인증)이나 타임아웃(네트워크)이 **아니라** 412라는 점이 핵심. 즉 **KR2 워커 → KR1 리전 NCR 네트워크도, ncr-secret 인증도 정상**이고, 레지스트리가 응답을 준 뒤 **정책 단계에서 거부**한 것. NHN NCR은 Harbor 기반이며, Harbor는 content-trust 정책 위반 시 412를 반환한다.
- **원인**: 레지스트리 생성 시 켜둔 **"미인증 이미지 Pull 방지"** 옵션은 "로그인 인증 요구"가 아니라 **"서명(signature)되지 않은 이미지의 Pull 차단"**(content-trust)이었다. `docker push`만 한 이미지는 서명이 없어 정책에 걸렸다.
- **해결**: 데모 단계에선 레지스트리 설정에서 "미인증 이미지 Pull 방지"를 **미설정**으로 변경(이미 push된 이미지 재사용, 재push 불필요) → 멈춘 파드 삭제로 즉시 재시도 → 정상 Pull/롤아웃 완료.
- **트레이드오프**: 프로덕션이라면 정책을 켠 채 **이미지 서명(cosign 등)**을 도입하는 게 공급망 보안상 맞다. 포트폴리오에선 "정책 완화 vs 서명 도입"을 인지하고 선택한 것 자체가 의사결정 근거가 된다.
- **알아둘 점**: 클라우드 콘솔 옵션의 한글 라벨("미인증 이미지 Pull 방지")을 액면대로 "인증 필요"로 오해하기 쉬웠다. **HTTP 상태코드(412 vs 401/403)로 "인증 문제가 아니라 정책 문제"임을 갈라낸 것**이 원인 격리의 결정적 단서였다.

### 4.11 kube-prometheus-stack이 ServiceMonitor를 인식 못 함 (0개 타겟, 에러조차 없음) ⭐
- **증상**: `ServiceMonitor`(`chaos-demo`)를 만들고 라벨/포트 이름도 Service와 맞췄는데, Prometheus 타겟 페이지에 아예 나타나지 않음. 에러 로그도 없어서 뭐가 잘못됐는지 단서가 없었음.
- **원인**: kube-prometheus-stack Helm 차트는 기본값이 `serviceMonitorSelector: {}`(전체 선택처럼 보임)이지만, `serviceMonitorSelectorNilUsesHelmValues: true`가 **기본으로 켜져 있어** 이 `{}` 설정을 무시하고 실제로는 **`release: <helm 릴리즈 이름>` 라벨이 붙은 ServiceMonitor만** 선택하도록 강제한다. 우리 ServiceMonitor엔 이 라벨이 없어서 Prometheus 입장에선 "그런 리소스가 없는 것"과 동일하게 취급됐다(선택 안 됨 = 0개 타겟, 에러가 아니라 조용한 누락).
- **해결**: `metadata.labels`에 `release: kube-prometheus-stack`(helm install 시 지정한 릴리즈 이름과 동일)을 추가 → 즉시 타겟으로 인식되어 3개 파드 전부 scrape 성공.
- **알아둘 점**: 클라우드 콘솔 옵션의 "미인증 이미지 Pull 방지"(4.10)처럼, **오픈소스 Helm 차트의 "편의를 위한 기본값"도 문서를 안 읽으면 오해하기 쉽다.** `{}`라는 값만 보면 "전체 선택"이라 짐작하기 쉽지만, 그 값의 실제 처리 로직(nilUsesHelmValues 플래그)까지 봐야 진짜 동작을 알 수 있었다.

### 4.12 Alertmanager Slack 연동 3단 실패 — 레이어를 하나씩 벗겨가며 원인을 좁힌 사례 ⭐
- **배경**: Prometheus 알림 규칙(`ChaosDemoPodDown`/`HighErrorRate`/`HighCPU`)은 정상적으로 `Firing`까지 도달했는데, Slack엔 메시지가 안 왔다. 겉보기엔 "Alertmanager가 발송을 실패한다"는 단일 증상이었지만, 실제로는 **서로 다른 layer의 문제 3개가 순서대로 숨어 있었다.**
- **1단계 — `helm upgrade --reuse-values`가 `-f` 파일을 무시함**: `helm upgrade ... --reuse-values -f alertmanager-slack-values.yaml`을 실행하면 "upgraded" 성공 메시지가 뜨고 REVISION도 올라가지만, Alertmanager 파드는 재생성되지 않았다(AGE 그대로). `--reuse-values`는 이전 릴리즈의 값을 우선 적용하는 옵션이라, 새로 준 `-f` 파일의 내용이 실제로는 반영되지 않았다. **해결**: `--reuse-values`를 빼고, 최초 설치 때 줬던 `--set` 값(NodePort 등)을 전부 다시 명시하며 `-f`와 함께 적용.
- **2단계 — Secret이 다른 네임스페이스에 있었음**: 위 방법으로 재적용해도 여전히 `/etc/alertmanager/secrets/slack-webhook/`가 안 생겼다. `alertmanagerSpec.secrets`는 **Alertmanager 자신과 같은 네임스페이스(`monitoring`)**에서만 Secret을 찾는데, 앱이 쓰던 `slack-webhook` Secret은 `default` 네임스페이스에 있었다. **해결**: 같은 Secret을 `monitoring` 네임스페이스에도 복사 생성.
- **3단계 — receivers 리스트를 통째로 덮어써서 `null` receiver가 사라짐**: 위 두 개를 다 고쳐도 StatefulSet에 볼륨 자체가 안 생겼다. Prometheus Operator 로그(`kubectl logs ... prometheus-operator`)를 보고서야 정확한 원인이 드러났다: `undefined receiver "null" used in route`. kube-prometheus-stack 기본값은 내부 `Watchdog` 하트비트 알림을 무음 처리하는 `route.routes: [{receiver: "null", matchers: [alertname="Watchdog"]}]`를 갖고 있는데, Helm은 리스트(list)를 병합하지 않고 통째로 교체하기 때문에 우리가 `receivers:`를 우리 것(`slack-notifications`)만으로 덮어쓰자 `null` receiver 정의 자체가 사라졌다. `route.routes`는 우리가 안 건드려서 그대로 남아있었기 때문에 "null이라는 receiver를 쓰는데 그런 receiver가 없다"는 검증 실패로 **Operator의 reconcile 자체가 통째로 실패**했고(설정 검증 실패 → StatefulSet 업데이트도, Secret 마운트도 전혀 진행 안 됨), 그래서 1·2단계를 다 고쳐도 증상이 똑같았던 것이다. **해결**: `receivers`에 `slack-notifications`와 함께 `null` 항목도 유지.
- **디버깅 방법**: 매 단계 "될 것 같은 명령"을 실행하고 결과가 그대로면 곧바로 다음 가설로 넘어가지 않고, **helm이 실제로 받은 값(`helm get values`) → Operator가 실제로 만든 Secret 내용 → Operator 자신의 로그** 순으로 점점 더 깊은 레이어를 직접 까봤다. 특히 3단계는 로그의 정확한 에러 문구 없이는 추측으로 못 찾았을 문제였다.
- **알아둘 점**: 클라우드 콘솔 확인 창(4.10)과 마찬가지로, **Helm 차트의 "합리적으로 보이는 기본값"을 손댈 때는 그 기본값이 다른 곳에서도 참조되고 있는지 반드시 확인해야 한다.** `receivers:`를 교체하면서 그 안의 `null` 항목이 `route.routes`에서 참조되고 있다는 걸 몰랐던 것처럼.

### 4.13 NCR 이미지 서명(cosign) 도입 — 3중 장애물을 순서대로 해결 ⭐
- **배경**: 4.10에서 임시로 꺼둔 "미인증 이미지 Pull 방지" 정책을 이번엔 실제로 이미지에 서명해서 다시 켜기로 했다(cosign, 키 기반 서명).
- **장애물 1 — 최신 cosign(v3.1.2)이 이 NCR/Harbor의 OCI 1.1 Referrers API와 호환 안 됨**: `cosign sign`이 서명 업로드 전 `GET /v2/.../referrers/<digest>`를 조회하는데, 이 레지스트리는 그 경로 자체를 `401 UNAUTHORIZED: un-recognized request`로 응답했다. 정상적인 레지스트리라면 `404`를 반환해 cosign이 자동으로 legacy(태그 기반) 방식으로 폴백해야 하는데, 401이라 폴백 로직이 발동하지 않았다. `--registry-referrers-mode=legacy` 플래그(공식 문서에 나온 해결책)를 앞뒤 위치 다 바꿔가며 시도해도 동일 에러. **해결**: GitHub 릴리즈에서 구버전(`cosign v2.4.1`, legacy 태그 기반 서명이 기본이던 시절) 바이너리를 직접 받아 그걸로 서명 — 문제없이 통과.
- **장애물 2 — `docker build`가 기본으로 붙이는 provenance/SBOM attestation이 이미지를 멀티 매니페스트 인덱스로 만듦**: 첫 서명 시도에서 "recursively signing" 로그와 함께 실패했는데, 원인은 최근 Docker의 기본 빌드가 이미지 매니페스트 외에 attestation 서브 매니페스트를 함께 묶어 "매니페스트 리스트"로 push하기 때문이었다(이것도 내부적으로 referrers 조회를 유발). **해결**: `docker build --provenance=false --sbom=false`로 재빌드해 순수 단일 매니페스트로 만든 뒤 서명.
- **장애물 3 — `imagePullPolicy` 기본값(IfNotPresent) 때문에 테스트 결과를 착각할 뻔함**: 정책을 다시 켜고 파드를 재생성했는데 이벤트가 `Pulled ... already present on machine`으로 나와서 "통과했나?" 헷갈렸다. 실제로는 태그(`v4`)를 그대로 두고 이미지 내용만 다시 push했기 때문에, 워커 노드가 이전에 캐싱해둔(서명 붙이기 전) 이미지를 레지스트리 확인도 없이 그대로 재사용한 것 — 즉 정책 검증 자체가 발동을 안 한 상태였다. **해결**: `imagePullPolicy: Always`로 명시해 태그가 같아도 항상 레지스트리에서 실제로 확인하도록 강제 → 그제서야 진짜 `Pulling image` → `Successfully pulled image` 이벤트로 서명 검증 통과를 확인할 수 있었다.
- **최종 검증**: 정책 재활성화 + `imagePullPolicy: Always` 상태에서 파드 3개 전부 `Successfully pulled image` 이벤트로 정상 기동 확인.
- **알아둘 점**: 키 기반(`cosign sign --key`) 서명도 기본적으로 Sigstore의 공개 투명성 로그(Rekor)에 서명 메타데이터(다이제스트·공개키·서명값)를 영구 기록한다 — 이미지 내용 자체는 노출되지 않지만, 되돌릴 수 없는 공개 기록이라는 점은 인지하고 사용해야 한다.

### 4.14 Jenkins CI/CD 첫 end-to-end 실행 — 컨테이너 이미지 4중 장애물 ⭐
- **배경**: Jenkinsfile(Kaniko 빌드 → cosign 서명 → kubectl 배포)을 처음 push해서 실제로 돌려보는 과정에서, 파이프라인의 각 스테이지마다 서로 다른 이유로 4번 연속 실패했다. 매번 "그럴듯해 보이는 설정"이 실제 환경에서는 안 맞았던 사례들이라, 로그를 하나씩 읽어가며 원인을 좁혔다.
- **장애물 1 — `bitnami/kubectl:1.33` 태그가 존재하지 않음(`ErrImagePull`)**: Bitnami가 2025년 이미지 카탈로그를 개편하면서, 짧은 버전 태그(`1.33`) 같은 예전 무료 이미지 태그들을 `bitnamilegacy` 네임스페이스의 전체 버전 태그(예: `1.33.4-debian-12-r0`)로 옮겼다. Docker Hub API로 실제 존재하는 태그를 직접 조회해 확인 후 교체. **알아둘 점**: 유명 베이스 이미지라도 "짧은 태그가 항상 존재한다"고 가정하면 안 되고, 특히 Bitnami처럼 최근 카탈로그 정책이 바뀐 벤더는 실제 레지스트리 API로 태그 존재 여부를 확인해야 한다.
- **장애물 2 — non-root 컨테이너에서 Jenkins 셸 실행 자체가 실패**(`process apparently never started`): cosign 스테이지(`curlimages/curl`)와 kubectl 스테이지(`bitnamilegacy/kubectl`) 둘 다 같은 에러로 실패했다. 두 이미지 모두 컨테이너를 **non-root 사용자로 기본 실행**하는데, Jenkins Kubernetes 플러그인은 실행할 스크립트를 워크스페이스(공유 볼륨)에 쓰고 그 컨테이너 안에서 실행시키는 방식이라, 그 사용자가 워크스페이스에 쓸 권한이 없으면 스크립트 자체가 시작을 못 한다. **해결**: cosign 스테이지는 기본이 root인 `alpine` 이미지로 교체, kubectl 스테이지는 검증된 이미지를 유지한 채 `securityContext.runAsUser: 0`으로 root 강제.
- **장애물 3 — cosign 서명 시 `decrypt: encrypted: decryption failed`**: 이미지 빌드/push는 성공했는데 서명 단계에서 매번 실패했다. 처음엔 "Jenkins 시크릿이 잘못 전달되나?"로 의심했지만, 로컬에서 `cosign public-key --key cosign.key`로 같은 비밀번호를 직접 넣어보니 **로컬에서도 복호화가 실패**해 원인이 Jenkins/K8s가 아니라 **`cosign-key` 시크릿을 만들 때 비밀번호 자체를 잘못 입력**했던 것으로 좁혀졌다. 정확한 비밀번호를 다시 확인(`cosign public-key`의 출력이 `cosign.pub`과 바이트 단위로 일치하는지 대조)한 뒤 시크릿을 재생성해 해결. **알아둘 점**: 서명 비밀번호처럼 "맞는지 틀린지 결과로만 알 수 있는" 값은, 실패 시 그 값을 전달하는 파이프라인(Jenkins→K8s Secret)부터 의심하기 쉽지만, **가장 바깥쪽 레이어(로컬에서 같은 값으로 재현)부터 검증**하는 게 더 빠르게 원인을 좁힌다.
- **장애물 4(경미) — RBAC에 `watch` 누락으로 배포 단계 로그 스팸**: 파이프라인 자체는 성공했지만, `kubectl rollout status`가 내부적으로 Deployment를 `watch`하려다 권한이 없어 매 폴링마다 `Failed to watch ... forbidden` 에러를 로그에 남겼다(동작 자체는 폴링으로 대체되어 실패하지 않음). `jenkins-deploy-rbac.yaml`의 Role에 `watch` verb를 추가해 깨끗하게 해결.
- **최종 검증**: push → GitHub Webhook → Kaniko 빌드+push(`chaos-arena:jenkins-N`) → cosign 서명(Rekor 기록) → `kubectl set image`+`rollout status` → KR2 파드 3개 전부 새 이미지로 교체 확인. `curl`로 앱 응답(200) 확인까지 사람 개입 없이 자동 완료.

### 4.15 DNS Plus GSLB 구성 — Terraform 커버리지 밖의 콘솔 전용 기능 ⭐
- **배경**: NHN DNS Plus 권한을 받은 뒤, 지금까지처럼 이 부분도 Terraform으로 코드화하려고 provider 스키마부터 확인했다.
- **발견 — provider에 Zone/Recordset만 있고 GSLB(Pool/헬스체크/FAILOVER)는 없음**: `terraform providers schema -json`으로 `nhncloud` provider의 리소스를 뒤져보니 `nhncloud_dns_zone_v2`/`nhncloud_dns_recordset_v2`만 있었다. 필드를 보면 OpenStack Designate 호환의 **일반 DNS 관리 기능**일 뿐, GSLB의 핵심인 Pool·헬스체크·우선순위 기반 FAILOVER 정책 필드가 전혀 없다. **즉 GSLB 자체는 Terraform으로 다룰 수 없고 NHN 콘솔에서 직접 구성해야 하는 영역**이다 — 인터넷 게이트웨이 생성 리소스가 provider에 없었던 4.4절과 같은 종류의 한계.
- **콘솔 UI 함정 — "DNS"와 "GSLB"가 완전히 다른 탭**: NHN Cloud 콘솔의 DNS Plus 서비스 안에 "DNS"(일반 Zone/레코드 관리)와 "GSLB"(Pool/헬스체크/GSLB 생성)가 서로 다른 최상위 탭으로 나뉘어 있다는 걸 모른 채로, "DNS → Zone → 레코드 세트 생성" 화면에서 GSLB용 레코드를 만들려다가 한참 헤맸다. 이 화면의 "레코드 세트 타입" 드롭다운(A/AAAA/CAA/CNAME/MX/NAPTR/PTR/TXT/SRV/NS)에는 애초에 GSLB 관련 타입이 없다 — **Pool/헬스체크/GSLB 생성은 전부 "GSLB" 탭에서, 그 결과로 만들어지는 GSLB 전용 도메인(예: `60vo8ll7y2hd1g7ms4.toastgslb.com`)을 "DNS" 탭에서 우리 도메인의 CNAME으로 연결**해야 완성된다. (AWS Route53 ALIAS나 Azure Traffic Manager와 비슷한 "서비스 자체 도메인 + CNAME 연결" 패턴)
- **엔드포인트 주소 입력 함정**: Pool의 엔드포인트 주소 필드는 `IP:포트` 형식을 안 받는다(콜론이 허용 문자 목록에 없음, "영어 소문자와 숫자, '.', '-', '_'만 입력 가능"). IP만 넣어야 하며, 포트(`30080`, NodePort)는 헬스체크 설정 쪽에서 별도로 지정한다. 실제 서비스 접속 시에는 GSLB가 IP만 넘겨주므로, URL에 포트를 직접 붙여야 한다(`http://www.chaosarena.cloud:30080`).
- **최종 구성**: Health Check(HTTP `/health`:30080) × 2 → Pool(`kr1-active` 우선순위1 / `kr2-standby` 우선순위2) × 2 → GSLB(`chaosarena`, 라우팅 규칙 FAILOVER, TTL 30초)에 두 Pool을 우선순위로 연결 → `www` CNAME을 GSLB 도메인으로 연결.
- **최종 검증**: `scripts/06-test-gslb-failover.sh`로 실시간 모니터링하며 KR1 파드를 `kubectl scale --replicas=0`으로 강제로 내림 → **약 80초 후** 응답이 `kr1-test`에서 `kr2`로 자동 전환(failover) 확인 → KR1을 다시 `--replicas=1`로 복구하자 자동으로 `kr1-test`로 되돌아오는 failback까지 실측 확인. 가비아 네임서버 전파도 예상(1~4시간)보다 훨씬 빨리 완료됐다.
- **알아둘 점**: TTL(30초)만으로 failover 속도가 결정되는 게 아니라, 헬스체크가 "몇 번 연속 실패해야 비정상으로 판단하는지" 기준까지 합쳐져서 실제 전환 시간(이번엔 약 80초)이 나온다 — TTL 값만 보고 전환 속도를 예단하면 안 된다.

### 4.16 Jenkins 파드 CrashLoopBackOff — 같은 파드 안 emptyDir이 재시도를 거듭하며 오염 ⭐
- **증상**: CI/CD 전용 탭 기능을 push했는데 KR2 앱이 계속 이전 빌드(#10)만 응답. GitHub 웹훅은 200을 반환했다는
  기록이 있었지만, 실제로는 그 시점에 Jenkins 자체가 죽어있었다.
- **진단**: `kubectl -n jenkins get pods`로 `jenkins-0`가 `0/2 Unknown`(28시간째)인 걸 확인. `describe pod`로
  보니 컨테이너 상태가 `CrashLoopBackOff`였고, 원인은 `init` 컨테이너(플러그인을 `/var/jenkins_plugins`
  emptyDir로 복사하는 단계)가 27번 연속 재시작 중이었다. 로그를 보니 `cp: overwrite '...jpi'?` 프롬프트가
  플러그인 파일마다 떠 있었다 — GNU `cp`는 대상 파일에 쓰기 권한이 없으면 `-i` 없이도 자동으로 덮어쓸지
  묻는데, 이 확인이 표준입력으로 들어오길 기다리다가 그대로 실패(exit 1)한 것이다.
- **근본 원인**: `jenkins-0`는 StatefulSet 파드라 컨테이너가 몇 번을 재시작해도 **파드 자체는 그대로**라서,
  `plugin-dir`(emptyDir) 볼륨도 파드 수명 내내 유지된다. 첫 실행에서 이미 플러그인을 다 복사해놨는데,
  그 다음 재시작(원인은 별개 — 아마 노드/리소스 이벤트로 컨테이너가 한 번 죽은 것)마다 init 컨테이너가
  똑같은 파일을 그 위에 다시 복사하려다가 "이미 있고 쓰기 권한 없음" 상태에 걸려 실패 → 실패하면 kubelet이
  다시 재시작 → 또 같은 자리에서 실패, 그대로 자기 자신을 되풀이하는 크래시 루프가 된 것.
- **해결**: `kubectl -n jenkins delete pod jenkins-0` — StatefulSet이 완전히 새 파드(새 emptyDir, 빈 상태에서
  시작)를 만들어주므로 약 80초 만에 `2/2 Running`으로 정상 복귀. Jenkins의 영구 데이터(Job 설정, 빌드 이력)는
  hostPath PV(`jenkins-home`)에 있어서 이 삭제로 전혀 영향받지 않았다.
- **후속 조치 — 놓친 웹훅 수동 복구**: Jenkins가 죽어있던 동안 도착한 GitHub 웹훅은 이미 유실되어 자동으로
  재시도되지 않는다. Jenkins가 복구된 뒤, `jenkins` 시크릿에서 admin 비밀번호를 꺼내 REST API(크럼(CSRF
  토큰) 발급 → `POST /job/chaos-demo-cicd/build`)로 빌드를 수동 트리거해서 마무리했다. build #11이
  SUCCESS로 끝났고, 실제 파이프라인 소요시간(42초)이 처음으로 실측되어 `DEPLOY_RANK_THRESHOLDS`(S≤90초)
  가 합리적인 범위였음도 같이 확인됐다(11.7절).
- **알아둘 점**: StatefulSet 파드는 "재시작해도 같은 파드"라는 성질이 있어서, 컨테이너 재시작 이력이
  emptyDir 상태에 누적될 수 있다는 걸 이번에 알게 됐다. 파드가 오래 살아있는데 특정 초기화 단계가
  반복 실패한다면, 그 단계가 "이전 실행의 흔적이 남아있는 상태"를 전제로 짜여있는지 의심해볼 것.

### 4.17 KR1 Terraform state drift 진짜 원인 — `image_id` + boot-from-volume 조합이 매번 서버 재설치를 부를 뻔함 ⭐
- **배경**: 4.x 이전(07-26)에 `admin_cidr`만 바꾸려고 `terraform plan`을 돌렸는데, 관계없어 보이는 KR1 워커 2대
  생성 + KR2 인스턴스 4대의 `image_id` in-place 업데이트가 같이 떴다. 원인을 모른 채 `-target`으로 보안그룹
  리소스만 scoped apply하고, 원인 파악 전까지 **일반(비-target) apply를 금지**해뒀었다.
- **조사 — 실제로 뭐가 바뀌려던 건지 `terraform plan` 출력을 그대로 읽음**: `image_id` 필드가
  `"Attempt to boot from volume - no image supplied"` → `<실제 이미지 UUID>`로 바뀌는 것으로 나왔다.
  이 문자열 자체가 단서였다 — 진짜 UUID가 아니라 사람이 읽으라고 써놓은 에러/설명 문구가 **state에 그대로
  저장돼 있었다**는 뜻이었다.
- **원인 확정 — 프로바이더 소스 코드까지 읽어서 확인**: `modules/chaos-cluster/compute.tf`가
  `nhncloud_compute_instance_v2`에 `image_id`를 직접 지정하면서 동시에 `block_device`로
  boot-from-volume도 쓰고 있었다. `terraform providers schema`로는 `image_id`가 `ForceNew: false`라는
  것만 보이고 "그래서 뭐가 위험한지"는 안 보여서, `gh api`로 프로바이더(`nhn-cloud/terraform-provider-nhncloud`)
  깃허브 소스(`resource_openstack_compute_instance_v2.go`)를 직접 받아 확인했다.
  - Read 함수: boot-from-volume 서버는 Nova API가 서버 자체의 이미지 참조를 안 주기 때문에(볼륨이 이미지로
    만들어진 것이지 서버가 아니라서), 이 프로바이더는 `image_id`를 그냥 `"Attempt to boot from volume -
    no image supplied"` 문자열로 state에 저장해버린다.
  - Update 함수: `image_id`가 바뀐 것으로 감지되면 `servers.Rebuild()`(Nova Rebuild API)를 호출한다 —
    **기존 서버를 새 이미지로 재설치**하는 진짜 파괴적인 동작이다(디스크 내용 전부 날아감).
  - 즉, config에 `image_id`를 직접 넣어둔 이상 **매 plan마다 저 가짜 문자열과 실제 이미지 UUID가 달라
    보여서 영원히 "변경 있음"으로 뜨고**, 만약 그 상태로 apply했다면 이미 정상 운영 중인 KR2 인스턴스 4대와
    KR1 워커까지 전부 `Rebuild()`로 재설치되어 쿠버네티스 클러스터가 통째로 날아갔을 것이다.
- **해결**: `compute.tf`의 `master`/`worker` 리소스에서 top-level `image_id` 인자를 제거(`block_device.uuid`만
  남김) — boot-from-volume을 쓸 땐 이게 이 프로바이더의 올바른 사용법이다. 수정 후 `terraform plan`으로
  재확인하니 `image_id` 관련 diff 6개가 전부 사라지고 `Plan: 2 to add, 0 to change, 0 to destroy`만 남았다.
- **남은 "2 to add"는 별개의, 이미 알고 있던 이슈**: `worker_count = 3`이 고정값인데 KR1은 RAM 쿼터 부족으로
  워커 1대(`worker3`)만 성공적으로 만들어진 상태라 나머지 2대가 항상 "생성 예정"으로 뜨는 것 — 코드 버그가
  아니라 KR1 정식 재구축(현재 진행 상황 5절 항목) 전까지는 그대로 둬야 하는 정상적인 pending 상태.
- **알아둘 점**: Terraform plan에 이상한 diff가 뜨면 "무슨 리소스가 왜 바뀌는지"까지만 보고 넘어가지 말고,
  값 자체(이번엔 사람이 읽는 에러 문자열)를 근거로 프로바이더 소스까지 내려가서 실제 API 호출(Update가
  뭘 하는지)을 확인하는 게 중요하다 — 겉보기엔 "이미지 버전이 최신으로 갱신되나보다" 정도로 넘어갈 수
  있었지만, 실제로는 운영 중인 서버를 통째로 밀어버리는 위험한 동작이었다.

### 4.18 HPA 도입 — "노드당 파드 1개" 강제 규칙이 스케일 아웃을 막던 문제 + 적용 중 겪은 실수 2건 ⭐
- **배경**: 선택 기능 목록에 있던 HPA(오토스케일링)를 KR2 `chaos-demo`에 도입. `resources.requests/limits`와
  `metrics-server`는 이미 준비돼 있어서(우연히) 바로 HPA 매니페스트만 있으면 될 줄 알았다.
- **막힌 지점**: `k8s/deployment.yaml`의 `podAntiAffinity`가 `requiredDuringSchedulingIgnoredDuringExecution`
  (강제)로 "노드당 파드 1개"를 걸고 있었는데, 워커가 정확히 3대뿐이라 HPA가 4번째 파드를 만들려는 순간
  이미 노드 3대 전부 파드가 하나씩 있어서 4번째가 영원히 `Pending`에 걸린다 — HPA가 "6개로 늘리자"고
  결정은 해도 실제로는 하나도 안 늘어나는, 겉으로 안 보이는 반쪽짜리 기능이 될 뻔했다.
  `requiredDuringScheduling` → `preferredDuringScheduling`(weight 100)으로 완화해서, 평소엔 그대로
  노드당 1개로 퍼지되 HPA가 늘릴 때만 한 노드에 여러 개를 허용하도록 고쳤다.
- **`minReplicas=3` 고정 이유**: `app.py`의 `EXPECTED_REPLICAS=3` 기반 미션 완료 판정과 절대 어긋나지
  않도록, HPA가 3 밑으로는 절대 못 내려가게 설계(위로만 6까지 확장).
- **적용 중 실수 ① — 이미지 태그가 조용히 롤백됨**: anti-affinity만 고치려고
  `kubectl apply -f k8s/deployment.yaml`을 그대로 실행했는데, 이 파일엔 예전 이미지 태그(`v4`)가
  하드코딩돼 있었다. Jenkins는 `kubectl set image`로 운영 중인 Deployment를 직접(imperative) 패치하기
  때문에 파일(git)과 실제 클러스터가 어긋나 있었고, `apply`가 그 차이를 "되돌려야 할 변경"으로 보고
  최신 빌드(jenkins-12)를 옛날 이미지로 덮어써버렸다. `kubectl set image`로 즉시 복구하고, 파일 태그도
  최신으로 맞춘 뒤 "이 필드는 Jenkins가 덮어쓰니 손으로 apply하기 전엔 먼저 현재 태그를 확인할 것"이라는
  경고 주석을 남겼다.
- **적용 중 실수 ② — 스케줄러가 낡은 이벤트를 붙잡고 재시도를 안 함**: 파드 하나가 `Pending`에서 안
  풀려서 봤더니, 이미 자리가 빈 노드가 있는데도 몇 분 전(다른 노드가 아직 안 비었을 때) 시점의 낡은
  `FailedScheduling` 이벤트만 있고 재시도 흔적이 없었다. 해당 파드를 삭제하니 ReplicaSet이 새로 만든
  파드가 현재 클러스터 상태 기준으로 바로 정상 스케줄됐다 — 스케줄러가 재시도 안 하는 것처럼 보이면
  막힌 파드를 지우고 새로 만들게 하는 게 빠른 우회법.
- **최종 검증(실측)**: `k8s/hpa.yaml` 적용 후 평소 `cpu: 11%/50%`(replicas 3, 노드당 1개) → 기존 "CPU
  부하" 버튼 On → `109%/50%`→`175%/50%`로 오르며 **실제로 3→6 스케일 아웃**(노드당 2개로 균등 분산) →
  버튼 Off 후 CPU 7%로 떨어졌지만 기본 5분 안정화 창 때문에 곧바로 안 줄고, 5분 뒤 **실제로 6→3 스케일
  다운**(`cpu: 10%/50%`, 노드당 1개로 재정렬)까지 확인.
- **알아둘 점**: CPU 부하 토글(`/chaos/cpu`)은 그 요청을 받은 파드 하나의 메모리 상태만 바꾸는 구조라,
  replicas가 6개로 늘어난 뒤엔 버튼을 반복 눌러도 매번 다른 파드가 걸릴 수 있다 — 검증 때는 각 파드
  IP에 직접 `/chaos/recover`를 호출해 확실하게 전부 껐다(고칠 필요는 없는, 알아두면 좋은 특성).

### 4.19 Ingress 도입 1단계 — GSLB를 안 건드리는 병렬 추가 방식으로 진행
- **배경**: 선택 기능 목록의 "Ingress+TLS" 중 Ingress만 먼저 진행. 지금 유일한 실제 외부 노출 방식은
  NodePort(`k8s/service-nodeport.yaml`, `:30080`)뿐이고(`service-loadbalancer.yaml`의 MetalLB는 파일만
  있고 클러스터에 적용된 적 없음), Ingress Controller도 클러스터에 아예 없었다.
- **왜 곧바로 실제 입구를 바꾸지 않았나**: GSLB Pool의 헬스체크가 KR1/KR2 양쪽의 `:30080`을 직접 찌르고
  있어서, 여기에 바로 손대면 이미 검증해둔 failover(4.15절)가 깨질 위험이 있었다. 그래서 사용자와 상의해
  **기존 NodePort/GSLB는 전혀 안 건드리고, ingress-nginx를 KR2에 새 NodePort(30081/30444)로 병렬
  추가**해서 라우팅 자체만 먼저 검증하기로 했다. TLS(cert-manager+Let's Encrypt)도 이번엔 빼고 다음
  작업으로 미뤘다 — Let's Encrypt의 HTTP-01 검증은 실제 80번 포트가 공인 도메인으로 열려있어야 하는데,
  병렬 테스트 단계에선 그 조건이 안 맞기 때문.
- **구성**: `k8s/ingress-nginx-values.yaml`(Helm values, NodePort 30081/30444 고정) → Helm으로
  `ingress-nginx` 설치 → `k8s/chaos-demo-ingress.yaml`(새 Service 없이 기존 `chaos-demo-nodeport`를
  백엔드로 재사용, host는 실제 DNS 미등록 테스트 전용 이름).
- **검증**: `curl -H "Host: ingress-test.chaosarena.cloud" http://<KR2 IP>:30081/api/status` → 200 정상.
  `curl -H "Host: wrong-host.example.com" ...` → 404(진짜 host 기반 라우팅 확인). 기존 `:30080` 직접
  접속과 `www.chaosarena.cloud`(GSLB) 접속 모두 그대로 200 — **회귀 없음**.
- **다음 단계(미착수)**: TLS 붙이기, 검증되면 GSLB Pool 헬스체크 대상을 Ingress의 80/443으로 전환하는
  실제 컷오버 여부 결정.

### 4.20 Ingress 도입 2단계 — 포트 재사용으로 GSLB를 안 건드리고 실제 입구로 전환
- **배경**: 4.19절의 병렬 구조(별도 NodePort 30081/30444)를 검증한 뒤, TLS는 다음으로 미루고 KR2의
  진짜 입구로 전환했다.
- **핵심 ① 포트 재사용**: GSLB Pool 헬스체크는 IP만 알고 포트(`:30080`)는 고정 설정이라(4.15절),
  `chaos-demo-nodeport`를 `NodePort` → `ClusterIP`로 바꿔 30080을 반납하고, `ingress-nginx-values.yaml`의
  `nodePorts.http`를 30081→30080으로 옮겨 **같은 포트를 ingress-nginx가 대신 갖게** 했다. 그 결과 GSLB
  콘솔/Terraform 보안그룹을 단 하나도 안 건드리고 전환이 끝났다.
- **핵심 ② catch-all 전환**: `chaos-demo-ingress.yaml`의 `host` 필드를 제거해 어떤 Host 헤더로 오든
  받는 규칙으로 바꿨다 — 4.19절에서 "등록 안 된 host → 404"를 라우팅이 동작한다는 증거로 확인했는데,
  실제 입구가 된 지금은 그 동작이 거꾸로 GSLB 헬스체크(Host 헤더 없이 `/health` 호출)를 막을 위험이었다.
- **전환 순서**: ClusterIP로 포트 반납 → helm upgrade로 ingress-nginx가 포트 확보 → Ingress catch-all
  적용. 순서를 반대로 하면 포트 충돌 에러가 난다.
- **무중단이었던 이유**: 전환 시점에 GSLB가 KR1을 Active로 보고 있어서 KR2로는 애초에 실사용자 트래픽이
  안 가는 중이었다.
- **검증**: `curl http://<KR2 IP>:30080/health`(Host 헤더 없음, GSLB와 동일 요청) → 200. `/api/status`
  정상 데이터. `www.chaosarena.cloud`(GSLB)는 그대로 KR1 응답, 전혀 영향 없음 — 회귀 없음.

### 4.21 Ingress 도입 3단계 — 포트 번호 없는 URL: hostPort + 마스터 노드 스케줄링, KR1까지 확장
- **배경**: 2단계까지는 `:30080`이 URL에 남아있었다. 원래 계획은 "TLS 붙일 때 같이"였는데, TLS(Let's
  Encrypt)와 "포트 없는 HTTP"는 사실 독립적인 문제라 이번엔 TLS 없이 80번 포트만 먼저 열었다.
- **NodePort로 안 되는 이유**: k8s NodePort는 30000-32767 범위만 허용. 진짜 80번은 hostPort(파드가
  노드 네트워크에 직접 바인딩)로만 가능하다.
- **왜 마스터 노드인가**: 워커에는 비용 절감을 위해 공인IP를 일부러 안 붙였다(2.2절 설계) — 공인IP는
  마스터에만 있다. hostPort는 파드가 실제로 뜬 노드에서만 의미가 있으므로, ingress-nginx를 마스터
  노드에 스케줄링해야 했다. `tolerations`(control-plane taint 허용) + `nodeSelector`(마스터 노드 이름)로
  구현. Jenkins를 hostPath PV 때문에 특정 워커에 고정했던 것과 같은 패턴("물리적 제약 때문에 특정
  노드에만 있어야 한다"), 이번엔 그 제약이 "공인IP 보유 여부"였다는 점만 다르다.
- **보안그룹은 이미 열려있었음**: 80번 포트는 예전 MetalLB용으로 이미 0.0.0.0/0에 열려있어서
  (`terraform/modules/chaos-cluster/network.tf`), Terraform 변경이 전혀 필요 없었다.
- **KR1까지 확장**: 이 시점 GSLB가 KR1을 Active로 보고 있어서, 실제 도메인(`www.chaosarena.cloud`)이
  포트 없이 보이려면 Active인 KR1에도 동일 구성이 필요했다. KR1엔 helm 자체가 없어서 새로 설치부터
  진행(`chaos-demo-nodeport` ClusterIP 전환 → ingress-nginx 설치 → catch-all Ingress, KR2와 동일 순서).
- **부수 관찰**: KR1 전환 작업 중 `:30080` 헬스체크가 잠깐 응답 못 하는 순간이 있었는지, GSLB가 그
  찰나에 KR2로 failover했다가 곧바로 failback하는 게 관찰됨 — 의도한 테스트는 아니었지만 GSLB가 짧은
  헬스체크 공백에도 설계대로 반응한다는 걸 실제로 재확인.
- **최종 검증**: `curl http://<마스터 공인IP>/api/status`(포트 없이) KR1/KR2 둘 다 200, 기존 `:30080`도
  회귀 없이 정상. **`curl http://www.chaosarena.cloud/api/status`(포트 없이) → 200** — 실제 도메인으로
  포트 없는 접속 확인 완료.

### 4.22 ArgoCD(GitOps) 도입 — Jenkins의 배포 권한을 없애고 Pull 모델로 전환
- **배경**: Jenkins가 빌드→서명→배포(`kubectl set image` 직접 실행)까지 전부 담당하는 Push 모델이었다.
  Jenkins처럼 외부 웹훅을 받는 시스템이 클러스터 배포 권한까지 들고 있으면, Jenkins가 뚫렸을 때 그
  권한이 그대로 악용될 수 있다. Jenkins는 CI(빌드+서명)만 담당하고, 배포는 클러스터 안의 ArgoCD가
  Git을 스스로 지켜보다 반영하는 구조(Pull, GitOps)로 바꾸기로 이전부터 방향을 정해뒀었다.
- **매니페스트 레포 분리**: `ChaosArena-manifests`라는 별도 GitHub 레포를 만들어 `k8s/`의 내용을
  옮겼다. 순수 K8s 매니페스트(`argocd-managed/`)와 Helm values 파일(`helm-values/`)을 폴더로
  분리했는데, 후자는 `apiVersion`/`kind`가 없는 값 파일이라 ArgoCD의 기본 디렉터리 동기화 방식으로
  처리가 안 되기 때문이다 — 이번 스코프는 "Jenkins가 매 빌드 바꾸는 대상"(앱 Deployment)에만 GitOps를
  적용하는 최소 범위로 잡았다. Helm 차트까지 관리하려면 차트별 `Application`(source.helm)을 추가로
  만들어야 하는데, 이건 다음 확장 과제로 남긴다.
- **GitOps 원칙과 어긋났던 부분 하나 발견**: `BUILD_NUMBER`/`GIT_COMMIT`/`DEPLOY_DURATION_SECONDS`는
  원래 Jenkins가 배포 직후 `kubectl set env`로 즉석에서 클러스터에만 심어주던 값이라(11.6절), Git에는
  없는 상태였다. 이대로 두면 ArgoCD의 self-heal이 "Git과 다르다"며 오히려 이 값들을 지워버릴 것이다.
  그래서 `k8s/deployment.yaml`에 이 세 값을 아예 선언해두고, Jenkins가 매니페스트 레포 사본에 값을
  채워 커밋하는 방식으로 바꿔서 "클러스터의 실제 상태 = Git의 내용"이 유지되게 했다.
- **Jenkinsfile 변경**: Deploy 스테이지(`kubectl set image/env/rollout status`) → "Update Manifests
  Repo" 스테이지(매니페스트 레포 clone → `yq`로 이미지 태그/env 값 구조적으로 편집 → commit/push)로
  교체. `sed`가 아니라 `yq`를 쓴 이유: env 리스트를 줄 순서 기반으로 바꾸면 순서가 조금만 달라져도
  깨지는데, `yq`는 "이름이 X인 항목의 value"처럼 구조로 찾아 바꿔서 몇 번을 반복 실행해도 안전하다.
  파드 템플릿에서 `kubectl` 컨테이너와 `jenkins-deployer` ServiceAccount도 제거했다 — 이제 클러스터
  권한이 전혀 필요 없다(`k8s/jenkins-deploy-rbac.yaml`은 참고용으로 남겨두되 더 이상 안 씀 표시).
- **배포 랭크(CI/CD 탭) 의미 변화**: `DEPLOY_DURATION_SECONDS`는 이제 "Jenkins가 빌드+서명+매니페스트
  커밋까지 끝낸 시간"이지, 실제 클러스터 반영까지의 시간이 아니다. ArgoCD 기본 폴링 주기(3분)를
  기다리면 체감 지연이 커서, 매니페스트 레포에도 Jenkins 웹훅과 같은 방식으로 GitHub Webhook을
  ArgoCD에 걸어 즉시 반영되게 했다.
- **작업 방식 변화**: 사용자가 "인프라를 직접 실행해보며 배우고 싶다"고 요청해서, ArgoCD 설치·새
  GitHub 레포 생성·Jenkins credential 등록 같은 실행형 작업은 이번부터 `docs/SETUP_GUIDE.md`에
  가이드로만 제시하고 직접 실행은 안 함(코드/설정 파일 편집만 담당).
- **최종 실측 검증 완료** ⭐ — 더미 커밋 push → Jenkins build #17이 SUCCESS로 끝나고
  `ChaosArena-manifests`에 새 커밋(`d8aed29`) 생성 → `kubectl -n argocd get application chaos-demo`가
  `Synced`/`Healthy` → `kubectl get deployment chaos-demo`의 이미지 태그가 `jenkins-17`로 일치하는 것까지
  Jenkins→Git→ArgoCD→클러스터 전체 파이프라인을 end-to-end로 확인. 이어서 앱 코드에 실제 변경(footer
  문구)을 넣어 build #18로 한 번 더 반복 검증.
- **`ChaosArena-manifests` 레포에 GitHub Webhook 등록 확인** — Payload URL
  `https://<마스터_공인IP>:30443/api/webhook`, SSL verification은 ArgoCD가 자체 서명 인증서를 쓰기 때문에
  Disable로 설정. 등록 직후 GitHub가 보낸 `ping` 이벤트에 ArgoCD가 `200`으로 응답한 것을 Recent
  Deliveries에서 확인 — 이제 ArgoCD 기본 3분 폴링을 기다릴 필요 없이 커밋 직후 몇 초 안에 반영된다.

### 4.23 GitOps 검증 중 Jenkins 에이전트가 영원히 "접속 대기"에 멈춤 — TCP 포트 바인딩 레이스 + K8s Service 고정 포트 불일치 ⭐
- **증상**: ArgoCD 도입 검증을 위해 더미 커밋을 push했더니, Jenkins 에이전트 파드(`kaniko`/`cosign`/`git`/
  `jnlp` 4개 컨테이너)는 전부 `Running`인데 Jenkins가 "빌드 태스크를 스케줄링하지 못하고 있다"며 빌드가
  끝없이 멈췄다(build #14, #15 둘 다).
- **1차 원인 격리**: `kubectl get pods -n jenkins`로 보니 `jenkins-0` 컨트롤러 자체가 `Unknown` 상태였다가,
  다시 보니 `Running`인데도 빌드가 안 풀렸다. 컨트롤러 로그(`kubectl logs jenkins-0 -c jenkins`)에서
  결정적 단서 발견:
  ```
  WARNING  Jenkins#launchTcpSlaveAgentListener: Failed to listen to incoming agent
  connections through port 50000. Change the port number
  ```
  이 WARNING의 발생 시각이 바로 몇 시간 전 4.16절 크래시루프를 고치려고 `kubectl delete pod jenkins-0`로
  강제 재생성했던 시점과 일치했다 — 컨테이너가 막 재시작된 직후, 커널이 이전 프로세스의 소켓 상태를 아직
  정리 못한 타이밍에 첫 바인딩 시도가 실패한 것으로 보인다(재시작 직후 한 번만 발생하는 레이스 컨디션,
  4.16절 emptyDir 오염과 같은 "재시작 타이밍 문제" 계열).
- **연쇄 효과**: 이 바인딩 실패로 `TcpSlaveAgentListener` 객체 자체가 생성되지 않았고, 그 결과 에이전트가
  접속 위치를 확인하려 두드리는 `/tcpSlaveAgentListener/` HTTP 엔드포인트가 아예 존재하지 않아 모든
  에이전트가 `404 Not Found`를 받으며 영원히 재시도만 반복했다(`jnlp` 컨테이너 로그로 확인).
- **1차 시도(Random 포트)의 함정**: Manage Jenkins → Security → Agents에서 TCP 포트를 Fixed 50000 →
  Random으로 바꿔 저장했더니 404는 사라졌다(설정을 저장하는 행위 자체가 리스너를 재초기화시켰고, 이번엔
  타이밍 문제가 이미 지나가 있어 바인딩이 성공한 것). 하지만 곧 새 에러가 나왔다:
  ```
  Agent discovery successful (Agent port: 50000) → Connecting to jenkins-agent...:50000
  → Connection refused
  ```
  원인: 이 프로젝트의 Kubernetes Service(`jenkins-agent`)와 모든 에이전트 파드의 `JENKINS_TUNNEL` 환경
  변수는 Helm 배포 시점에 **고정된 포트 50000**으로 이미 배선돼 있는데, 리스너가 실제로는 랜덤 포트에
  뜨면서 Service가 전달하는 50000번 트래픽을 아무도 안 듣게 된 것 — "포트 번호를 바꾸라"는 에러 메시지를
  액면 그대로 따른 게 오히려 Kubernetes 고정 배선과 어긋나는 새 문제를 만든 사례.
- **최종 해결**: 설정을 다시 Fixed 50000으로 되돌리고 저장(→ 리스너 재초기화 재트리거) + `jenkins-0` 파드
  한 번 더 완전 재생성. 이번엔 (a) 최초의 타이밍 문제도 이미 사라졌고 (b) 값도 Service/에이전트가 기대하는
  50000과 일치해서 정상 동작. build #17이 `Update Manifests Repo` 스테이지까지 SUCCESS로 완주.
- **교훈**: Jenkins가 뱉는 에러 메시지("Change the port number")를 액면 그대로 믿고 설정값 자체를 바꾸기
  전에, 그 값이 Kubernetes Service/환경변수 등 **다른 곳에도 고정 배선돼 있는지**부터 확인했어야 했다.
  결과적으로 문제를 실제로 푼 건 "포트 값 변경"이 아니라 "설정 저장 → 리스너 재초기화"였다.

### 4.24 GSLB 우선순위 재조정 — 풀 스펙 클러스터(KR2)를 Active로
- **배경**: 4.15절에서 GSLB를 처음 구성할 때 Pool 이름을 `kr1-active`(우선순위1)/`kr2-standby`(우선순위2)로
  만들었는데, 이후 KR1은 RAM 쿼터 문제로 최소 스펙 테스트 클러스터(마스터1+워커1)로 남고 Jenkins/Prometheus/
  ArgoCD 등 풀 스펙 구성은 전부 KR2에 올라갔다. 그 결과 **실제 서비스 트래픽이 계속 최소 스펙 클러스터로
  가고, 정작 잘 갖춰진 KR2는 대기만 하는** 상태로 방치돼 있었다 — 인프라 지도를 다이어그램으로 그려보다가
  발견.
- **변경**: NHN Cloud 콘솔 → DNS Plus → GSLB → `chaosarena` → 연결된 Pool의 우선순위를 `kr2-standby`=1,
  `kr1-active`=2로 수정(콘솔에서 "Pool 연결 수정"으로 우선순위 숫자만 바꾸는 것 — GSLB 자체가 Terraform
  미지원이라 4.15절 때처럼 콘솔 작업).
- **Pool 이름은 그대로 둠**: `kr1-active`/`kr2-standby`라는 이름 자체는 이제 실제 우선순위와 반대로 읽히지만
  (`kr2-standby`가 실제로는 1순위), NHN Cloud 콘솔에서 Pool 이름 변경 자체가 지원되지 않아 이름은 생성 당시
  그대로 남겨뒀다. **실제 동작은 이름이 아니라 우선순위 숫자로 결정**되므로 기능상 문제는 없다 — 콘솔을 볼
  다음 사람을 위해 이 문서에 명시.
- **검증**: 우선순위 변경 직후(TTL 30초) `dig +short www.chaosarena.cloud` → `114.110.162.53`(KR2 마스터
  공인IP) 확인. 트래픽이 실제로 KR2로 전환된 것을 확인.

### 4.25 Jenkins 자동 롤백 — 배포 후 헬스체크 실패 시 이전 버전으로 자동 복구
- **배경**: "다음 작업 리스트업"에서 선택한 항목. 지금까지는 Jenkins가 `ChaosArena-manifests`에 새
  이미지 태그를 커밋+push하는 순간 빌드가 SUCCESS로 끝났다 — 그 이미지가 실제로 클러스터에서 건강하게
  뜨는지는 아무도 확인하지 않았다.
- **방식 결정**: Argo Rollouts(카나리+자동분석을 지원하는 업계 표준 도구) 대신 **가벼운 자체 구현**을
  택함 — 새 CRD/컨트롤러 없이, 기존 Jenkinsfile에 `Verify Deployment` 스테이지 하나만 추가. 사용자가
  프로젝트 규모 대비 학습·설명 부담이 적은 쪽을 선택.
- **새 크레덴셜 없이 배포 상태를 확인하는 방법**: Jenkins는 GitOps 전환(4.22절) 때 클러스터 접근
  권한을 의도적으로 전부 제거했다. 여기서 kubectl이나 ArgoCD API 접근 권한을 새로 추가하면 그 원칙이
  무너진다. 그래서 앱이 이미 갖고 있는 `/api/status`를 **클러스터 내부 Service DNS**
  (`http://chaos-demo-nodeport.default.svc.cluster.local/api/status`)로 직접 호출하는 방식을 택했다 —
  순수 네트워크 호출이라 새 권한이 전혀 필요 없고, GSLB가 어느 리전을 Active로 보고 있는지와도
  무관하다(4.24절의 GSLB 상태에 의존하지 않음).
- **`/health`가 아니라 `build_number`를 확인하는 이유**: 롤링 업데이트(`maxSurge:0/maxUnavailable:1`)
  중엔 구버전 파드가 아직 살아있어서 `/health`는 계속 200을 준다. `/api/status`의 `build_number`가
  방금 push한 빌드 번호와 실제로 일치하는지까지 확인해야 "새 버전이 진짜 응답 중"이라는 게 증명된다.
- **롤백 구현**: `Update Manifests Repo` 스테이지에서 새 값을 쓰기 직전에 이전 값(이미지 태그,
  `BUILD_NUMBER`/`GIT_COMMIT`/`DEPLOY_DURATION_SECONDS`)을 `yq eval`(읽기)로 캡처해 워크스페이스에
  `rollback-info.env` 파일로 저장. `Verify Deployment`가 10초 간격 최대 12회(약 2분) 폴링 후에도
  `build_number`가 안 바뀌면, 그 파일을 `source`하고 yq의 `strenv()` 함수로 이전 값을 다시 써넣어
  `"ROLLBACK: ..."` 커밋을 push한다 — 롤백도 클러스터를 직접 안 건드리고 Git 커밋 하나로 처리된다
  (GitOps 원칙이 롤백에도 그대로 적용).
- **빌드 결과**: 롤백이 발생하면 `error()`로 파이프라인을 **FAILURE**로 마킹 — 롤백 자체는 성공해도
  "이 배포는 실패했다"는 신호가 Jenkins 화면에 바로 보이게 함.
- **변경 파일**: `Jenkinsfile`만 수정(새 인프라 설치 없음) — `Update Manifests Repo` 스테이지에 이전값
  캡처 로직 추가, 새 `Verify Deployment` 스테이지 추가.
- **실제 검증 결과 + 발견한 한계**: 일부러 `/health`를 깨서 push했더니 build #22가 헬스체크 타임아웃
  → `"ROLLBACK: ... build #21로 복구"` 커밋이 자동으로 push되고 빌드가 FAILURE로 표시되는 것까지
  라이브로 확인했다. 다만 그 build #21 자체가 (검증 로직 도입 전 빌드라) 이미 파드가 안 뜨는 상태였던
  걸 뒤늦게 발견 — **단일 단계 롤백은 "바로 이전 버전"으로만 되돌리기 때문에, 그 이전 버전 자체가 이미
  나쁜 상태면 복구가 안 되는 한계**가 있다(연속 실패 케이스). `/health`를 정상으로 되돌린 뒤 다시
  push해서 최종적으로 정상 복구됨을 확인. 이 한계는 발표에서 "가벼운 자체 구현이 커버 못 하는 지점"으로
  솔직하게 설명할 수 있는 지점으로 남겨둔다(Argo Rollouts 같은 이력 기반 롤백 도구라면 해결되는 문제).

### 4.26 CI/CD 탭 배포 히스토리 타임라인 — 성공/롤백 이력을 화면에 남기기
- **배경**: 4.25절의 자동 롤백은 실제로 잘 동작했지만, CI/CD 탭 화면에는 그 흔적이 안 남았다 — 롤백이
  일어나도 화면은 그냥 빌드 번호가 하나 줄어든 정상 배포처럼 보였다. 사용자가 "롤백 과정을 대시보드에
  어떻게 보여줄지 고민해보자"고 제안해서 진행.
- **저장 방식**: 새 DB/Redis 없이, `app.py`가 이미 갖고 있던 in-cluster ServiceAccount
  (`chaos-dashboard-sa`)에 `configmaps` 읽기(`get`) 권한만 추가(`resourceNames`로 이 ConfigMap 하나만
  제한, 최소 권한 유지). ConfigMap(`chaos-deploy-history`)도 `deployment.yaml`처럼
  `ChaosArena-manifests/argocd-managed/`에 두고 ArgoCD가 동기화 — 쓰기는 여전히 Jenkins→Git 커밋뿐,
  앱은 읽기만 한다(GitOps/권한 최소화 원칙 그대로 유지).
- **데이터 형식**: JSON 배열이 아니라 JSON Lines(줄 하나 = 이벤트 하나, 최신이 맨 위) — Jenkins의 git
  컨테이너엔 `jq`가 없어서 배열 조작이 번거로운데, JSON Lines는 "새 줄 붙이고 `head -n 10`으로 자르기"만
  하면 돼서 기존 `yq`/`head`만으로 충분하다.
- **기록 시점**: `Update Manifests Repo`가 아니라 결과를 확인한 뒤인 `Verify Deployment` 스테이지에서만
  기록 — 미리 "성공"으로 적어두면 그 뒤 롤백될 때 이미 틀린 기록이 남는 문제(낙관적 기록의 함정)를
  피하기 위함.
- **변경 파일**: `k8s/rbac.yaml`(configmaps get 권한 추가), `k8s/deploy-history-configmap.yaml`(신규),
  `Jenkinsfile`(Verify Deployment 성공/실패 분기에 이력 기록 로직 추가), `app.py`(`/api/deploy-history`
  엔드포인트), `templates/cicd.html`(타임라인 UI). `LOCAL_MODE=true`로 로컬 실행해 엔드포인트/화면 정상
  동작은 확인 완료, 실제 클러스터에 RBAC/ConfigMap을 반영하고 라이브 이벤트가 쌓이는 것 검증은 대기 중.

### 4.27 CI/CD 탭 UX 정합성 수정 — 파이프라인 단계 패널 제거 + 롤백 캡션 모순 해결
- **배경**: 사용자가 실제 화면 스크린샷을 보고 두 가지를 지적했다. (1) 배포 미션 결과의 큰 캡션이
  롤백이 나도 계속 "완벽한 배포! S랭크!"로 떠서 모순됨. (2) "파이프라인 단계" 패널이 4.22절에서 이미
  걷어낸 Jenkins 직접배포(push 모델) 순서를 그대로 보여주고 있어 실제 GitOps(ArgoCD Pull) 흐름과
  안 맞음.
- **1차 수정**: 파이프라인 단계 패널을 실제 흐름(Build&Push→Sign→Update Manifests→ArgoCD Sync→
  Verify)에 맞게 다시 쓰고, 배포 히스토리(4.26절)의 최신 이벤트가 롤백인지 확인해 큰 결과 패널에
  "🛡️ 배포 실패 감지 — 이전 안정 버전으로 자동 복구됨" 배너/캡션이 뜨도록 `applyRankCaption()` /
  `latestDeployIsRollback` 로직을 추가했다.
- **CI/CD 자동 트리거 버튼 검토(보류)**: 사용자가 "대시보드에 버튼 하나로 코드 변경 감지 → 자동
  빌드/배포"가 가능한지 물어, 가능은 하다고 답하되 트레이드오프를 함께 설명했다 — 앱이 Jenkins Job을
  트리거하려면 새 권한(Job trigger token)이 필요하고, 공인 IP로 열려있는 버튼이라 남용(무한 재배포
  유발) 위험이 있다. 사용자가 트레이드오프를 듣고 진행하지 않기로 결정.
- **2차 수정(파이프라인 패널 완전 제거)**: 위 논의에서 "파이프라인 단계는 굳이 대시보드에 필요없다"는
  결론이 나와, 패널 자체를 통째로 제거했다(관련 CSS `.pipeline-steps`/`.pipeline-step`/`.pipeline-tag`도
  삭제). GitOps 랭크 설명 한 줄만 결과 카드 아래로 옮겨 보존.
- **실측 검증**: `/health`를 일부러 두 번(각 수정 직후) 깨서 실제 KR2에서 롤백을 유발, 배너/캡션이
  올바르게 바뀌는 것과 `/health` 복구 후 다시 원래 캡션으로 돌아오는 것까지 라이브로 확인했다.
- **변경 파일**: `templates/cicd.html`만 수정(백엔드/인프라 변경 없음).

### 4.28 Jenkins 파드 CrashLoopBackOff 재발 — 4.16과 동일 원인, 동일 해결
- **증상**: 다음날 아침 Jenkins 웹 콘솔 접속 불가. `kubectl describe pod jenkins-0 -n jenkins`로 확인해
  보니 메인 `jenkins` 컨테이너가 아니라 **init 컨테이너**가 CrashLoopBackOff(재시작 8회) 상태였다.
- **원인**: `kubectl logs jenkins-0 -n jenkins -c init --previous`로 확인 — 플러그인 복사 단계(`cp`)가
  대화형 덮어쓰기 확인 프롬프트에 걸려 멈춰있었다. 같은 파드 안에 남아있던 `plugin-dir` emptyDir이
  이전 재시도들의 잔여물로 오염된 것 — **4.16절에서 이미 겪었던 것과 완전히 동일한 실패 패턴**이었다.
- **해결**: `kubectl delete pod jenkins-0 -n jenkins`. `jenkins-home`은 PVC라 job 이력/JCasC 설정/
  크레덴셜은 전부 보존되고, 오염된 emptyDir만 새로 생성돼(StatefulSet이 파드를 재생성) 정상 기동했다.
- **부수 정리**: 같은 시점에 사용자가 orphan 상태(`Unknown`, 18시간 경과)였던 별도 파드
  (`chaos-demo-cicd-14-...`, `jenkins` 네임스페이스)도 직접 삭제했다 — 이건 build #14의 **일회성 빌드
  에이전트 파드**로, `default` 네임스페이스의 실제 `chaos-demo` 앱 파드와는 무관한 자원이라 삭제해도
  안전함을 확인해줬다.
- **교훈**: 같은 실패 패턴이 재발할 수 있다는 걸 전제하고, PROJECT_LOG에 남긴 이전 사례를 먼저 찾아보는
  게 새로 원인 분석하는 것보다 빨랐다.

### 4.29 GitHub 웹훅 배포 실패 — Jenkins가 다운된 순간의 delivery는 자동 재시도되지 않음
- **증상**: (4.28 복구 직후) UI 수정 커밋을 push했는데 한참이 지나도 `/api/status`의 빌드 번호가
  바뀌지 않았다.
- **원인 확인**: `gh api repos/wonju90/ChaosArena/hooks/{hook_id}/deliveries`로 최근 delivery 목록을
  조회해보니, 해당 push의 delivery가 `502 failed to connect to host`(그 순간 Jenkins가 CrashLoop 중
  이었기 때문)로 실패해 있었다. **GitHub는 실패한 웹훅 delivery를 자동으로 재시도하지 않는다**는 것도
  이번에 확인했다.
- **해결**: 실패한 delivery ID를 찾아 `gh api -X POST .../deliveries/{id}/attempts`로 수동 재전송했다.
  새 `200 OK` delivery가 찍히는 것을 확인한 뒤, `/api/status`/`/api/deploy-history`를 폴링해 빌드가
  정상적으로 넘어가고 성공 이력까지 기록되는 것을 확인했다. 세션 후반 또 다른 push에서 같은 증상이
  한 번 더 나타나 동일한 방법으로 해결했다.
- **왜 새 커밋을 만들지 않았나**: 코드는 이미 올바르게 push돼 있었고 문제는 순전히 "그 순간 알림이
  전달 안 된 것"뿐이라, 빈 커밋이나 재push 대신 웹훅 재전송이 더 정확한 수정이었다.
- **교훈**: "push했는데 배포가 안 됨"이 항상 코드/파이프라인 문제는 아니다 — 웹훅 delivery 로그를 먼저
  확인하는 게 원인 파악에 더 빨랐다.

### 4.30 대시보드 UI 일관성 개선 — 색상 규칙 / 빈 여백 / 그리드 통일
- **배경**: 사용자가 4개 페이지 스크린샷을 보고 "중구난방해보인다"고 피드백. 헤드리스 Chrome
  스크린샷으로 4개 페이지를 나란히 비교해 원인을 3가지 축으로 좁혔다.
- **1) 색상 규칙**: `stat-tile`의 accent 5색(blue/green/orange/red/gold)이 이미 대부분 일관됐는데
  (파랑=카운트/식별, 주황=시간, 빨강=경고, 금색=최고기록), `cicd.html`의 "커밋" 타일만 초록(=정상/성공
  의미)을 쓰고 있어 유일한 예외였다. `stat-accent-green` → `stat-accent-blue`로 통일하고, 앞으로 새
  지표를 추가할 때 참고하도록 `base.html`에 색상 규칙을 주석으로 남겼다.
- **2) 빈 여백**: `game.html`(대기 화면)과 `cicd.html`은 하단에 공백이 컸는데, 새 API/DB 없이 이미
  있는 `/api/records` · `/api/deploy-history`를 재사용해 서로를 요약해서 보여주는 크로스링크 패널을
  추가했다(게임 콘솔엔 "최근 전적", CI/CD엔 "최근 장애 복구 기록", 기록실엔 "최근 배포 이력"). "파드
  복구도 게임, 배포도 게임"이라는 이 프로젝트의 기존 테마도 자연스럽게 강화됐다.
- **3) 그리드 구조**: `game.html`/`cicd.html`은 이미 `2:1` 비대칭 분할이었는데 `records.html`만 대칭
  2분할이라 달랐다 → 위 크로스링크 패널을 사이드 칸에 배치하면서 자연스럽게 같은 `2:1` 구조로
  재편했다. **`monitor.html`은 의도적으로 제외** — Chart.js 캔버스 2개가 이미 화면을 꽉 채우고 있어
  억지로 구조를 맞추면 리사이즈 회귀 위험만 크고 얻는 게 적다고 판단했다(모니터링류 페이지가
  전체너비 스택인 건 그 자체로 흔한 패턴).
- **그 외**: 모든 페이지 공통 footer의 작은 태그라인 제거, `records.html`의 빈 상태(포디움/히스토리)
  문구를 아이콘+CTA 버튼이 있는 통일된 empty-state 컴포넌트로 재작성.
- **후속(모니터링 페이지 크로스링크)**: 위 3페이지 작업 뒤 `monitor.html`만 다른 페이지와의
  크로스링크가 없다는 걸 재확인해, "파드 요약" 패널에 기록실 링크 한 줄을 추가했다(그리드 구조는
  그대로 유지).
- **검증**: 매 변경마다 로컬(`LOCAL_MODE=true`)에서 헤드리스 Chrome 스크린샷으로 레이아웃을 확인하고,
  각 페이지의 기존 `id`가 그대로 남아있는지 grep으로 재확인해(기존 폴링 로직 회귀 방지) 커밋했다.
  실제 커밋(`e4d3cc3`, `9130192`, `aa1e3df`) push 후 KR2에 배포되는 것까지 확인.
- **변경 파일**: `templates/base.html`/`cicd.html`/`game.html`/`records.html`/`monitor.html`(전부
  프론트엔드, 백엔드/인프라 변경 없음).

### 4.31 기록실(리더보드) Redis 도입 — 실제 라이브 검증 완료
- **배경**: 4.30절 UI 작업 도중, 사용자가 실제 화면에서 "빌드 #38 배포 직후 기록실이 0으로 리셋"되는
  걸 직접 목격했다. 원인은 `records` dict(`app.py:107`)가 그 요청을 처리한 파드 프로세스의 메모리에만
  있어서 — (1) CI/CD 자동 배포(코드와 무관한 문서 커밋 포함)가 파드를 롤링 교체할 때마다 초기화되고,
  (2) replica 3개끼리 메모리를 공유하지 않아 sticky session 없이는 서로 다른 값을 보여준다는 것.
- **결정**: Redis 도입. Postgres/SQLite 대신 Redis를 택한 이유, Helm 차트 대신 직접 작성한
  StatefulSet+hostPath PV(Jenkins와 다른 워커 노드)를 택한 이유, `ZADD ... GT CH`로 동시성 레이스를
  없앤 방법 등 설계 근거는 `docs/CONCEPTS.md` 20절 참고. `current_mission`/`chaos_state`/
  `metrics_state`는 의도적으로 손대지 않음(스코프를 명확히 좁힘).
- **구현**: `app.py`에 `get_redis_client()`(REDIS_HOST 비어있으면 None → in-memory로 저하) +
  `_record_completion()`/`_fetch_records_snapshot()` 추가, `_complete_mission()`/`api_records()`/
  `api_records_reset()`은 이 두 헬퍼만 호출하도록 재작성. `PROMETHEUS_URL`/`SLACK_WEBHOOK_URL`과
  동일한 "선택적 외부 의존성 + 좁은 try/except + 로그 후 계속" 패턴을 그대로 따름. 새 파일
  `k8s/redis-pv.yaml`/`k8s/redis.yaml`/`k8s/redis-secret.example.yaml`, `k8s/deployment.yaml`에
  `REDIS_HOST`/`REDIS_PORT`/`REDIS_PASSWORD` env 추가, `requirements.txt`에 `redis==5.0.8`.
- **로컬 검증**: Homebrew `redis-server`를 띄워 (1) 미션 완료 → Redis에 정상 기록, (2) 앱 프로세스를
  죽였다 재시작해도 기록 유지(재배포 시뮬레이션), (3) Redis를 꺼둔 상태에서도 앱이 500 없이 파드
  메모리로 저하하며 미션도 정상 진행, (4) `REDIS_HOST` 아예 미설정 시 기존 로컬 개발 방식 그대로
  회귀 없음, (5) 리셋 시 Redis 키까지 깨끗이 삭제 — 5가지 시나리오 전부 실측 확인.
- **⚠️ 실제 롤아웃 중 발견한 문서 실수**: SETUP_GUIDE.md 10.5 초안이 "이 레포의 `k8s/deployment.yaml`을
  복사해서 `ChaosArena-manifests`에 push"라고 안내했는데, 그대로 따르면 Jenkins가 관리하는 실제
  이미지 태그/`BUILD_NUMBER`/`GIT_COMMIT`/`DEPLOY_DURATION_SECONDS`를 통째로 덮어써서 최신 빌드가
  옛날 이미지로 롤백될 뻔했다. 사용자가 실제로 그 단계를 진행하며 화면을 공유해줘서 발견 →
  "새 env 3줄만 손으로 추가, 나머지 필드는 그대로 둔다"는 방식으로 즉시 수정(9.8절과 같은 "파일
  일부만 최초 1회 수동 반영" 패턴). 가이드 문서 자체도 실제로 한 줄씩 따라 해봐야 이런 실수를
  잡아낼 수 있다는 사례.
- **KR2 실제 클러스터 검증 완료**: `redis-secret`/`redis-pv`/`redis` StatefulSet 적용 →
  `kubectl delete pod redis-0` 후에도 `smoke-test` 키가 살아있음을 확인(PV/RDB 정상). `redis-cli
  keys "records:*"` 조회 결과 실제 미션 완료 후 `incidents`/`leaderboard`/`recovery_sum`/
  `recent_history`/`current_combo`/`best_combo`/`leaderboard:seq` 7개 키 전부 정상 생성 확인.
  **최종 확인**: 이 문제를 처음 발견했던 시나리오를 그대로 재현 — 문서 수정 커밋(`e0d487e`)을
  push해 Jenkins→ArgoCD 자동 재배포(build #39→#40)를 유발한 뒤 `/api/records`를 다시 조회, 배포
  전과 완전히 동일한 값(`total_incidents: 3`, `best_recovery_seconds: 1.2`, 리더보드 3건)이 유지되는
  것을 확인 — 처음 이 작업을 시작하게 만든 그 버그가 실제로 해결됐음을 증명했다. (참고로 같은 응답의
  `total_requests`/`avg_response_ms`는 이번에도 0으로 리셋됐는데, 이는 의도적으로 Redis로 안 옮긴
  `metrics_state`이므로 예상된 동작이다.)

### 4.32 대시보드에 오토스케일링(HPA) 패널 추가

- **배경**: HPA(4.18절)가 실제로 3→6으로 스케일 아웃하는 건 파드 개수로 화면에서 확인할 수 있었지만,
  "왜(CPU 몇 %인지)"는 `kubectl get hpa`로만 볼 수 있었다. 사용자가 "대시보드에서 육안으로 확인할 수
  있는 기능이 있냐"고 물어서, 없다는 것과 트레이드오프를 설명한 뒤 추가 요청을 받아 구현.
- **구현**: `k8s/rbac.yaml`에 `autoscaling/horizontalpodautoscalers` 리소스 하나(`chaos-demo`)만
  `get` 권한 추가(배포 이력 ConfigMap과 동일한 최소 권한 패턴). `app.py`에 `AutoscalingV2Api` 클라이언트
  + `/api/hpa` 엔드포인트 추가 — `PROMETHEUS_URL`과 같은 "선택적 연동 + 우아한 저하"(HPA 미설치
  클러스터는 `available:false`) 패턴 재사용. `LOCAL_MODE`에서는 이미 있는 `chaos_state["cpu_load"]`
  토글로 스케일 아웃을 흉내내는 목업 사용. `templates/monitor.html`에 현재/목표 레플리카, min/max,
  CPU 사용률 바(목표 초과 시 주황색)를 보여주는 새 패널 추가, 5초 폴링.
- **로컬 검증**: `LOCAL_MODE=true`로 CPU 부하 버튼 on/off 각각에 대해 `/api/hpa` 응답과 화면 렌더링
  (막대 색상 전환 포함) 스크린샷으로 확인 완료.
- **변경 파일**: `app.py`, `k8s/rbac.yaml`, `templates/monitor.html`.

### 4.33 KR1(판교) RAM 쿼터 해결 → 정식 재구축 + 원래 설계대로 Active 전환 ⭐

- **배경**: 4.24절에서 KR1이 최소 스펙(RAM 쿼터 부족)이라 KR2를 임시로 Active(우선순위 1)로 바꿔둔
  채로 지금까지 운영해왔다. 공유 교육 계정의 KR1 RAM 쿼터가 풀려서, 원래 설계(3.3절, KR1 Active/KR2
  Standby)대로 되돌리는 작업을 진행.
- **Terraform 재구축**: `terraform.tfvars`의 `kr1_flavor_name`이 이미 `r2.c4m16`(정식 스펙)으로
  미리 채워져 있었던 걸 발견 — 쿼터 부족으로 실제 적용만 안 됐던 상태. `terraform apply` 결과
  `2 to add, 2 to change, 0 to destroy`(워커 2대 신규 + 마스터/워커3 flavor in-place 교체, KR2는
  변경 없음)로, 우려했던 것보다 안전하게 완료됐다.
- **예상 밖의 발견 — in-place resize라 기존 클러스터가 그대로 생존**: flavor 변경이 destroy 없이
  in-place update로 처리돼서, 마스터와 워커3의 **OS 디스크(및 그 위의 kubeadm 클러스터 상태)가
  그대로 유지**됐다. 즉 기존 최소 스펙 테스트 클러스터(마스터 init + Calico + ingress-nginx +
  `chaos-demo` 1replica)가 리사이즈 후에도 살아있어서, Part 2(마스터 init/Calico)와 Part 8
  (ingress-nginx)를 처음부터 다시 할 필요가 없었다 — 새로 만들어진 워커 2대만 `kubeadm join`으로
  기존 클러스터에 합류시키는 것으로 충분했다. terraform plan 단계에서 "0 to destroy"를 미리 확인해둔
  덕분에 이 가능성을 예측하고 불필요한 재작업을 피할 수 있었다.
- **트러블슈팅 — join 명령 복붙 실수**: 터미널에서 줄바꿈된 `kubeadm join <주소>:6443 --token ...
  --discovery-token-ca-cert-hash sha256:...` 명령을 복사할 때 해시값만 잘려서 붙여넣어져
  `discovery.bootstrapToken.token: Invalid value: ""` 류의 에러 발생. 원인은 단순 복붙 실수였고,
  전체 명령을 한 줄로 다시 붙여넣어 해결.
- **트러블슈팅 — PV가 `Terminating`에서 안 지워짐**: `redis-pv-kr1.yaml`(아래 항목)의 `nodeAffinity`
  값을 잘못 적용해서(파일이 아직 git에 없어 `git pull`로 못 받았는데 그 사실을 모른 채 구버전 파일로
  적용) `kubectl delete pv`를 했더니 `Terminating`에서 멈췄다. 원인은 `data-redis-0` PVC가 여전히
  그 PV를 참조하고 있어서 `kubernetes.io/pv-protection` finalizer가 삭제를 막고 있었던 것 — StatefulSet
  → PVC → PV 순서로 먼저 지우니 정상적으로 정리됐다(finalizer 강제 제거는 필요 없었음).
- **KR1 전용 Redis 신규 설치**: `k8s/redis-pv-kr1.yaml`(신규, KR2 버전과 동일 패턴이나
  `chaosarena-worker2-kr1`에 고정) + 기존 `redis.yaml`/`redis-secret.example.yaml`을 KR1용 값으로
  복사해 적용. KR1은 Jenkins가 없는 클러스터라(CI/CD는 KR2 전용) 어느 워커에 둬도 다른 컴포넌트와
  충돌할 위험이 없다. `deployment.yaml`의 `REDIS_HOST`가 클러스터 내부 DNS(`redis.default.svc.cluster.local`)
  라서 코드 변경 없이 "각자 자기 리전의 Redis"에 자동으로 연결됐다.
- **트레이드오프 — 리전별 리더보드 분리**: KR1/KR2가 각자 독립된 Redis를 쓰므로, 두 리전 다 살아있는
  상태에서 GSLB DNS 캐시가 아직 안정되지 않은 짧은 구간(failover 테스트 직후)에는 어느 리전에 붙느냐에
  따라 기록 수·최고기록이 다르게 보이는 게 관찰됨. 이건 버그가 아니라 "리전마다 독립된 상태"를 선택한
  설계의 자연스러운 결과 — Active/Standby 구조상 평소엔 한쪽만 트래픽을 받으므로 실사용에는 영향 없음.
- **최종 검증**: chaos-demo 파드 강제 삭제 후에도 `/records`의 `total_incidents`가 유지되는 것으로
  KR1 Redis 영속성 확인. GSLB Pool 우선순위를 `kr1-active`=1/`kr2-standby`=2로 원복(4.24절 이전 상태로
  복귀) 후, `scripts/06-test-gslb-failover.sh`로 양방향 재검증: KR1 강제 다운 → 약 67초 후
  `FAILOVER 감지: kr1 → kr2`, KR1 복구 → `FAILOVER 감지: kr2 → kr1`(failback)까지 실측 확인.
- **변경 파일**: `k8s/redis-pv-kr1.yaml`(신규), `terraform.tfvars`(값은 이미 있었음, 변경 없음),
  KR1 클러스터 쪽 리소스(Deployment/Redis/RBAC/secret)는 매니페스트 레포가 아니라 마스터에서 직접
  `kubectl apply`(KR1은 GitOps 대상이 아님, CI/CD는 KR2 전용).

### 4.34 컨트롤 플레인 이중화 — KR1에도 Jenkins/ArgoCD/모니터링 복제 + 실제로 겪은 4가지 장애물 ⭐

- **배경**: "액티브(KR1)가 오래 죽으면 스탠바이(KR2)로 failover 되니 안전하다"고 설계했지만, 반대로
  **컨트롤 플레인(Jenkins/ArgoCD)이 있던 KR2 자체가 오래 죽으면** KR1이 멀쩡히 서비스 중이어도 새
  코드를 배포할 방법이 없어진다는 걸 사용자가 지적. `docs/CONCEPTS.md` 21절에서 "컨트롤 플레인은
  복제 안 해도 된다"고 정리했던 판단에 예외가 있다는 뜻이라, 그 판단 기준을 21.6~21.7절로 갱신하고
  실제로 KR1에도 Jenkins+ArgoCD+kube-prometheus-stack을 통째로 복제했다.
- **설계**: 새 매니페스트 레포 대신 `ChaosArena-manifests`에 `argocd-managed-kr1/`을
  `argocd-managed-kr2/`(기존 `argocd-managed/`를 개명)의 형제 폴더로 추가. Jenkinsfile은 포크하지
  않고 컨트롤러의 `env.REGION` 값 하나로 매니페스트 경로/이미지 태그 접두어를 분기(`SETUP_GUIDE.md`
  Part 11 참고).
- **장애물 1 — `containerEnv`로 심은 `REGION`이 Pipeline에 전달 안 됨** ⭐: Helm values의
  `controller.containerEnv`는 컨트롤러 **컨테이너의 OS 환경변수**만 설정할 뿐, Jenkins Pipeline이
  참조하는 `env.REGION`과는 다른 채널이다. 이 상태로 배포했더니 이미지 태그가 `null-jenkins-51`로
  찍히고 `cd manifests-repo/argocd-managed-null`이 없어서 빌드 4개(#48~51)가 연속 실패 — 다행히
  실패 지점이 "Update Manifests Repo" 단계라 실제 배포(프로덕션) 이전이라 서비스엔 영향 없었다.
  JCasC(`controller.JCasC.configScripts`)의 `jenkins.globalNodeProperties[].envVars.env[]`로
  바꾸니(Jenkins UI의 "Manage Jenkins → 전역 환경변수"와 동일한 정식 통로) 해결, build #53부터
  `kr2-jenkins-53` 태그로 정상 빌드됨을 확인.
- **장애물 2 — `git pull --rebase` 한 번만으로는 동시 push 충돌을 못 막음** ⭐: KR1/KR2가 처음으로
  진짜 동시에 빌드된 회귀 테스트에서, KR2가 `pull --rebase`(성공) 직후 `push`하려는 그 짧은 틈에
  KR1의 빌드가 먼저 push를 끝내버려 KR2의 push가 `[rejected] (fetch first)`로 거부됨. "확인 후
  실행" 사이엔 항상 남이 끼어들 틈이 남는다는 걸 실측으로 확인 — push 실패 시 다시 rebase하고
  재시도하는 루프(최대 5회, 매번 랜덤 지터)로 감싸서 해결. 이후 같은 소스 커밋으로 KR1/KR2를 다시
  동시에 트리거했을 때 이번엔 둘 다 SUCCESS로 끝나는 것으로 재검증.
- **장애물 3 — `manifests-repo-token`을 KR2와 다른 값으로 잘못 발급** ⭐: 설계상 이 PAT은 KR2와
  완전히 동일한 값을 재사용해야 한다(레포 쓰기 권한은 요청이 어느 서버에서 왔는지와 무관하기
  때문 — GitHub 계정에 귀속된 권한이지 서버별 권한이 아니다). 그런데 KR1 셋업 때 "새 서버니까 새
  토큰"이라는 직관적이지만 틀린 판단으로 별도 PAT을 새로 발급해 넣었고, 그 결과 KR1 Jenkins가
  빌드·서명까지 전부 성공하고도 마지막 `git push origin main`에서
  `remote: Permission ... denied ... 403`으로 실패. 두 시크릿의 값을 직접 비교(`github_pat_...`
  접두어까지는 같지만 그 뒤 랜덤 문자열이 완전히 다름)해서 원인을 확정하고, KR2와 동일한 값으로
  재생성해 해결.
- **장애물 4 — ArgoCD 웹훅이 TLS 인증서 SAN 에러로 계속 실패** ⭐: `ChaosArena-manifests` 레포에
  KR1 ArgoCD용 웹훅(`https://<KR1 IP>:30443/api/webhook`)을 등록했는데 GitHub의 Recent Deliveries에
  `tls: failed to verify certificate: x509: cannot validate certificate ... doesn't contain any IP
  SANs`로 계속 실패. ArgoCD가 자체 서명 인증서를 쓰는데 그 인증서에 접속 IP가 SAN으로 안 박혀있어서
  GitHub가 신뢰를 못 한 것 — 웹훅 설정의 "SSL verification"을 Disable로 바꾸고 나서야 delivery 성공. **이 웹훅이
  없는 상태에서 실제로 겪은 부작용**: ArgoCD가 기본 3분 폴링에 의존하는데 Jenkins의 헬스체크 대기는
  약 2분(10초×12회)뿐이라, 실제로는 정상적으로 배포됐을 빌드(#4)가 "너무 늦게 반영됐다"고 오판되어
  자동 롤백 커밋이 push되는 걸 라이브로 목격 — 웹훅 등록 후 재검증하니 몇 초 안에 반영되어 롤백 없이
  SUCCESS로 끝남.
- **최종 검증 — 이번 작업 전체의 성공 기준**: `kubectl -n jenkins scale statefulset jenkins
  --replicas=0`로 **KR2 Jenkins를 실제로 완전히 내려놓고** 커밋을 push. KR1이 빌드→서명→매니페스트
  커밋→ArgoCD 반영까지 사람 개입도, KR2의 어떤 컴포넌트의 도움도 없이 혼자 끝내는 것을 실측
  확인(build #7, S랭크). GitHub Webhooks 화면에서도 그 순간 KR2 쪽 delivery는
  `failed to connect to host`, KR1 쪽은 성공으로 명확히 갈려서 남아 교차 검증됨. 검증 후 KR2
  Jenkins는 `--replicas=1`로 복구.
- **변경 파일**: `Jenkinsfile`(REGION 기반 경로/태그 분기 + push 재시도 루프),
  `k8s/jenkins-values.yaml`(KR2, JCasC REGION 추가)/`k8s/jenkins-values-kr1.yaml`(신규),
  `k8s/jenkins-pv-kr1.yaml`(신규), `k8s/argocd-application.yaml`(KR2, path →
  `argocd-managed-kr2`)/`k8s/argocd-application-kr1.yaml`(신규),
  `k8s/alertmanager-slack-values.yaml`(KR2, `[KR2]` 제목 접두어)/
  `k8s/alertmanager-slack-values-kr1.yaml`(신규, `[KR1]` 접두어), `ChaosArena-manifests` 레포의
  `argocd-managed` → `argocd-managed-kr2`(rename) + `argocd-managed-kr1/`(신규 시딩).

### 4.35 인프라 지도(/infra) 탭 — 리전 상태 + GSLB 페일오버를 화면으로 관찰 ⭐

- **배경**: 4.34절에서 만든 컨트롤 플레인 이중화는 "KR2가 죽어도 KR1이 혼자 배포할 수 있다"를
  증명했지만, 그 failover 자체(8절 GSLB)는 지금까지 `scripts/06-test-gslb-failover.sh`라는 외부
  스크립트로만 관찰 가능했다. 사용자가 "ArgoCD의 앱 트리 화면처럼, 인프라 전체를 한눈에 보여주고
  리전을 강제로 내리면 실시간으로 빨갛게 반응하는 대시보드"를 새 탭으로 요청.
- **범위 확정 (Plan 단계에서 사용자에게 직접 질문)**: 리전을 "죽이는" 것 자체를 앱 안의 버튼으로
  만들지 물었고, **패시브(관찰만) 방식**으로 확정 — 실제 kill 버튼을 만들려면 이 public 앱이 반대편
  리전을 조작할 크레덴셜을 들고 있어야 해서, "이 앱은 자기 파드만 최소 권한으로 건드린다"는 기존
  RBAC 원칙과 충돌하기 때문. 리전은 지금처럼 사용자가 터미널에서 직접 내리고, 대시보드는 결과만
  관찰한다.
- **설계 검증(Plan 에이전트 크리틱에서 잡힌 것)**: 처음 구상은 "요청마다 상대 리전에 동기 HTTP
  확인"이었는데, 이러면 리전이 죽어있는 바로 그 데모 순간에 폴링마다 timeout(2초)을 기다리게 돼
  화면 자체가 굼떠지는 문제가 있었다. `_cpu_burn`(CPU 부하 시뮬레이션)에 이미 쓰던
  `threading.Thread(daemon=True)` 패턴을 재사용해서, 5초마다 백그라운드에서 미리 확인해 캐시
  딕셔너리를 통째로 스왑해두고 `/api/regions`는 그 캐시만 읽게 바꿨다. 또한 브라우저가 상대 리전
  공인IP에 직접 fetch하는 안도 검토했는데, CORS 헤더를 새로 추가해야 하고 timeout/에러 처리를
  클라이언트 JS마다 따로 구현해야 해서 배제하고 서버사이드 프록시로 확정했다(처음엔 "사이트가
  HTTPS라 믹스드 콘텐츠로 막힐 것"이라고도 예상했는데, 이건 아래 실제 장애물에서 틀린 전제였음이
  드러났다).
- **GSLB "현재 트래픽 대상"은 추측하지 않고 실제로 확인**: 상대 리전이 안 닿는다고 "그럼 자기
  자신이 대상이겠지"로 지레짐작하지 않고, 공개 도메인(`http://www.chaosarena.cloud/api/status`)을
  실제로 호출해 `version` 필드로 판정 — 이래야 이 기능의 존재 이유인 GSLB의 실제 TTL 지연
  (30~80초)을 화면에서 그대로 보여줄 수 있다. 판정 실패 시 마지막 값을 재사용하지 않고
  `gslb_target: null`을 그대로 반환, 화면은 "판정 중…"을 명시.
- **실제 장애물 — `GSLB_PUBLIC_URL`을 `https://`로 잘못 하드코딩** ⭐: `REGIONS_JSON` 반영 후
  두 리전 카드는 정상(초록)으로 떴는데 GSLB 배지만 "판정 중…"에서 안 넘어감. 사용자가 로컬
  맥북에서 `curl -I https://www.chaosarena.cloud`(443 포트 연결 자체 실패)와
  `curl -I http://www.chaosarena.cloud`(200 OK)를 나란히 확인해줘서, 사이트가 아직 TLS 없이
  평문 HTTP로만 서빙 중이라는 게 드러났다 — TLS는 `SETUP_GUIDE.md`의 미착수 항목에 그대로 남아
  있었는데, 이 기능을 설계할 때 "사이트는 당연히 HTTPS일 것"이라고 확인 없이 가정한 게 원인이었다.
  `app.py`의 `GSLB_PUBLIC_URL`을 `http://www.chaosarena.cloud`로 수정해 해결. 같은 잘못된 전제로
  적혀있던 `CONCEPTS.md` 22.3절의 "믹스드 콘텐츠라 막힌다" 설명도 사실관계에 맞게 다시 썼다
  (실제로는 CORS/timeout 일원화가 백엔드 프록시를 택한 진짜 이유).
- **새 환경변수 `REGIONS_JSON`**: KR1/KR2 양쪽에 완전히 동일한 값(두 리전의 공인 주소 목록)을
  심는다 — `APP_VERSION`/Jenkins `REGION`과 같은 "대칭 설정값 공유" 패턴. 오늘 이전까지 두 리전의
  앱은 서로의 존재를 전혀 몰랐는데(코드 조사로 확인), 이게 그걸 깨는 최초의 지점이다.
- **로컬 검증 완료**: `.venv/bin/python3 app.py`(LOCAL_MODE=true)로 `/infra`·`/api/regions` 목업
  응답 확인, 이어서 `LOCAL_MODE=false` + 가짜 `REGIONS_JSON`(상대 리전을 존재하지 않는 로컬 포트로
  지정)으로 실제 코드 경로까지 검증 — 자기 자신은 호출 없이 reachable, 상대는 실제 요청 실패 시
  `reachable:false`로 정확히 표시되는 것, GSLB 확인 자체가 실패하면(이 개발 환경은 외부 인터넷
  접근이 막혀 있어 실제로 실패함) `gslb_target: null`로 우아하게 저하하는 것까지 확인.
- **아직 안 끝난 것**: `REGIONS_JSON`은 이 레포가 아니라 별도 `ChaosArena-manifests` 레포의
  `argocd-managed-kr1/deployment.yaml`·`argocd-managed-kr2/deployment.yaml`에 최초 1회 수동으로
  추가해야 하는 값이라, 실제 KR1/KR2 라이브 클러스터에서의 최종 검증(리전 하나를 진짜로 내려서
  카드가 빨갛게 바뀌고 GSLB 배지가 뒤따라 넘어가는 것)은 사용자가 그 값을 반영한 뒤 진행 예정.
- **변경 파일**: `app.py`(`REGIONS_JSON`/`GSLB_PUBLIC_URL` 설정, `_refresh_regions_loop` 백그라운드
  스레드, `GET /api/regions`, `GET /infra`), `templates/infra.html`(신규), `templates/base.html`
  (사이드바/모바일 내비게이션에 "인프라 지도" 탭 추가).

### 4.36 chaos-demo 애플리케이션 트리 — 권한 확장 없이 ArgoCD식 트리 복원 ⭐

- **배경**: `/infra`의 리전 카드는 리전 단위 상태(초록/빨강)만 보여줘서, "파드를 스케일하면 구조가
  디테일하게 펼쳐지는" ArgoCD의 Application Details Tree 같은 그림을 원한다는 요청이 들어왔다.
- **핵심 결정 — RBAC를 늘리지 않았다**: `Deployment → ReplicaSet → Pod` 트리를 그리려면 얼핏
  Deployment/ReplicaSet 조회 권한이 필요해 보이지만, 대시보드 SA(`k8s/rbac.yaml`)에는 그 권한을
  주지 않고 **이미 있는 파드 조회 권한만으로 트리를 역복원**했다. 각 파드의 `ownerReferences`(소속
  ReplicaSet)와 `pod-template-hash` 라벨로 RS 그룹을 재구성하고, desired 수·CPU%만 HPA(get 권한
  기존 보유)에서 가져온다. 옛 RS는 파드가 0개라 자연히 안 잡힌다. → 최소 권한 원칙(21절)을 시각화
  기능에서도 유지.
- **스코프 → 두 리전 통합(후속)**: 처음엔 앱이 자기 클러스터 파드만 kube로 조회 가능(상대 리전
  kubeconfig도 최소 권한상 미부여)이라 **서빙 리전 하나**만 그렸는데, 그러면 접속 경로(GSLB→KR1
  vs KR2 직접 IP)에 따라 트리가 KR1↔KR2로 달라지는 문제가 있었다. **해결**: 상대 리전 트리는
  kube가 아니라 **그쪽의 `/api/topology`를 HTTP로 가져와** 합친다 — 리전 카드가 `/health`를
  확인하던 것과 같은 서버사이드 프록시 방식(`_fetch_region_topology`). 각 리전의 `/api/topology`는
  자기 자신만 담은 1차 응답이라 재귀 없음, 백그라운드 스레드가 5초마다 미리 모아 캐시(요청
  스레드에서 네트워크 I/O 안 함), 프런트는 통합 엔드포인트 `/api/topology/all`만 읽는다. →
  크로스리전 kube 크레덴셜을 여전히 안 들고도 한 화면에 KR1·KR2 트리 모두 표시, 죽은 리전은 그
  블록만 "응답 없음"으로 저하.
- **로컬 검증 완료(실측)**: `LOCAL_MODE`에서 `/chaos/cpu` 토글로 목업 HPA를 3→6으로 올려
  `/api/topology/all`이 KR1(self, 6개)·KR2(원격, 3개) 두 리전을 모두 반환하고, 헤드리스 Chrome
  스크린샷으로 두 리전 트리가 각각 `deploy(CPU%, HPA 3→6) → rs → pod×N`으로 세로로 쌓여 펼쳐지는
  것, 현재 리전 블록이 파란 테두리로 구분되는 것, 새 파드에만 1회성 fade-in이 적용되는 것 확인.
- **최종 형태 — 단일 통합 흐름도**: 처음엔 (리전 카드 목록) + (별도 트리 패널)로 나뉘어 있었는데,
  "여러 개가 아니라 전체 인프라가 하나로 보이게" 요청에 따라 `/infra`를 **하나의 '전체 인프라
  흐름' 패널**로 재구성했다: `GSLB → 리전(판교/평촌) → Ingress → chaos-demo(Deployment→
  ReplicaSet→Pod) → Redis·모니터링·CI/CD`를 한 다이어그램에 담고, 판교·평촌을 세로 레인으로 쌓아
  둘 다 같은 디테일로 표현. 트래픽 받는 리전은 파란 테두리로 강조, 죽은 리전 레인은 빨갛게 저하.
- **변경 파일**: `app.py`(`build_topology`/`build_mock_topology`/`build_mock_topology_all`/
  `format_pod_age`/`container_ready_str` 헬퍼, `_fetch_region_topology`/`_self_topology`/
  `_build_topology_snapshot` + `_refresh_regions_loop`에 토폴로지 캐시 추가, `GET /api/topology`(1차)
  · `GET /api/topology/all`(통합)), `templates/infra.html`(GSLB+두 리전 레인을 하나로 합친 흐름도 —
  Ingress→deploy→rs→pod 서비스 경로 + Redis/모니터링/CI·CD 부속 노드 + 커넥터 CSS + 폴링 렌더러).
- **라이브 검증 대기**: 실배포 후 실제 HPA 스케일아웃(부하 → 3→6) 시 두 리전 트리가 함께 뜨고
  한쪽 리전을 내리면 그 블록만 "응답 없음"으로 바뀌는 것 확인 예정.

### 4.37 /infra UI 개편 — 파이프라인 강조형 재설계 + CI/CD 상태 실제 헬스체크로 전환 ⭐

- **UI 방향 재설계**: 사용자 피드백("전보다 낫지만 더 개선할 방향?")에 따라 세 가지 방향(상태
  요약 우선 / 파이프라인 강조형 / 미니멀 정돈)을 ASCII 미리보기로 제시하고 **파이프라인
  강조형**으로 확정. `Ingress(작은 필) → Deploy(허브, 가장 큰 카드 — 파드스케일/CPU 진행률
  바 포함) → RS(컴팩트 필) → Pod(작고 흐린 잎, 접미사+age만 표시)`로 세로 연결. CPU%가 HPA
  목표의 1.6배를 넘으면 막대가 초록→빨강으로 바뀌어 상태가 색으로 즉시 읽힌다. 파드 전체
  정보(이름/노드/phase)는 title 툴팁으로 이동.
- **계기 — Redis/모니터링/Jenkins/ArgoCD 줄이 실제로는 장식이었다**: 재배포 확인 중 실제로
  Jenkins 파드가 죽어있었는데도 이 줄은 계속 멀쩡하게 보였다(정적 텍스트였을 뿐 헬스체크가
  아니었음). 이 대시보드가 "그럴듯한 그림"이 아니라 실제 장애 탐지 도구가 되도록, 4개 항목
  모두 실제 헬스체크로 바꿨다: Redis는 기존 `get_redis_client()`로 `PING`, 모니터링은 기존
  `PROMETHEUS_URL`에 `/-/healthy` 호출, Jenkins/ArgoCD는 클러스터 내부 Service URL(신규
  `JENKINS_HEALTH_URL`/`ARGOCD_HEALTH_URL` env)로 HTTP 응답 여부만 확인(특정 상태 코드를
  요구하지 않음 — 리다이렉트/로그인 페이지든 "연결 자체가 되는지"가 핵심).
- **"미설정"과 "죽음"을 구분**: 위 4개 env 중 하나가 비어있으면(아직 매니페스트에 안 넣은
  경우) 그 항목은 `null`(미설정, 회색 그대로)이지, `false`(빨강)로 단정하지 않는다 — GSLB
  대상을 추측하지 않고 실제 확인될 때까지 `null`로 두던 것과 같은 원칙(22.5절).
- **죽으면 흐려지는 게 아니라 튀어나온다**: 기존엔 리전 전체가 죽었을 때만 부속 컴포넌트 줄
  전체가 흐려졌는데, 이번엔 리전은 멀쩡한데 서비스 하나만 죽는 경우(정확히 이번에 겪은
  Jenkins 사고)를 위해 그 칩만 빨간 배경/테두리로 **더 눈에 띄게** 만들었다 — "죽은 걸 더
  흐리게" 만드는 건 잘못된 신호라는 판단.
- **자기 리전은 로컬, 상대 리전은 HTTP 프록시**: 토폴로지(4.36절)와 완전히 같은 구조 —
  `GET /api/aux-health`(1차, 자기 자신만) / `GET /api/aux-health/all`(통합, 백그라운드
  스레드가 5초마다 상대 리전 것까지 미리 가져다 캐시). 크로스리전 크레덴셜 추가 없음.
- **로컬 검증(실측)**: LOCAL_MODE 목업(4개 전부 초록) 확인 후, 스크래치 사본에서 `jenkins:
  False, argocd: None`으로 강제해 헤드리스 Chrome 스크린샷 — Jenkins 칩만 빨갛게 튀고
  ArgoCD는 회색 그대로(미설정)인 것을 확인.
- **변경 파일**: `app.py`(`JENKINS_HEALTH_URL`/`ARGOCD_HEALTH_URL` 설정, `_check_http_reachable`/
  `_check_redis_health`/`_check_prometheus_health`/`_self_aux_health`/`_fetch_region_aux_health`/
  `_build_aux_snapshot` + `_refresh_regions_loop`에 aux 캐시 추가, `build_mock_aux_health_all`,
  `GET /api/aux-health`·`GET /api/aux-health/all`), `templates/infra.html`(파이프라인 세로
  레이아웃 CSS 전면 개편, `auxChip`/`auxRow` 실헬스체크 렌더러).
- **라이브 최종 검증 완료**: `JENKINS_HEALTH_URL`/`ARGOCD_HEALTH_URL`을 두 리전 매니페스트에
  반영하고, ArgoCD TLS 검증 문제(아래 트러블슈팅)까지 고친 뒤 KR1·KR2 양쪽 다 Redis·모니터링·
  Jenkins·ArgoCD 4개 칩 전부 초록으로 확인. 부수적으로 **KR1의 kube-prometheus-stack이 설치는
  돼 있었지만 `PROMETHEUS_URL`이 매니페스트에 안 심어져 있던 것**도 이번에 같이 발견해 추가
  (Jenkins/ArgoCD와 같은 클래스의 "인프라는 있는데 앱이 모르는" 문제). 검증 중 KR1이 롤링
  업데이트 중이라 ReplicaSet 2개가 잠깐 공존하는 순간도 파이프라인 트리가 의도대로 정확히
  표현하는 것을 확인.
- **실배포 트러블슈팅 — ArgoCD 칩만 계속 빨갛게 뜸**: 매니페스트 반영(수동 편집 중 git 히스토리
  분기로 `push` 거부 → `pull --no-rebase` → 충돌 마커 수동 정리 → merge 커밋 후 재push, 앞서
  겪은 "여러 Jenkins 빌드가 같은 파일을 동시에 커밋"과 같은 종류의 흔한 git 충돌이었을 뿐 YAML
  문법 문제는 아니었음) 후에도 Redis·모니터링·Jenkins는 초록인데 **ArgoCD만 KR1·KR2 양쪽 다
  빨갛게** 떴다. 원인: `argocd-server`는 80번(http)으로 들어온 요청을 자체 서명 인증서를 쓰는
  443번(https)으로 리다이렉트하는데, `requests`가 기본값(`verify=True`)으로 그 인증서를
  검증하려다 `SSLCertVerificationError`로 실패 — 예전 GitHub 웹훅에서 겪은 것과 같은 자체 서명
  인증서 문제(4.34절)였다. 로컬에서 자체 서명 인증서로 HTTPS 서버를 띄워 재현: `verify=True`는
  실패, `verify=False`는 성공을 직접 확인 후 `_check_http_reachable`에 `verify=False` 추가로
  수정(신뢰 여부가 아니라 "응답이 오는지"만 보는 헬스체크이므로 안전). `urllib3.disable_warnings`로
  매 5초 반복되는 `InsecureRequestWarning` 로그도 같이 정리.

### 트러블슈팅에서 얻은 원칙
1. **에러 메시지를 액면 그대로 믿지 말 것** — "Could not find user"는 실제로 엔드포인트 버전 문제였다. 일부러 틀린 입력으로 메시지가 변하는지 확인하는 이분법이 원인 격리에 효과적이었다.
2. **추측 대신 실제 API 조회** — 이미지명/AZ명/VPC ID 등은 전부 직접 조회해 확정.
3. **플랫폼별 모델 차이 검증** — "AWS는 이러니 NHN도 그럴 것"이라는 가정(인터넷 게이트웨이 outbound)이 틀렸다. 공식 문서로 확인.
4. **프로바이더의 한계를 아키텍처로 우회** — 게이트웨이/NAT 생성 리소스 부재를 "기존 VPC 재사용"으로 해결.
5. **레이어를 하나씩 벗겨가며 범위를 좁힐 것** — 외부 접속 실패를 클라우드 방화벽→NodePort→서비스→파드 IP 순으로 우회 테스트하며, "어디까지는 되고 어디부터 안 되는지"로 원인을 좁혔다 (4.8).

---

## 5. 현재 진행 상황

> **계획 변경**: 원래 KR1(판교)+KR2(평촌) 동시 구축 예정이었으나, KR1 리전 RAM 쿼터가 부족해
> **KR2(평촌)만 먼저 구축**하고, 판교 쿼터 확보 후 멀티클러스터로 확장하는 방향으로 조정.
> (`terraform/main.tf`의 `cluster_kr1` 모듈은 일시 주석 처리, 값은 보존)

- [x] 앱: 멀티 페이지 분리 + 시각화/디자인 시스템
- [x] Git/GitHub 저장소 구성 (`infra/k8s-setup` 브랜치에서 인프라 작업)
- [x] Terraform 멀티 리전 인프라 코드 (모듈화, v3 인증, 기존 VPC 재사용, 포트 기반 배치)
- [x] **KR2(평촌) 인스턴스 4대** 프로비저닝 — `ChaosArena-master-kr2`, `worker1~3-kr2`
- [x] **KR2 kubeadm 클러스터 구축** — Calico CNI, 4대 전부 Ready
- [x] **앱 배포(KR2)** — NodePort(`:30080`) + 마스터 공인IP로 노출, 접속 확인 완료
- [x] **핵심 데모 검증 완료** ⭐ — 브라우저에서 Chaos 버튼으로 실제 파드 삭제 → 진짜 kubeadm 클러스터가 새 파드를 자동 재생성하는 것까지 end-to-end 확인. 이 프로젝트의 본래 목표(Self-Healing 시각화)가 로컬 목업이 아닌 실제 자체 구축 클러스터 위에서 동작함을 증명.
- [x] **대시보드 운영 콘솔 리디자인**(`chaos-arena:v3`) — 사이드바+멀티컬럼, 노드별 파드 토폴로지, Chart.js 차트 (2.2절)
- [x] **NCR(비공개 레지스트리) 전환** — Docker Hub → NHN NCR(`chaosarena-registry`), `ncr-secret` 인증. content-trust 정책 이슈(412) 해결 (4.10절)
- [x] **KR1(판교) 최소 스펙(1마스터+1워커) 테스트 클러스터 구축 + 앱 배포** — RAM 쿼터가 빠듯해 정식 4c16 대신 `m2.c2m4`(2vCPU/4GB)로 우선 검증. `k8s/deployment-kr1-test.yaml`(replicas=1)로 별도 운용
- [x] **Slack 알림 연동** — Incoming Webhook + k8s Secret(`slack-webhook`). 앱 코드(`send_slack_message`)는 이미 준비돼 있었고 Webhook 등록만 하면 즉시 동작
- [x] **Prometheus + Grafana 메트릭 스택** (KR2) — kube-prometheus-stack Helm 설치, `ServiceMonitor`로 앱의 `/metrics`(`app_requests_total`/`app_errors_total`/`app_response_time_seconds`) 연동, Grafana 대시보드(`ChaosArena App Metrics`) 구성
- [x] **자체 대시보드 ↔ Prometheus 직접 연동** — Grafana를 iframe으로 끼워넣는 대신, Flask 앱이 Prometheus HTTP API(`/api/v1/query`)를 직접 호출해 `sum(rate(...))`로 파드 전체 합산 지표를 계산하는 `/api/metrics/cluster`를 추가. 기존 `/api/status`(응답한 파드 1대의 로컬 값이라 폴링마다 들쭉날쭉)와 대비되는 "클러스터 전체 기준" 지표를 같은 디자인 시스템 안에서 보여줌. `PROMETHEUS_URL` 미설정 시(KR1 등) 자동으로 "미연동" 표시로 우아하게 저하
- [x] **KR1 Terraform state drift 원인 규명 + 수정** ⭐ — `image_id` + boot-from-volume 조합이 매 plan마다
  거짓 diff를 만들고, apply 시 운영 중인 서버를 `servers.Rebuild()`로 통째로 재설치할 뻔한 게 진짜 원인이었다.
  프로바이더 소스 코드까지 확인해 근본 원인을 확정하고 `compute.tf`에서 중복 `image_id` 지정을 제거해 해결.
  수정 후 `terraform plan` 결과 `2 to add, 0 to change, 0 to destroy`만 남아 **일반 apply가 다시 안전해짐**
  (남은 "2 to add"는 KR1 RAM 쿼터 문제로 아래 항목이 해결되기 전까진 그대로 둘 것) (4.17절)
- [x] **KR1(판교) RAM 쿼터 확보 → 정식 재구축 + 원래 설계대로 Active 전환** ⭐ — `r2.c4m16`·워커 3대로
  재구축(기존 마스터/워커는 in-place resize라 클러스터 상태 보존, 신규 워커 2대만 조인).
  `deployment-kr1-test.yaml`(replicas=1) → `deployment.yaml`(replicas=3, APP_VERSION=kr1) 전환.
  KR1 전용 Redis 신규 설치 + 재시작 생존 검증. GSLB 우선순위를 `kr1-active`=1로 원복하고
  failover(kr1→kr2)/failback(kr2→kr1) 양방향 재검증 완료 (4.33절)
- [x] **DNS Plus GSLB failover 구성 + 검증 완료** ⭐ — Zone 생성 → 가비아 네임서버를 NHN으로 위임 → Pool(`kr1-active` 우선순위1/`kr2-standby` 우선순위2) + 헬스체크(`/health`) → GSLB(FAILOVER, TTL 30초) 생성 후 Pool 연결 → `www` CNAME을 GSLB 도메인으로 연결. `scripts/06`으로 KR1 파드를 강제로 내려 실제 failover(약 80초 소요, `kr1-test`→`kr2`)와 복구 후 failback을 둘 다 실측 검증 (4.15절)
- [x] **GSLB 우선순위 재조정** — 풀 스펙 클러스터인 KR2를 우선순위 1(Active)로, 최소 스펙 테스트
  클러스터인 KR1을 우선순위 2(Standby)로 변경. `dig +short www.chaosarena.cloud`가 KR2 공인IP를
  가리키는 것으로 실제 전환 확인 (4.24절)
- [x] **AlertManager 알림 규칙(파드 다운/CPU/에러율) + Slack 라우팅** — `PrometheusRule`(release 라벨 필요, 4.11 교훈 적용) + Alertmanager Slack 연동. 3단 실패(helm --reuse-values 함정 / Secret 네임스페이스 불일치 / null receiver 삭제로 인한 reconcile 전체 실패)를 로그 기반으로 하나씩 좁혀 해결 (4.12절). `ChaosDemoHighCPU` 알림이 실제로 파드명까지 템플릿 치환되어 Slack 도착 확인
- [x] **Jenkins CI/CD** ⭐ — KR2 클러스터 내부(Pod)에 Helm으로 설치(hostPath PV로 영속화), `jenkins-deployer` RBAC,
  GitHub Webhook + Pipeline Job(`infra/k8s-setup` 브랜치), Jenkinsfile(Kaniko 빌드+push → cosign 서명 → kubectl
  배포)까지 전부 구성해 **push 한 번으로 빌드→서명→KR2 배포가 완전 자동으로 도는 것을 실제로 검증**했다.
  4가지 장애물(Bitnami 태그 소실/non-root 셸 실행 실패/cosign 비밀번호 오타/RBAC watch 누락)을 로그 기반으로
  하나씩 해결 (4.14절). 이미지 태그를 `jenkins-${BUILD_NUMBER}`로 매 빌드 고유하게 부여해 어떤 빌드가
  배포됐는지 추적 가능. 1단계로 **KR2 전용**(KR1 확장은 3.5절 트레이드오프 참고).
- [x] **자동배포 시각화** — Jenkinsfile Deploy 스테이지가 `kubectl set env`로 `BUILD_NUMBER`/`GIT_COMMIT`을
  Deployment에 심어주고, `/api/status`가 이를 노출. 프론트가 5초 폴링으로 빌드 번호 변경을 감지해 사이드바
  배지 갱신 + "🚀 새 버전이 배포되었습니다" 토스트(4초)를 모든 페이지 공통으로 표시. Playwright로 빌드
  번호 전환 시나리오를 재현해 배지/토스트 타이밍까지 실제 검증 (docs/CONCEPTS.md 11.6절). 처음 시도했던
  "화면 전체 틴트+대형 배너" 효과는 실제로 보고 나서 반려되어 코드에서 제거하고, 아래 CI/CD 탭으로 대체.
- [x] **CI/CD 전용 탭 + "배포 랭크" 게임화** ⭐ — 파드 복구를 채점하던 S/A/B/C 랭크 시스템을 Jenkins
  파이프라인 소요시간(Build&Push→Sign→Deploy)에도 그대로 적용. `Jenkinsfile`이 Checkout~Deploy 직전까지
  걸린 시간을 재서 `DEPLOY_DURATION_SECONDS`로 앱에 전달하면, `app.py`가 `compute_deploy_rank()`로
  채점해 `/api/status`에 노출하고, 새로 만든 `/cicd`(`templates/cicd.html`) 탭이 그 랭크를 큰 글자 +
  게이지 + 컨페티/사운드(파드 복구 랭크 연출 재사용)로 보여준다. 연속 S랭크 배포 시 콤보 표시도 동일하게
  적용. 화면 전체가 아니라 **이 탭 안에서만** 반응하게 해서, 다른 페이지의 절제된 톤은 그대로 유지.
  로컬(Playwright)에서 빌드 7→8(C랭크)→9(S)→10(S, 2연속 콤보) 전환 시나리오를 재현해 랭크/게이지/콤보
  갱신과 리빌 연출까지 스크린샷으로 검증 (docs/CONCEPTS.md 11.7절). 다회차 배포 이력("퀘스트 로그")은
  이 앱 파드 자체가 배포마다 재시작되는 구조상 영속 저장소(Redis/DB) 없이는 못 쌓아서 의도적으로 보류.
  **실제 KR2 프로덕션에서도 검증 완료** — push 도중 Jenkins가 CrashLoopBackOff로 죽어있던 걸 발견해
  복구하고(4.16절) build #11을 수동 트리거, 실제 파이프라인 소요시간 42초로 S랭크가 뜨는 것까지 확인.
- [x] **NCR 이미지 서명(cosign) 도입 + content-trust 정책 재활성화** — 3중 장애물(cosign 최신버전 호환성/attestation 매니페스트/스테일 이미지 캐시)을 순서대로 해결, 서명된 이미지가 정책 재활성화 상태에서 정상 pull됨을 실제로 검증 (4.13절)
- [x] **HPA(오토스케일링) 도입** ⭐ — `k8s/hpa.yaml`(minReplicas 3/maxReplicas 6/CPU 목표 50%)로 KR2
  `chaos-demo`에 적용. 강제였던 podAntiAffinity를 preferred로 완화해 "노드당 파드 1개" 규칙이 스케일
  아웃을 막던 문제를 해결하고, 기존 "CPU 부하" 버튼을 그대로 트리거로 재사용해 실제 3→6 스케일 아웃 →
  5분 안정화 창 후 6→3 스케일 다운까지 전체 라이프사이클 실측 검증 (4.18절)
- [x] **Ingress 도입** ⭐ — 1단계(병렬): ingress-nginx를 KR2에 새 NodePort(30081/30444)로 설치해
  라우팅만 우선 검증(4.19절). 2단계(실제 전환): 포트 번호를 그대로 재사용해 `chaos-demo-nodeport`를
  ClusterIP로 바꾸고 ingress-nginx가 30080을 대신 갖게 해서 **GSLB 설정을 하나도 안 건드리고** KR2의
  실제 입구를 Ingress로 전환, host를 catch-all로 바꿔 헬스체크 회귀도 방지(4.20절). 3단계(포트 번호
  제거): hostPort+마스터 노드 스케줄링으로 진짜 80번 포트를 열어 **`www.chaosarena.cloud`가 포트 번호
  없이 접속되는 것까지 KR1/KR2 양쪽 확인 완료**(4.21절). TLS는 다음 단계로 보류.
- [x] **ArgoCD(GitOps) 도입** ⭐ — Jenkins는 빌드+서명(CI)까지만, 배포(CD)는 별도 `ChaosArena-manifests`
  레포를 ArgoCD가 pull 방식으로 감시/반영. Jenkins의 클러스터 배포 권한(`jenkins-deployer`)을
  완전히 제거하고 Git 쓰기 권한만 갖게 함. 배포 랭크 기능(BUILD_NUMBER 등)도 GitOps 원칙에 맞게
  Git 선언 상태로 전환 (4.22절). **Jenkins→Git→ArgoCD→클러스터 전체 파이프라인 end-to-end 실측
  검증 완료**(build #17 SUCCESS, ArgoCD Synced/Healthy, 배포된 이미지 태그 일치 확인). 검증 중 겪은
  에이전트 TCP 포트 바인딩 레이스 + K8s Service 고정 포트 불일치 트러블슈팅은 4.23절 참고
- [x] **Jenkins 자동 롤백** ⭐ — 배포 후 `/api/status`의 `build_number`로 새 버전 반영을 확인하고, 약
  2분 내에 안 바뀌면 이전 버전으로 되돌리는 커밋을 자동 push. 새 크레덴셜 없이 클러스터 내부 Service
  DNS만으로 확인(4.25절). 실제로 헬스체크를 깨서 롤백 커밋이 push되고 빌드가 FAILURE로 표시되는 것까지
  라이브 검증 완료 — 다만 "그 이전 버전 자체가 이미 나쁜 상태면 복구 안 됨"이라는 단일 단계 롤백의
  한계도 함께 발견(4.25절 트러블슈팅)
- [x] **CI/CD 탭 배포 히스토리 타임라인** — 배포 성공/롤백 이력을 ConfigMap에 기록해 화면에 최신순으로
  보여줌(4.26절). 실제 KR2 클러스터에 RBAC/ConfigMap 반영 + `/health`를 일부러 깨는 라이브 롤백
  테스트를 여러 차례 반복해 성공/롤백 이벤트가 정확히 기록·표시되는 것까지 검증 완료
- [x] **CI/CD 탭 UX 정합성 수정** — 파이프라인 단계 패널이 실제 GitOps 흐름과 안 맞아 통째로 제거하고,
  롤백 시에도 "완벽한 배포!" 캡션이 뜨던 모순을 수정(4.27절). 대시보드에 배포 트리거 버튼을 추가하는
  안은 검토 후 보류(권한/남용 리스크)
- [x] **대시보드 UI 일관성 개선** — footer 태그라인 제거, 색상 accent 규칙 통일, 페이지 간 크로스링크로
  빈 여백 채우기, 유사한 페이지끼리 그리드 구조 통일(4.30절). Jenkins 파드 CrashLoopBackOff 재발(4.28절)
  및 GitHub 웹훅 배포 실패(4.29절)도 이 기간에 겪고 해결
- [x] **기록실(리더보드) Redis 도입** ⭐ — 파드 재시작(모든 CI/CD 자동 배포 포함)마다 리더보드가
  지워지고 replica 3개끼리 값이 다르던 문제를 실제 화면에서 목격 → Redis(hostPath PV, Jenkins와
  다른 워커 노드) 도입으로 해결. 로컬 5가지 시나리오 + KR2 실제 클러스터(파드 삭제 후 데이터 보존,
  실제 CI/CD 재배포 후 리더보드 유지)까지 전부 실측 검증 완료(4.31절)
- [x] **대시보드 오토스케일링(HPA) 패널** — 최소 권한(HPA 1개 `get`)으로 현재/목표 레플리카, min/max,
  CPU 사용률을 `/monitor`에서 kubectl 없이 육안 확인 가능(4.32절)
- [x] **컨트롤 플레인 이중화** ⭐ — KR2 자체가 오래 죽으면 KR1이 멀쩡해도 배포를 못 한다는 SPOF를
  없애기 위해 Jenkins+ArgoCD+kube-prometheus-stack을 KR1에도 통째로 복제(`docs/CONCEPTS.md`
  21.6~21.7절, `docs/SETUP_GUIDE.md` Part 11). JCasC REGION 전파 실수, 동시 push 레이스,
  PAT 값 불일치, ArgoCD 웹훅 TLS 에러까지 4가지 장애물을 실제로 겪고 해결(4.34절). **최종적으로
  KR2 Jenkins를 완전히 내려놓은 상태에서 KR1이 혼자 빌드→서명→배포까지 끝내는 것을 실측 검증**
- [x] **인프라 지도(/infra) 탭** — 양쪽 리전 상태 + GSLB 현재 트래픽 대상을 화면으로 관찰
  (`docs/CONCEPTS.md` 22절, 4.35절). 코드/로컬 검증 완료, `ChaosArena-manifests`에
  `REGIONS_JSON` 반영 후 라이브 최종 검증 대기 중
- [ ] 마무리: main 병합, README, requirements 버전 고정

---

## 6. 리포지토리 구조

```
ChaosArena/
├── app.py                  # Flask 앱 (게임 로직 + K8s API + 대시보드 API)
├── templates/              # base/game/monitor/records/cicd (Jinja2 상속)
├── Dockerfile
├── requirements.txt
├── k8s/                    # rbac, deployment, hpa, ingress(-nginx), service(lb/nodeport), metallb,
│                           # argocd-application(-kr1), jenkins-values(-kr1)/-pv(-kr1),
│                           # alertmanager-slack-values(-kr1), secret 예시 — "처음 배우는 템플릿"이며,
│                           # 실제 배포 상태의 source of truth는 별도 ChaosArena-manifests 레포(4.22절).
│                           # KR1/KR2 리전별 파일은 -kr1 접미사로 구분(4.34절)
├── scripts/                # 01~05 클러스터 구축 + 06 GSLB failover 테스트 + 07 metrics-server
├── terraform/
│   ├── providers.tf        # kr1/kr2 provider (Keystone v3)
│   ├── main.tf             # 모듈 2회 호출
│   ├── modules/chaos-cluster/  # VPC 재사용 + 포트 + 인스턴스 + 마스터 FIP
│   └── terraform.tfvars.example
└── docs/
    ├── PROJECT_LOG.md      # (이 문서) 의사결정 + 트러블슈팅 기록
    ├── CONCEPTS.md         # 초보자 관점 배경지식 노트 (Jenkins, PV/hostPath, RBAC 등)
    └── SETUP_GUIDE.md      # 처음부터 직접 따라 하는 실행 가이드 (명령어 + 순서 + 이유)
```

---

## 7. 참고 출처 (Provenance)

이 프로젝트의 스크립트/매니페스트/IaC 코드는 **공식 문서의 표준 절차를 이 환경에 맞게
조합·조정**해 작성했다. 외부 저장소를 복제한 것이 아니며, 아래 공식 소스를 근거로 한다.
작성·검증 과정에서 웹 검색과 각 프로젝트의 공식 GitHub 리소스를 직접 조회해 버전과
스키마를 확인했다.

| 산출물 | 근거 공식 출처 |
|---|---|
| `scripts/01-node-common-setup.sh` (swap/containerd/kubeadm) | [Kubernetes 공식 kubeadm 설치 문서](https://kubernetes.io/docs/setup/production-environment/tools/kubeadm/install-kubeadm/), [pkgs.k8s.io 저장소](https://pkgs.k8s.io) |
| `scripts/02-master-init.sh` (kubeadm init) | [kubeadm 클러스터 생성 문서](https://kubernetes.io/docs/setup/production-environment/tools/kubeadm/create-cluster-kubeadm/) |
| `scripts/03-install-calico.sh` (Calico CNI) | [Calico(Tigera) 공식 설치 매니페스트](https://docs.tigera.io/calico/latest/getting-started/kubernetes/) |
| `scripts/05-install-metallb.sh` (MetalLB) | [MetalLB 공식 매니페스트](https://metallb.universe.tf/installation/) |
| `terraform/**` (NHN Cloud 리소스) | [nhn-cloud/terraform-provider-nhncloud 공식 문서](https://registry.terraform.io/providers/nhn-cloud/nhncloud/latest/docs) |
| GSLB / DNS failover | [NHN Cloud DNS Plus 공식 문서](https://docs.nhncloud.com/ko/Network/DNS%20Plus/ko/overview/) |
| 인터넷 게이트웨이 outbound 동작 | [NHN Cloud Internet Gateway 개요](https://docs.nhncloud.com/ko/Network/Internet%20Gateway/ko/overview/) |

> **포트폴리오 노트**: 이 프로젝트의 핵심 가치는 스크립트를 손으로 타이핑했는지가 아니라,
> "왜 이렇게 구성했는가(4장 의사결정)"와 "환경 특수적 문제를 어떻게 진단·해결했는가
> (5장 트러블슈팅)"를 설명할 수 있다는 점에 있다. 표준 절차는 공식 문서를 근거로 하되,
> Keystone v3 인증·인터넷 게이트웨이 제약·RAM 쿼터·Pod CIDR 충돌 등 이 환경에서만
> 발생한 문제는 직접 원인을 격리하고 해결했다.
