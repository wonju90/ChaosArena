# -*- coding: utf-8 -*-
"""
K8s 장애 대응 게임 대시보드 - Flask 앱

이 앱은 두 가지 역할을 동시에 한다.
1) 쿠버네티스 위에서 돌아가는 "워크로드"(장애가 나고 복구되는 대상 그 자체)
2) 그 워크로드의 상태를 보여주는 "대시보드"(사람이 보는 화면 + JSON API)

라벨 app=chaos-demo 를 붙인 파드 3개 이상이 이 앱으로 떠 있고,
그 중 하나(또는 여럿)를 Chaos 버튼으로 강제로 죽이면 쿠버네티스가 자동으로 새 파드를 만든다(Self-healing).
그 복구 시간을 재서 게임 점수(랭크/콤보/하이스코어)처럼 기록한다.

LOCAL_MODE:
  로컬(VS Code)에는 진짜 쿠버네티스 클러스터가 없어서, 곧바로 kubernetes 라이브러리를
  호출하면 에러가 난다. 그래서 환경변수 LOCAL_MODE로 "가짜 데이터 모드"와
  "진짜 클러스터 모드"를 나눠서, 로컬에서 먼저 화면/버튼 동작을 다 확인한 뒤
  클러스터에 배포할 때는 LOCAL_MODE=false로 바꿔서 실제 K8s API를 쓰게 한다.
"""

import os
import json
import time
import random
import threading
from collections import deque

from flask import Flask, jsonify, render_template, request
from kubernetes import client, config
from kubernetes.client.rest import ApiException
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
import redis
import requests

app = Flask(__name__)

# ---------------------------------------------------------------------------
# 1. 기본 설정값
# ---------------------------------------------------------------------------

# 환경변수로 로컬/클러스터 모드 구분
# (K8s 배포 시 Deployment YAML에서 LOCAL_MODE=false 로 지정 예정)
LOCAL_MODE = os.environ.get("LOCAL_MODE", "true").lower() == "true"

# 파드를 찾을 네임스페이스(namespace: 쿠버네티스 안에서 리소스를 나누는 논리적 구역)
NAMESPACE = os.environ.get("K8S_NAMESPACE", "default")

# 이 앱의 파드들만 골라내기 위한 라벨 셀렉터
LABEL_SELECTOR = "app=chaos-demo"

# 정상일 때 있어야 할 파드 개수 (Deployment의 replicas와 동일하게 맞춰야 함)
EXPECTED_REPLICAS = int(os.environ.get("EXPECTED_REPLICAS", "3"))

# 로컬 모드에서 "복구 완료"로 흉내낼 때까지 기다리는 시간(초)
LOCAL_MOCK_RECOVERY_SECONDS = 3

# Slack Webhook 주소. 코드에 직접 적지 않고 환경변수로만 받는다.
# (K8s에서는 Secret으로 등록해서 Deployment에 주입할 예정)
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")

# 배포 버전 표시용 (Deployment에서 env로 주입하면 화면에 "v3" 같은 값이 뜬다)
APP_VERSION = os.environ.get("APP_VERSION", "v1")

# 인프라 지도(/infra) 탭용 — "이 세상에 리전이 몇 개 있고, 각자 공인 주소가 뭔지"를 담은 정적
# 목록. KR1/KR2 양쪽 Deployment에 완전히 동일한 값을 심는다(APP_VERSION처럼 리전별로 다르게
# 만드는 게 아니라, 대칭 설정값 하나를 공유하는 패턴). 형식:
# '[{"id":"kr1","label":"판교","url":"http://<공인IP>"}, {"id":"kr2", ...}]'
# 비어있으면(로컬 개발) 인프라 지도는 목업 데이터로 저하한다.
try:
    REGIONS = json.loads(os.environ.get("REGIONS_JSON", "[]"))
except (json.JSONDecodeError, TypeError):
    REGIONS = []

# GSLB가 지금 실제로 어느 리전에 트래픽을 보내고 있는지는, 리전마다 다른 값이 아니라 이
# 사이트의 공개 도메인 하나를 실제로 호출해서 확인한다 - 리전별 env가 아니라 상수인 이유.
GSLB_PUBLIC_URL = "http://www.chaosarena.cloud"

# Jenkins CI/CD가 배포 직후 `kubectl set env`로 채워주는 값들 (수동 배포/로컬에서는 빈 값).
# 화면에서 "지금 몇 번째 빌드가 떠 있는지"를 보여주는 용도.
BUILD_NUMBER = os.environ.get("BUILD_NUMBER", "")
GIT_COMMIT = os.environ.get("GIT_COMMIT", "")

# 이번 빌드의 파이프라인 전체 소요시간(초). Jenkinsfile이 Checkout 시작~Deploy 직전까지 측정해서 넘겨준다.
# CI/CD 탭에서 이 값을 파드 복구 시간과 같은 방식으로 S/A/B/C 랭크로 보여주는 데 쓴다.
DEPLOY_DURATION_SECONDS = os.environ.get("DEPLOY_DURATION_SECONDS", "")

# 기록실(records) 데이터를 저장할 Redis 주소. 비어있으면(로컬 개발, Redis 미설치 클러스터)
# 아래 records dict(파드 메모리)로 조용히 저하한다 - PROMETHEUS_URL과 같은 패턴.
REDIS_HOST = os.environ.get("REDIS_HOST", "")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD", "")

# LOCAL_MODE에서 사용할 가짜 파드 목록 (이름, 노드) - EXPECTED_REPLICAS 기본값(3)과 개수를 맞춤
MOCK_PODS = [
    ("chaos-demo-mock-a", "local-node-1"),
    ("chaos-demo-mock-b", "local-node-2"),
    ("chaos-demo-mock-c", "local-node-3"),
]
MOCK_POD_NAMES = [name for name, _ in MOCK_PODS]

# 랭크 판정 기준(초). 복구 시간이 짧을수록 높은 랭크.
# LOCAL_MODE는 항상 3초에 완료되도록 되어 있어서 항상 S랭크가 뜬다(데모 시연용).
RANK_THRESHOLDS = [
    (5, "S"),
    (10, "A"),
    (20, "B"),
]
RANK_DEFAULT = "C"

# 배포 파이프라인(Kaniko 빌드+push → cosign 서명 → kubectl 배포)의 랭크 판정 기준(초).
# 실제 빌드 로그 몇 건을 보고 튜닝된 값이 아니라 Kaniko/cosign/kubectl 단계별 평소 소요시간을 감안한
# 추정치라, 실제 빌드 시간 분포를 몇 번 더 확인한 뒤 조정할 수 있다.
DEPLOY_RANK_THRESHOLDS = [
    (90, "S"),
    (150, "A"),
    (240, "B"),
]


# ---------------------------------------------------------------------------
# 2. 메모리 저장소 (일단 전역 변수로 시작, 나중에 MySQL/Redis 등으로 옮길 수 있음)
#
# 참고(전역변수 동시성): current_mission/chaos_state/metrics_state는 데모/포트폴리오
# 용도라 아래처럼 전역 변수로 저장해도 충분하다(각각 진행 중 미션/토글 상태/최근 100건
# 지표라 파드 재시작으로 잃어도 크게 문제되지 않는다). 다만 records(기록실 데이터)는
# 실제로 문제가 됐다 - CI/CD가 파드를 재배포할 때마다 초기화되고 replica 3개끼리도
# 서로 안 보이는 게 확인돼서, 아래 2.5절에서 Redis로 옮겼다. records dict 자체는
# Redis가 없거나 응답 안 할 때 저하할 대상으로 계속 남겨둔다.
# ---------------------------------------------------------------------------

# 오늘의 기록판 (Redis 미설정/장애 시 저하 대상 - 2.5절 get_redis_client() 참고)
records = {
    "total_incidents": 0,     # 총 장애 발생 횟수
    "recovery_times": [],     # 복구 시간 리스트 (초 단위, 평균 계산용)
    "best_time": None,        # 최고 기록 (가장 짧은 복구 시간)
    "top_times": [],          # 상위 3개 기록 (초 단위, 오름차순) - 하이스코어 보드용
    "current_combo": 0,       # 현재 연속 S랭크 달성 횟수
    "best_combo": 0,          # 역대 최고 콤보
}

# 현재 진행 중인 미션(파드 복구 대기) 상태
current_mission = {
    "active": False,               # 미션 진행 중 여부
    "target_pods": [],             # 어떤 파드(들)가 죽었는지 (하드/보스전은 여러 개)
    "start_time": None,            # 장애 시작 시각 (time.time())
    "status": "idle",              # idle / recovering / completed
    "expected_replicas": EXPECTED_REPLICAS,
}

# CPU 부하 / 에러 주입 모드 on-off 스위치
chaos_state = {
    "cpu_load": False,
    "error_mode": False,
}

# 실시간 지표(요청수/에러율/응답시간) 집계용
# deque(maxlen=100): 리스트처럼 쓰지만 100개 넘으면 오래된 것부터 자동으로 버려주는 자료구조.
# -> 평균 응답시간이 "최근 100건 기준"으로 계산되게 하기 위함(전체 평균은 최근 상황을 못 보여줌).
metrics_state = {
    "total_requests": 0,
    "total_errors": 0,
    "response_times": deque(maxlen=100),
    "error_flags": deque(maxlen=100),  # 요청별 에러 여부(1/0) - 에러율 추이 그래프용
}

# 여러 요청이 동시에 metrics_state를 수정할 때 값이 꼬이지 않도록 잠그는 락
# (락: 한 번에 하나의 스레드만 이 구간에 들어오게 막는 장치)
metrics_lock = threading.Lock()

# 실시간 지표는 "/" 경로로 들어오는 실제 트래픽만 집계한다.
# 대시보드 자신의 폴링 API(/api/*)까지 집계에 포함시키면, 폴링 자체가 지표를 왜곡해버린다.
# 시연할 때는 hey, ab, Locust 같은 부하 테스트 도구로 서비스에 트래픽을 흘려주면 된다.
TRACKED_PATHS = {"/"}


# ---------------------------------------------------------------------------
# 2.5 Redis 연동 - 기록실(records) 데이터가 파드 재시작에도 살아남게
#
# 위 records dict는 그 요청을 처리한 파드 프로세스의 메모리에만 있어서, 파드가
# 재시작되면(CI/CD 자동 배포 포함) 사라지고 replica 3개끼리도 서로 안 보인다.
# REDIS_HOST가 설정돼 있으면 기록을 Redis에 저장/조회하고, 비어있거나 연결이
# 실패하면 records dict(파드 메모리)로 조용히 저하한다 - PROMETHEUS_URL/
# SLACK_WEBHOOK_URL과 같은 "선택적 외부 의존성" 패턴을 그대로 따른다.
# ---------------------------------------------------------------------------

RECORDS_KEY_INCIDENTS = "records:incidents"
RECORDS_KEY_RECOVERY_SUM = "records:recovery_sum"
RECORDS_KEY_LEADERBOARD = "records:leaderboard"
RECORDS_KEY_LEADERBOARD_SEQ = "records:leaderboard:seq"
RECORDS_KEY_RECENT_HISTORY = "records:recent_history"
RECORDS_KEY_CURRENT_COMBO = "records:current_combo"
RECORDS_KEY_BEST_COMBO = "records:best_combo"

_redis_client = None


def get_redis_client():
    """
    REDIS_HOST가 비어있으면(로컬 개발, 또는 Redis 미설치 클러스터) None을 반환해
    호출부가 곧바로 in-memory records로 저하하게 한다. 연결 자체는 최초 호출 때
    한 번만 만들어 재사용한다(redis-py 클라이언트가 내부적으로 커넥션 풀을 관리하므로
    매 요청마다 새로 만들 필요가 없다).
    """
    global _redis_client
    if not REDIS_HOST:
        return None
    if _redis_client is None:
        _redis_client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            password=REDIS_PASSWORD or None,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
    return _redis_client


# ---------------------------------------------------------------------------
# 3. Prometheus 메트릭 (Prometheus: 시계열 형태로 지표를 수집하는 모니터링 도구)
# ---------------------------------------------------------------------------

REQUEST_COUNT = Counter("app_requests_total", "총 요청 수")
ERROR_COUNT = Counter("app_errors_total", "총 에러(5xx) 수")
RESPONSE_TIME = Histogram("app_response_time_seconds", "응답 시간(초)")

# Prometheus 서버 주소 (클러스터 내부 Service DNS). 설치 안 된 클러스터(KR1 테스트 등)나
# 로컬 개발 중에는 빈 값으로 둬서 아래 query_prometheus_instant()가 조용히 스킵하게 한다.
PROMETHEUS_URL = os.environ.get("PROMETHEUS_URL", "")


def query_prometheus_instant(promql):
    """
    Prometheus HTTP API(/api/v1/query)로 즉시값(instant vector) 쿼리 하나를 날린다.
    이 앱 자신의 로컬 메모리 집계(metrics_state)는 "요청을 받은 그 파드 하나"의 값이라
    폴링할 때마다 다른 파드가 응답하면 값이 들쭉날쭉하지만, Prometheus는 모든 파드의
    /metrics를 각각 긁어와 합산하므로 "클러스터 전체" 기준의 정확한 값을 준다.
    실패하거나 미설정이면 None을 반환하고, 호출부에서 이를 "연동 안 됨"으로 처리한다.
    """
    if not PROMETHEUS_URL:
        return None
    try:
        resp = requests.get(
            f"{PROMETHEUS_URL}/api/v1/query", params={"query": promql}, timeout=3
        )
        result = resp.json()["data"]["result"]
        return float(result[0]["value"][1]) if result else 0.0
    except (requests.RequestException, KeyError, IndexError, ValueError) as e:
        print(f"Prometheus 쿼리 실패: {e}")
        return None


# ---------------------------------------------------------------------------
# 4. 쿠버네티스 API 헬퍼 함수 (LOCAL_MODE가 false일 때만 실제로 쓰인다)
# ---------------------------------------------------------------------------

def ensure_k8s_config():
    """
    - 파드 "안에서" 실행 중이면 in-cluster 설정(서비스어카운트 토큰 자동 사용)을 쓴다.
    - 그게 실패하면(예: 노트북에서 kubeconfig로 원격 클러스터를 테스트하는 경우) ~/.kube/config를 대신 사용한다.
    """
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()


def get_k8s_client():
    """쿠버네티스 API와 통신할 CoreV1Api(파드/컨피그맵 등) 클라이언트를 만든다."""
    ensure_k8s_config()
    return client.CoreV1Api()


def get_autoscaling_client():
    """HPA(HorizontalPodAutoscaler) 조회 전용 AutoscalingV2Api 클라이언트."""
    ensure_k8s_config()
    return client.AutoscalingV2Api()


def get_chaos_pods(v1):
    """app=chaos-demo 라벨이 붙은 파드 목록만 가져온다."""
    return v1.list_namespaced_pod(
        namespace=NAMESPACE, label_selector=LABEL_SELECTOR
    ).items


DEPLOY_HISTORY_CONFIGMAP_NAME = "chaos-deploy-history"


def get_deploy_history_events(v1):
    """
    chaos-deploy-history ConfigMap의 history.jsonl(JSON Lines, 최신이 맨 위)을 읽어
    이벤트 딕셔너리 목록으로 돌려준다. Jenkinsfile만 이 ConfigMap을 쓰고(Git 커밋 경유),
    여긴 읽기 전용이다(k8s/rbac.yaml에서 이 ConfigMap 하나만 get 권한을 준 이유).
    """
    cm = v1.read_namespaced_config_map(
        name=DEPLOY_HISTORY_CONFIGMAP_NAME, namespace=NAMESPACE
    )
    raw = (cm.data or {}).get("history.jsonl", "")
    events = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except ValueError:
            continue
    return events


HPA_NAME = "chaos-demo"


def get_hpa_status(autoscaling_v2):
    """
    chaos-demo Deployment에 걸린 HPA(k8s/hpa.yaml)의 현재 상태를 읽어온다.
    monitor.html의 "오토스케일링" 패널이 `kubectl get hpa` 없이도 같은 값을 보여줄 수 있게 한다.
    """
    hpa = autoscaling_v2.read_namespaced_horizontal_pod_autoscaler(
        name=HPA_NAME, namespace=NAMESPACE
    )

    current_cpu = None
    for m in hpa.status.current_metrics or []:
        if m.type == "Resource" and m.resource.name == "cpu":
            current_cpu = m.resource.current.average_utilization
            break

    target_cpu = None
    for m in hpa.spec.metrics:
        if m.type == "Resource" and m.resource.name == "cpu":
            target_cpu = m.resource.target.average_utilization
            break

    return {
        "min_replicas": hpa.spec.min_replicas,
        "max_replicas": hpa.spec.max_replicas,
        "current_replicas": hpa.status.current_replicas,
        "desired_replicas": hpa.status.desired_replicas,
        "current_cpu_percent": current_cpu,
        "target_cpu_percent": target_cpu,
    }


def build_mock_hpa():
    """
    LOCAL_MODE용 가짜 HPA 상태. 실제 metrics-server 없이도 CPU 부하 버튼과 연동해서
    화면을 확인할 수 있게, chaos_state["cpu_load"] 켜짐 여부로 스케일 아웃된 것처럼 흉내낸다.
    """
    if chaos_state["cpu_load"]:
        return {
            "min_replicas": 3,
            "max_replicas": 6,
            "current_replicas": 6,
            "desired_replicas": 6,
            "current_cpu_percent": 88,
            "target_cpu_percent": 50,
        }
    return {
        "min_replicas": 3,
        "max_replicas": 6,
        "current_replicas": 3,
        "desired_replicas": 3,
        "current_cpu_percent": 9,
        "target_cpu_percent": 50,
    }


def describe_k8s_error(e):
    """
    get_k8s_client()/get_chaos_pods() 호출 중 발생할 수 있는 예외를 사람이 읽을 메시지로 바꾼다.
    - ApiException(실제 쿠버네티스 API가 에러를 응답한 경우)은 e.reason에 이유가 담겨 있다.
    - ConfigException(클러스터 접속 설정 자체를 못 찾은 경우, 예: LOCAL_MODE=false인데
      in-cluster 설정도 kubeconfig도 없을 때)은 reason 속성이 없어서 str(e)로 대체한다.
    """
    return getattr(e, "reason", None) or str(e)


def is_pod_ready(pod):
    """파드가 Running 상태이고, 컨테이너가 전부 Ready인지 확인한다."""
    if pod.status.phase != "Running":
        return False
    container_statuses = pod.status.container_statuses or []
    if not container_statuses:
        return False
    return all(c.ready for c in container_statuses)


def build_mock_pods():
    """
    LOCAL_MODE용 가짜 파드 목록.
    미션이 진행 중이면(current_mission["active"]) target_pods에 들어있는 파드만
    "재시작 중"으로 보여줘서, 실제 K8s 없이도 파드 격자가 빨간색 -> 초록색으로
    바뀌는 걸 화면에서 확인할 수 있게 한다.
    """
    pods = []
    for name, node in MOCK_PODS:
        is_recovering_target = name in current_mission["target_pods"]
        pods.append(
            {
                "name": name,
                "node": node,
                "phase": "Pending" if is_recovering_target else "Running",
                "ready": not is_recovering_target,
            }
        )
    return pods


def build_mock_deploy_history():
    """LOCAL_MODE용 가짜 배포 히스토리 — 성공 이벤트 몇 개 + 롤백 1건을 섞어 화면 확인용으로 보여준다."""
    return [
        {"build_number": "26", "git_commit": "66c61b6", "status": "success", "timestamp": "2026-07-28T09:40:00Z"},
        {"build_number": "25", "git_commit": "1b5bb8d", "status": "success", "timestamp": "2026-07-28T09:20:00Z"},
        {"build_number": "24", "git_commit": "def4567", "status": "rollback", "recovered_build": "23", "timestamp": "2026-07-28T09:00:00Z"},
        {"build_number": "23", "git_commit": "789abcd", "status": "success", "timestamp": "2026-07-28T08:40:00Z"},
    ]


def compute_rank(elapsed_seconds):
    """복구 시간(초)을 S/A/B/C 랭크로 변환한다. 짧을수록 높은 랭크."""
    for limit, rank in RANK_THRESHOLDS:
        if elapsed_seconds <= limit:
            return rank
    return RANK_DEFAULT


def compute_deploy_rank(elapsed_seconds):
    """배포 파이프라인 소요시간(초)을 S/A/B/C 랭크로 변환한다. compute_rank와 같은 방식, 기준표만 다르다."""
    for limit, rank in DEPLOY_RANK_THRESHOLDS:
        if elapsed_seconds <= limit:
            return rank
    return RANK_DEFAULT


# ---------------------------------------------------------------------------
# 5. Slack 알림 헬퍼 함수 (선택 기능)
# ---------------------------------------------------------------------------

def send_slack_message(text):
    """
    Slack Webhook으로 메시지를 보낸다.
    SLACK_WEBHOOK_URL이 설정 안 됐으면(로컬 개발 중 등) 조용히 무시하고 넘어간다.
    (webhook: Slack이 미리 만들어주는 전용 URL로, 여기에 POST 요청만 보내면 채널에 메시지가 올라감)
    """
    if not SLACK_WEBHOOK_URL:
        return
    try:
        requests.post(SLACK_WEBHOOK_URL, json={"text": text}, timeout=3)
    except requests.RequestException as e:
        print(f"Slack 전송 실패: {e}")  # 실패해도 앱은 계속 동작해야 함


# ---------------------------------------------------------------------------
# 6. 요청 지표 수집 훅 (hook: 요청 처리 전/후에 자동으로 끼어들어 실행되는 함수)
# ---------------------------------------------------------------------------

@app.before_request
def before_request_start_timer():
    request._start_time = time.time()


@app.after_request
def after_request_record_metrics(response):
    if request.path in TRACKED_PATHS:
        elapsed_seconds = time.time() - getattr(request, "_start_time", time.time())

        with metrics_lock:
            metrics_state["total_requests"] += 1
            metrics_state["response_times"].append(elapsed_seconds * 1000)
            metrics_state["error_flags"].append(1 if response.status_code >= 500 else 0)
            if response.status_code >= 500:
                metrics_state["total_errors"] += 1

        REQUEST_COUNT.inc()
        RESPONSE_TIME.observe(elapsed_seconds)
        if response.status_code >= 500:
            ERROR_COUNT.inc()

    return response


# ---------------------------------------------------------------------------
# 7. CPU 부하 시뮬레이션 (버튼을 누를 때만 스레드를 새로 띄우는 방식)
# ---------------------------------------------------------------------------

_cpu_thread = None


def _cpu_burn():
    """chaos_state['cpu_load']가 True인 동안 계속 CPU를 소모하는 함수 (스레드에서 실행됨)."""
    while chaos_state["cpu_load"]:
        _ = sum(i * i for i in range(10000))  # 의미 없는 계산 반복 -> CPU 사용률 상승


def set_cpu_load(is_on):
    """CPU 부하 스레드를 켜고 끄는 걸 한 곳에서 담당한다 (토글 버튼과 보스전 모드가 같이 사용)."""
    global _cpu_thread
    chaos_state["cpu_load"] = is_on
    if is_on:
        # 데몬 스레드(daemon thread): 메인 프로그램이 끝나면 같이 종료되는 백그라운드 작업
        _cpu_thread = threading.Thread(target=_cpu_burn, daemon=True)
        _cpu_thread.start()


# ---------------------------------------------------------------------------
# 7-1. 인프라 지도(/infra) — 상대 리전 상태를 백그라운드에서 미리 확인해두기
# ---------------------------------------------------------------------------
# 왜 요청이 올 때마다 확인하지 않는가: 리전 하나가 진짜로 죽어있는 그 순간(=이 기능이 보여주고
# 싶은 바로 그 순간)에 매 폴링마다 새로 timeout을 기다리게 하면, 정작 보여주고 싶은 순간에
# 화면이 굼떠진다. 그래서 상시로 도는 백그라운드 스레드(_cpu_burn과 같은 daemon thread 패턴)가
# 5초마다 미리 확인해서 결과를 딕셔너리 하나로 새로 만들어 통째로 스왑해두고, API는 그 캐시를
# 읽기만 한다(요청 스레드 안에서 네트워크 I/O를 하지 않음).

_regions_cache = {"self": APP_VERSION, "gslb_target": None, "checked_at": None, "regions": []}


def _check_region_reachable(url):
    """상대 리전의 /health를 확인. 기존 query_prometheus_instant()와 동일한 try/except 관용구."""
    try:
        resp = requests.get(f"{url}/health", timeout=2)
        return resp.status_code == 200
    except requests.RequestException as e:
        print(f"리전 상태 확인 실패({url}): {e}")
        return False


def _check_gslb_target():
    """
    GSLB가 지금 실제로 어느 리전에 트래픽을 보내는지는 추측하지 않고, 공개 도메인을 실제로
    호출해서 확인한다 - 상대 리전이 안 닿는다고 "그럼 자기 자신이겠지"로 지레짐작하면, 이 기능의
    존재 이유인 GSLB의 실제 TTL 지연(30~80초)을 화면에서 보여줄 수가 없다.
    """
    try:
        resp = requests.get(f"{GSLB_PUBLIC_URL}/api/status", timeout=2)
        return resp.json().get("version")
    except (requests.RequestException, ValueError) as e:
        print(f"GSLB 대상 확인 실패: {e}")
        return None


def _build_regions_snapshot():
    region_results = []
    for region in REGIONS:
        is_self = region["id"] == APP_VERSION
        reachable = True if is_self else _check_region_reachable(region["url"])
        region_results.append(
            {
                "id": region["id"],
                "label": region["label"],
                "reachable": reachable,
                "is_self": is_self,
            }
        )

    return {
        "self": APP_VERSION,
        "gslb_target": _check_gslb_target(),
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "regions": region_results,
    }


def _refresh_regions_loop():
    global _regions_cache
    while True:
        if REGIONS:
            _regions_cache = _build_regions_snapshot()  # 새 dict 통째로 스왑 -> 원자적, Lock 불필요
        time.sleep(5)


if REGIONS and not LOCAL_MODE:
    threading.Thread(target=_refresh_regions_loop, daemon=True).start()


# ---------------------------------------------------------------------------
# 8. 화면 / 기본 라우트
# ---------------------------------------------------------------------------

@app.route("/")
def dashboard():
    # 에러 주입 모드가 켜져 있으면, 일정 확률로 500 에러를 응답한다 (에러율 지표를 올리기 위함)
    if chaos_state["error_mode"] and random.random() < 0.4:
        return "Internal Server Error (chaos: 에러 주입 모드)", 500
    return render_template(
        "game.html",
        version=APP_VERSION,
        active_page="game",
        rank_thresholds=RANK_THRESHOLDS,
    )


@app.route("/monitor")
def monitor():
    return render_template("monitor.html", version=APP_VERSION, active_page="monitor")


@app.route("/records")
def records_page():
    return render_template("records.html", version=APP_VERSION, active_page="records")


@app.route("/cicd")
def cicd_page():
    return render_template(
        "cicd.html",
        version=APP_VERSION,
        active_page="cicd",
        deploy_rank_thresholds=DEPLOY_RANK_THRESHOLDS,
    )


@app.route("/infra")
def infra_page():
    return render_template("infra.html", version=APP_VERSION, active_page="infra")


@app.route("/health")
def health():
    """K8s Liveness/Readiness Probe가 호출하는 헬스체크 엔드포인트."""
    return jsonify({"status": "ok"}), 200


@app.route("/metrics")
def metrics():
    """Prometheus가 주기적으로 긁어가는(scrape) 엔드포인트."""
    return generate_latest(), 200, {"Content-Type": CONTENT_TYPE_LATEST}


# ---------------------------------------------------------------------------
# 9. 대시보드 데이터 API
# ---------------------------------------------------------------------------

@app.route("/api/status")
def api_status():
    with metrics_lock:
        total = metrics_state["total_requests"]
        errors = metrics_state["total_errors"]
        response_times = list(metrics_state["response_times"])
        error_flags = list(metrics_state["error_flags"])

    error_rate = round((errors / total * 100), 2) if total > 0 else 0.0
    avg_response_ms = (
        round(sum(response_times) / len(response_times), 1) if response_times else 0.0
    )

    # 대시보드 페이지의 응답시간 스파크라인용 최근 값들 (최대 30개, 오래된 것부터)
    response_time_history = [round(v, 1) for v in response_times[-30:]]

    # 에러율 추이 그래프용: 10개씩 묶어서(sliding window) 구간별 에러 비율(%)을 계산한다.
    # 요청 하나하나의 성공/실패(0 또는 1)만 보면 들쭉날쭉해서 흐름을 읽기 어렵기 때문.
    error_window = 10
    error_rate_history = [
        round(sum(error_flags[i - error_window:i]) / error_window * 100, 1)
        for i in range(error_window, len(error_flags) + 1)
    ][-30:]

    return jsonify(
        {
            "version": APP_VERSION,
            "build_number": BUILD_NUMBER,
            "git_commit": GIT_COMMIT,
            "deploy_duration_seconds": (
                int(DEPLOY_DURATION_SECONDS) if DEPLOY_DURATION_SECONDS.isdigit() else None
            ),
            "deploy_rank": (
                compute_deploy_rank(int(DEPLOY_DURATION_SECONDS))
                if DEPLOY_DURATION_SECONDS.isdigit()
                else None
            ),
            "local_mode": LOCAL_MODE,
            "total_requests": total,
            "error_rate_percent": error_rate,
            "avg_response_ms": avg_response_ms,
            "error_rate_history": error_rate_history,
            "response_time_history": response_time_history,
            "cpu_load": chaos_state["cpu_load"],
            "error_mode": chaos_state["error_mode"],
        }
    )


@app.route("/api/metrics/cluster")
def api_metrics_cluster():
    """
    Prometheus 기준 "클러스터 전체" 지표. api_status()의 값은 응답한 파드 하나의
    로컬 메모리 기준이라 폴링마다 들쭉날쭉할 수 있는데, 여기는 sum(rate(...))로
    모든 파드를 합산한 값이라 어느 파드가 응답했는지와 무관하게 항상 같은 값이 나온다.
    """
    req_rate = query_prometheus_instant("sum(rate(app_requests_total[1m]))")
    err_pct = query_prometheus_instant(
        "sum(rate(app_errors_total[1m])) / sum(rate(app_requests_total[1m])) * 100"
    )
    avg_ms = query_prometheus_instant(
        "sum(rate(app_response_time_seconds_sum[1m]))"
        " / sum(rate(app_response_time_seconds_count[1m])) * 1000"
    )

    return jsonify(
        {
            "available": req_rate is not None,
            "cluster_request_rate": round(req_rate, 2) if req_rate is not None else None,
            "cluster_error_rate_percent": round(err_pct, 2) if err_pct is not None else None,
            "cluster_avg_response_ms": round(avg_ms, 1) if avg_ms is not None else None,
        }
    )


@app.route("/api/hpa")
def api_hpa():
    """
    오토스케일링(HPA) 상태 — monitor.html의 "오토스케일링" 패널이 이 값을 그대로 보여준다.
    HPA가 아직 없는 클러스터(KR1 등)에서는 read 호출이 404로 실패하는데, 이것도 다른
    선택적 연동(Prometheus 등)과 똑같이 available:false로 우아하게 처리한다.
    """
    if LOCAL_MODE:
        return jsonify({"available": True, **build_mock_hpa()})

    try:
        v2 = get_autoscaling_client()
        status = get_hpa_status(v2)
    except (ApiException, config.ConfigException) as e:
        return jsonify({"available": False, "error": f"쿠버네티스 API 호출 실패: {describe_k8s_error(e)}"})

    return jsonify({"available": True, **status})


@app.route("/api/pods")
def api_pods():
    if LOCAL_MODE:
        return jsonify({"pods": build_mock_pods()})

    try:
        v1 = get_k8s_client()
        pods = get_chaos_pods(v1)
    except (ApiException, config.ConfigException) as e:
        return jsonify({"error": f"쿠버네티스 API 호출 실패: {describe_k8s_error(e)}"}), 500

    pod_list = [
        {
            "name": pod.metadata.name,
            "node": pod.spec.node_name or "알수없음",
            "phase": pod.status.phase,
            "ready": is_pod_ready(pod),
        }
        for pod in pods
    ]
    return jsonify({"pods": pod_list})


@app.route("/api/regions")
def api_regions():
    """
    인프라 지도(/infra) 탭이 폴링하는 API. 실제 네트워크 호출은 이미 백그라운드 스레드
    (_refresh_regions_loop)가 5초마다 미리 해뒀으므로, 여기서는 그 캐시를 그대로 반환한다.
    REGIONS_JSON이 아직 설정 안 된 클러스터(예: 배포는 됐지만 매니페스트에 이 env를 아직 안
    넣은 상태)에서는 다른 선택적 연동(Prometheus/HPA)과 같은 패턴으로 available:false를 반환한다
    - LOCAL_MODE 목업과 헷갈리지 않도록, 가짜 "정상" 데이터로 우아하게 저하하지 않는다.
    """
    if LOCAL_MODE:
        return jsonify(
            {
                "available": True,
                "self": "kr1",
                "gslb_target": "kr1",
                "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "regions": [
                    {"id": "kr1", "label": "판교", "reachable": True, "is_self": True},
                    {"id": "kr2", "label": "평촌", "reachable": True, "is_self": False},
                ],
            }
        )

    if not REGIONS:
        return jsonify({"available": False})

    return jsonify({"available": True, **_regions_cache})


@app.route("/api/deploy-history")
def api_deploy_history():
    """CI/CD 탭의 배포 히스토리 타임라인용 — 최신순 성공/롤백 이벤트 목록."""
    if LOCAL_MODE:
        return jsonify({"events": build_mock_deploy_history()})

    try:
        v1 = get_k8s_client()
        events = get_deploy_history_events(v1)
    except (ApiException, config.ConfigException) as e:
        return jsonify({"error": f"쿠버네티스 API 호출 실패: {describe_k8s_error(e)}"}), 500

    return jsonify({"events": events})


@app.route("/api/mission/peek")
def api_mission_peek():
    """
    다른 페이지(대시보드/기록)의 네비게이션 배지가 쓰는 조회 전용 엔드포인트.
    /api/mission/status와 달리 완료 판정이나 기록 갱신을 하지 않는다.
    (완료 판정까지 같이 하면, 게임 페이지가 아닌 곳에서 먼저 완료 처리를 가로채서
    게임 화면의 랭크 연출이 안 뜨는 문제가 생길 수 있다.)
    """
    if not current_mission["active"]:
        return jsonify({"active": False})
    elapsed = time.time() - current_mission["start_time"]
    return jsonify({"active": True, "elapsed": round(elapsed, 1)})


@app.route("/api/mission/status")
def api_mission_status():
    if not current_mission["active"]:
        return jsonify({"status": "idle"})

    elapsed = time.time() - current_mission["start_time"]

    if LOCAL_MODE:
        # 로컬에서는 정해진 시간이 지나면 자동으로 "복구 완료"로 흉내낸다 (화면 테스트용)
        if elapsed >= LOCAL_MOCK_RECOVERY_SECONDS:
            return _complete_mission(elapsed)
        return jsonify({"status": "recovering", "elapsed": round(elapsed, 1)})

    try:
        v1 = get_k8s_client()
        pods = get_chaos_pods(v1)
    except (ApiException, config.ConfigException) as e:
        return jsonify(
            {
                "status": "recovering",
                "elapsed": round(elapsed, 1),
                "error": f"쿠버네티스 API 호출 실패: {describe_k8s_error(e)}",
            }
        )

    # 중요: 파드 개수가 기대치(expected_replicas)만큼 다 있고, 전부 Ready인지 확인한다.
    # 삭제 직후에는 "남아 있는 파드들"만 놓고 보면 전부 Ready라서, 새 파드가 아직
    # 만들어지기 전인데도 "복구 완료"로 잘못 판단하는 레이스 컨디션이 생길 수 있다.
    # 그래서 Ready한 파드 "개수"가 기대치 이상인지까지 같이 확인해야 한다.
    # (하드/보스전처럼 여러 파드를 한 번에 죽여도 이 개수 비교 로직은 그대로 통한다.)
    ready_count = sum(1 for pod in pods if is_pod_ready(pod))
    all_ready = ready_count >= current_mission["expected_replicas"]

    if all_ready:
        return _complete_mission(elapsed)

    return jsonify({"status": "recovering", "elapsed": round(elapsed, 1)})


def _record_completion(elapsed, rank):
    """
    미션 완료 기록을 Redis(가능하면) 또는 파드 메모리(records dict, 저하 시)에 남기고,
    이번 완료 반영 후의 current_combo 값을 반환한다.
    """
    r = get_redis_client()
    if r is not None:
        try:
            r.incr(RECORDS_KEY_INCIDENTS)
            r.incrbyfloat(RECORDS_KEY_RECOVERY_SUM, elapsed)

            # 유일한 멤버가 필요해서 elapsed 값 자체가 아니라 순번을 멤버로 쓴다
            # (같은 초수가 두 번 나오면 ZSET 멤버가 충돌해 하나로 합쳐져 버리기 때문).
            seq = r.incr(RECORDS_KEY_LEADERBOARD_SEQ)
            r.zadd(RECORDS_KEY_LEADERBOARD, {f"run-{seq}": elapsed})
            r.zremrangebyrank(RECORDS_KEY_LEADERBOARD, 3, -1)  # 상위 3개(가장 빠른)만 남김

            r.lpush(RECORDS_KEY_RECENT_HISTORY, elapsed)
            r.ltrim(RECORDS_KEY_RECENT_HISTORY, 0, 11)  # 최근 12개만 유지

            if rank == "S":
                new_combo = r.incr(RECORDS_KEY_CURRENT_COMBO)
            else:
                r.set(RECORDS_KEY_CURRENT_COMBO, 0)
                new_combo = 0
            # GT: 기존 값보다 클 때만 갱신하는 원자 연산 - read-compare-write 레이스가 없다.
            r.zadd(RECORDS_KEY_BEST_COMBO, {"best": new_combo}, gt=True, ch=True)
            return new_combo
        except redis.exceptions.RedisError as e:
            print(f"Redis 기록 실패, 파드 메모리로 저하: {e}")
            # 아래 in-memory 경로로 이어서 진행

    records["total_incidents"] += 1
    records["recovery_times"].append(elapsed)
    if records["best_time"] is None or elapsed < records["best_time"]:
        records["best_time"] = elapsed
    records["top_times"] = sorted(records["top_times"] + [elapsed])[:3]
    if rank == "S":
        records["current_combo"] += 1
    else:
        records["current_combo"] = 0
    records["best_combo"] = max(records["best_combo"], records["current_combo"])
    return records["current_combo"]


def _fetch_records_snapshot():
    """
    화면에 내려줄 기록판 스냅샷을 만든다. Redis가 설정돼 있고 정상이면 Redis에서,
    아니면 파드 메모리(records dict)에서 읽는다 - 두 경우 모두 같은 모양의 dict를 반환한다.
    """
    r = get_redis_client()
    if r is not None:
        try:
            incidents = int(r.get(RECORDS_KEY_INCIDENTS) or 0)
            recovery_sum = float(r.get(RECORDS_KEY_RECOVERY_SUM) or 0.0)

            # 하이스코어 보드: 1~3등 (금/은/동) - 점수(초)가 낮을수록 빠른 기록
            top = r.zrange(RECORDS_KEY_LEADERBOARD, 0, 2, withscores=True)
            leaderboard = [
                {"rank_no": i + 1, "seconds": round(score, 1)}
                for i, (_member, score) in enumerate(top)
            ]

            # LPUSH라 최신이 맨 앞이라서, 원래 순서(오래된 것부터)에 맞추려면 뒤집는다.
            raw_recent = r.lrange(RECORDS_KEY_RECENT_HISTORY, 0, 11)
            recent_seconds = [float(t) for t in reversed(raw_recent)]

            current_combo = int(r.get(RECORDS_KEY_CURRENT_COMBO) or 0)
            best_combo_raw = r.zscore(RECORDS_KEY_BEST_COMBO, "best")

            return {
                "total_incidents": incidents,
                "avg_recovery_seconds": round(recovery_sum / incidents, 1) if incidents else 0.0,
                "best_recovery_seconds": leaderboard[0]["seconds"] if leaderboard else None,
                "leaderboard": leaderboard,
                "recent_seconds": recent_seconds,
                "current_combo": current_combo,
                "best_combo": int(best_combo_raw) if best_combo_raw is not None else 0,
            }
        except redis.exceptions.RedisError as e:
            print(f"Redis 조회 실패, 파드 메모리로 저하: {e}")
            # 아래 in-memory 경로로 이어서 진행

    times = records["recovery_times"]
    return {
        "total_incidents": records["total_incidents"],
        "avg_recovery_seconds": round(sum(times) / len(times), 1) if times else 0.0,
        "best_recovery_seconds": (
            round(records["best_time"], 1) if records["best_time"] is not None else None
        ),
        "leaderboard": [
            {"rank_no": i + 1, "seconds": round(t, 1)}
            for i, t in enumerate(records["top_times"])
        ],
        "recent_seconds": times[-12:],
        "current_combo": records["current_combo"],
        "best_combo": records["best_combo"],
    }


def _complete_mission(elapsed):
    """미션 완료 처리를 한 곳에서 담당한다 (중복 코드 방지용 헬퍼 함수)."""
    rank = compute_rank(elapsed)
    new_combo = _record_completion(elapsed, rank)

    current_mission["active"] = False
    current_mission["status"] = "completed"
    current_mission["target_pods"] = []

    send_slack_message(f"🏆 [게임] 복구 완료! {elapsed:.1f}초 ({rank}랭크)")
    return jsonify(
        {
            "status": "completed",
            "elapsed": round(elapsed, 1),
            "rank": rank,
            "combo": new_combo,
        }
    )


@app.route("/api/records")
def api_records():
    snap = _fetch_records_snapshot()
    # 최근 기록 막대그래프용 (최대 12개, 오래된 것부터, 랭크 포함)
    recent_history = [
        {"seconds": round(t, 1), "rank": compute_rank(t)}
        for t in snap["recent_seconds"]
    ]
    return jsonify(
        {
            "total_incidents": snap["total_incidents"],
            "avg_recovery_seconds": snap["avg_recovery_seconds"],
            "best_recovery_seconds": snap["best_recovery_seconds"],
            "leaderboard": snap["leaderboard"],
            "recent_history": recent_history,
            "current_combo": snap["current_combo"],
            "best_combo": snap["best_combo"],
        }
    )


@app.route("/api/records/reset", methods=["POST"])
def api_records_reset():
    """데모를 처음부터 다시 보여주고 싶을 때 기록판만 초기화한다 (진행 중인 미션에는 영향 없음)."""
    r = get_redis_client()
    if r is not None:
        try:
            r.delete(
                RECORDS_KEY_INCIDENTS,
                RECORDS_KEY_RECOVERY_SUM,
                RECORDS_KEY_LEADERBOARD,
                RECORDS_KEY_LEADERBOARD_SEQ,
                RECORDS_KEY_RECENT_HISTORY,
                RECORDS_KEY_CURRENT_COMBO,
                RECORDS_KEY_BEST_COMBO,
            )
        except redis.exceptions.RedisError as e:
            print(f"Redis 초기화 실패: {e}")

    # Redis 사용 여부와 무관하게 파드 메모리 쪽도 항상 같이 초기화한다 - Redis가 잠깐
    # 끊긴 사이에 저하돼서 쓰인 기록이 있었더라도 리셋 후엔 뒤섞이지 않게 하기 위함.
    records["total_incidents"] = 0
    records["recovery_times"] = []
    records["best_time"] = None
    records["top_times"] = []
    records["current_combo"] = 0
    records["best_combo"] = 0
    return jsonify({"reset": True})


# ---------------------------------------------------------------------------
# 10. Chaos 액션 API (일부러 장애를 일으키거나 복구하는 버튼들)
# ---------------------------------------------------------------------------

def _run_chaos_kill(kill_count, also_cpu=False, also_error=False, mode_label="이지"):
    """
    난이도별 장애 주입 공통 로직.
    - 이지: 파드 1개 삭제
    - 하드: 파드 2개 동시 삭제
    - 보스전: 파드 2개 삭제 + CPU 부하 + 에러 모드까지 동시 발동
    """
    if current_mission["active"]:
        return jsonify({"error": "이미 진행 중인 미션이 있습니다."}), 409

    if LOCAL_MODE:
        targets = MOCK_POD_NAMES[:kill_count]
        current_mission.update(
            {
                "active": True,
                "target_pods": targets,
                "start_time": time.time(),
                "status": "recovering",
            }
        )
        if also_cpu:
            set_cpu_load(True)
        if also_error:
            chaos_state["error_mode"] = True

        send_slack_message(f"🎲 [게임:{mode_label}] 장애 발생: {', '.join(targets)} (로컬 모드)")
        return jsonify({"killed": targets, "mode": mode_label})

    try:
        v1 = get_k8s_client()
        pods = get_chaos_pods(v1)
    except (ApiException, config.ConfigException) as e:
        return jsonify({"error": f"쿠버네티스 API 호출 실패: {describe_k8s_error(e)}"}), 500

    if not pods:
        return jsonify({"error": f"라벨 {LABEL_SELECTOR}에 해당하는 파드가 없습니다."}), 404

    targets = random.sample(pods, min(kill_count, len(pods)))
    target_names = [pod.metadata.name for pod in targets]

    current_mission.update(
        {
            "active": True,
            "target_pods": target_names,
            "start_time": time.time(),
            "status": "recovering",
        }
    )

    try:
        for pod in targets:
            v1.delete_namespaced_pod(name=pod.metadata.name, namespace=NAMESPACE)
    except ApiException as e:
        current_mission["active"] = False
        current_mission["status"] = "idle"
        return jsonify({"error": f"파드 삭제 실패: {e.reason}"}), 500

    if also_cpu:
        set_cpu_load(True)
    if also_error:
        chaos_state["error_mode"] = True

    send_slack_message(f"🎲 [게임:{mode_label}] 장애 발생: {', '.join(target_names)}")
    return jsonify({"killed": target_names, "mode": mode_label})


@app.route("/chaos/random-pod-kill", methods=["POST"])
def chaos_random_pod_kill():
    """이지 모드: 파드 1개만 삭제 (기존 버튼과 동일)."""
    return _run_chaos_kill(kill_count=1, mode_label="이지")


@app.route("/chaos/hard-mode", methods=["POST"])
def chaos_hard_mode():
    """하드 모드: 파드 2개를 동시에 삭제해서 복구를 더 어렵게 만든다."""
    return _run_chaos_kill(kill_count=2, mode_label="하드")


@app.route("/chaos/boss-mode", methods=["POST"])
def chaos_boss_mode():
    """보스전: 파드 2개 삭제 + CPU 부하 + 에러 모드를 한꺼번에 터뜨린다."""
    return _run_chaos_kill(kill_count=2, also_cpu=True, also_error=True, mode_label="보스전")


@app.route("/chaos/cpu", methods=["POST"])
def chaos_cpu():
    set_cpu_load(not chaos_state["cpu_load"])
    state_text = "시작" if chaos_state["cpu_load"] else "종료"
    send_slack_message(f"🔥 [게임] CPU 부하 모드 {state_text}")
    return jsonify({"cpu_load": chaos_state["cpu_load"]})


@app.route("/chaos/error", methods=["POST"])
def chaos_error():
    chaos_state["error_mode"] = not chaos_state["error_mode"]
    state_text = "시작" if chaos_state["error_mode"] else "종료"
    send_slack_message(f"💥 [게임] 에러 주입 모드 {state_text}")
    return jsonify({"error_mode": chaos_state["error_mode"]})


@app.route("/chaos/recover", methods=["POST"])
def chaos_recover():
    # CPU 부하 스레드는 chaos_state["cpu_load"]가 False가 되는 순간 반복문(while)을 빠져나오며 스스로 멈춘다.
    set_cpu_load(False)
    chaos_state["error_mode"] = False
    send_slack_message("✅ [게임] 모든 Chaos 모드 정상 복귀")
    return jsonify({"cpu_load": False, "error_mode": False})


# ---------------------------------------------------------------------------
# 11. 로컬/컨테이너 실행 진입점
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True)
