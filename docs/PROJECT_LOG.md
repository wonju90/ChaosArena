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
- [ ] KR1(판교) RAM 쿼터 확보 → `r2.c4m16`·워커 3대로 정식 재구축 → `deployment-kr1-test.yaml` → `deployment.yaml`(APP_VERSION=kr1) 전환
- [x] **DNS Plus GSLB failover 구성 + 검증 완료** ⭐ — Zone 생성 → 가비아 네임서버를 NHN으로 위임 → Pool(`kr1-active` 우선순위1/`kr2-standby` 우선순위2) + 헬스체크(`/health`) → GSLB(FAILOVER, TTL 30초) 생성 후 Pool 연결 → `www` CNAME을 GSLB 도메인으로 연결. `scripts/06`으로 KR1 파드를 강제로 내려 실제 failover(약 80초 소요, `kr1-test`→`kr2`)와 복구 후 failback을 둘 다 실측 검증 (4.15절)
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
- [ ] 마무리: main 병합, README, requirements 버전 고정

---

## 6. 리포지토리 구조

```
ChaosArena/
├── app.py                  # Flask 앱 (게임 로직 + K8s API + 대시보드 API)
├── templates/              # base/game/monitor/records/cicd (Jinja2 상속)
├── Dockerfile
├── requirements.txt
├── k8s/                    # rbac, deployment, service(lb/nodeport), metallb, secret 예시
├── scripts/                # 01~05 클러스터 구축 + 06 GSLB failover 테스트
├── terraform/
│   ├── providers.tf        # kr1/kr2 provider (Keystone v3)
│   ├── main.tf             # 모듈 2회 호출
│   ├── modules/chaos-cluster/  # VPC 재사용 + 포트 + 인스턴스 + 마스터 FIP
│   └── terraform.tfvars.example
└── docs/
    ├── PROJECT_LOG.md      # (이 문서) 의사결정 + 트러블슈팅 기록
    └── CONCEPTS.md         # 초보자 관점 배경지식 노트 (Jenkins, PV/hostPath, RBAC 등)
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
