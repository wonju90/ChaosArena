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
| 프론트 | Vanilla JS (폴링 기반 실시간 대시보드), SVG 차트 |
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

### 2.2 디자인 시스템 & 시각화
- 재사용 `stat-tile` 카드, 그라디언트 배경, 페이드인 애니메이션
- SVG 스파크라인(응답시간·에러율 추이), conic-gradient 도넛 게이지, 랭크 구간 진행바
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

### 트러블슈팅에서 얻은 원칙
1. **에러 메시지를 액면 그대로 믿지 말 것** — "Could not find user"는 실제로 엔드포인트 버전 문제였다. 일부러 틀린 입력으로 메시지가 변하는지 확인하는 이분법이 원인 격리에 효과적이었다.
2. **추측 대신 실제 API 조회** — 이미지명/AZ명/VPC ID 등은 전부 직접 조회해 확정.
3. **플랫폼별 모델 차이 검증** — "AWS는 이러니 NHN도 그럴 것"이라는 가정(인터넷 게이트웨이 outbound)이 틀렸다. 공식 문서로 확인.
4. **프로바이더의 한계를 아키텍처로 우회** — 게이트웨이/NAT 생성 리소스 부재를 "기존 VPC 재사용"으로 해결.

---

## 5. 현재 진행 상황

- [x] 앱: 멀티 페이지 분리 + 시각화/디자인 시스템
- [x] Git/GitHub 저장소 구성 (`infra/k8s-setup` 브랜치에서 인프라 작업)
- [x] Terraform 멀티 리전 인프라 코드 (모듈화, v3 인증, 기존 VPC 재사용, 포트 기반 배치)
- [x] 인스턴스 8대(마스터1+워커3 × 2리전) 프로비저닝 — `ChaosArena-master-kr1` 등 네이밍
- [ ] kubeadm 클러스터 구축 (Calico CNI, MetalLB) — `scripts/01~05`
- [ ] NCR 이미지 빌드·푸시 + 앱 배포 (`k8s/`)
- [ ] DNS Plus GSLB failover 구성 + 검증 (`scripts/06`)
- [ ] 마무리: main 병합, README, requirements 버전 고정

---

## 6. 리포지토리 구조

```
ChaosArena/
├── app.py                  # Flask 앱 (게임 로직 + K8s API + 대시보드 API)
├── templates/              # base/game/monitor/records (Jinja2 상속)
├── Dockerfile
├── requirements.txt
├── k8s/                    # rbac, deployment, service(lb/nodeport), metallb, secret 예시
├── scripts/                # 01~05 클러스터 구축 + 06 GSLB failover 테스트
├── terraform/
│   ├── providers.tf        # kr1/kr2 provider (Keystone v3)
│   ├── main.tf             # 모듈 2회 호출
│   ├── modules/chaos-cluster/  # VPC 재사용 + 포트 + 인스턴스 + 마스터 FIP
│   └── terraform.tfvars.example
└── docs/PROJECT_LOG.md     # (이 문서)
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
