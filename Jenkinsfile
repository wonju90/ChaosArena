// Jenkins CI/CD 파이프라인 — push 시 Kaniko 빌드+push → cosign 서명까지만 담당(CI).
// 배포(CD)는 여기서 kubectl로 직접 하지 않고, ChaosArena-manifests 레포에 이미지 태그를 커밋+푸시하면
// 클러스터 안의 ArgoCD가 그 변경을 감지해서 스스로 반영한다(GitOps, Pull 모델).
// 배경/설계 근거는 docs/PROJECT_LOG.md 3.5절, docs/CONCEPTS.md 11~13절·Push vs Pull 절 참고.
// 배포 후에는 앱 자신의 /api/status로 새 버전이 실제로 응답하는지 확인하고, 타임아웃되면 이전
// 버전으로 되돌리는 커밋을 자동으로 push한다(자동 롤백, CONCEPTS.md 17절).
// 성공/롤백 결과는 매번 chaos-deploy-history ConfigMap에 한 줄씩 기록해서 CI/CD 탭의 배포
// 히스토리 타임라인에 남긴다(CONCEPTS.md 18절).
// KR1/KR2 각자 독립된 Jenkins가 이 파일을 그대로 공유해서 쓴다 — env.REGION 하나로 분기한다.

def REGISTRY = "55901daa-kr1-registry.container.nhncloud.com/chaosarena-registry/chaos-arena"
// env.REGION은 Jenkins 컨트롤러 자체에 심어둔 값(k8s/jenkins-values.yaml/-kr1.yaml의 containerEnv) —
// KR1/KR2가 각자 독립된 Jenkins를 갖게 되면서(컨트롤 플레인 이중화), 같은 Jenkinsfile을 그대로 쓰되
// 이 값 하나로 "어느 리전의 배포인지"를 구분한다.
// 태그에 리전을 안 붙이면: 두 Jenkins가 서로 다른 독립된 BUILD_NUMBER 카운터를 갖고 있어서,
// KR1의 12번째 빌드와 KR2의 12번째 빌드가 같은 NCR 태그를 덮어써버린다.
def IMAGE_TAG = "${env.REGION}-jenkins-${env.BUILD_NUMBER}"
def MANIFESTS_PATH = "argocd-managed-${env.REGION}"
def MANIFESTS_REPO = "github.com/wonju90/ChaosArena-manifests.git"

pipeline {
    agent {
        kubernetes {
            yaml """
apiVersion: v1
kind: Pod
spec:
  # ArgoCD 도입 이전엔 여기서 kubectl로 직접 배포해야 해서 jenkins-deployer ServiceAccount(클러스터
  # 배포 권한)가 필요했다. 이제 Jenkins는 Git에 커밋만 하고 클러스터는 안 건드리므로, 이 파드는
  # 클러스터 권한이 필요 없다 — 이게 Push→Pull 전환의 핵심 이점(권한이 Jenkins 밖으로 안 나감).
  containers:
    - name: kaniko
      image: gcr.io/kaniko-project/executor:v1.23.2-debug
      command: ["/busybox/cat"]
      tty: true
      volumeMounts:
        - name: ncr-auth
          mountPath: /kaniko/.docker
    - name: cosign
      # curlimages/curl은 기본적으로 non-root(curl_user)로 떠서, Jenkins가 워크스페이스에
      # 실행 스크립트를 쓰는 과정에서 권한 문제로 "process apparently never started"가 발생했다.
      # root로 도는 alpine + 내장 wget으로 대체.
      image: alpine:3.19
      command: ["cat"]
      tty: true
      env:
        - name: DOCKER_CONFIG
          value: /root/.docker
        - name: COSIGN_PASSWORD
          valueFrom:
            secretKeyRef:
              name: cosign-key
              key: password
      volumeMounts:
        - name: ncr-auth
          mountPath: /root/.docker
        - name: cosign-key
          mountPath: /mnt/cosign-key
    - name: git
      # ChaosArena-manifests 레포를 clone/commit/push하는 전용 컨테이너. alpine/git은 기본이 root라
      # cosign/kubectl 스테이지 때 겪었던 "process apparently never started"(non-root 워크스페이스 쓰기
      # 실패) 문제가 애초에 없다.
      image: alpine/git:2.45.2
      command: ["cat"]
      tty: true
      env:
        - name: GIT_MANIFESTS_TOKEN
          valueFrom:
            secretKeyRef:
              name: manifests-repo-token
              key: token
  volumes:
    - name: ncr-auth
      secret:
        secretName: ncr-secret
        items:
          - key: .dockerconfigjson
            path: config.json
    - name: cosign-key
      secret:
        secretName: cosign-key
        items:
          - key: cosign.key
            path: cosign.key
"""
        }
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
                // 배포 랭크(게임 테마 CI/CD 탭)를 계산하려면 파이프라인 전체 소요시간이 필요하다.
                // env.X = ... 로 지정한 값은 이후 스테이지에서도 그대로 읽을 수 있다.
                script {
                    env.PIPELINE_START_MS = System.currentTimeMillis().toString()
                }
            }
        }

        stage('Build & Push') {
            steps {
                container('kaniko') {
                    sh """
                        /kaniko/executor \
                          --dockerfile=Dockerfile \
                          --context=dir://\${WORKSPACE} \
                          --destination=${REGISTRY}:${IMAGE_TAG}
                    """
                }
            }
        }

        stage('Sign') {
            steps {
                container('cosign') {
                    sh """
                        wget -q -O /tmp/cosign https://github.com/sigstore/cosign/releases/download/v2.4.1/cosign-linux-amd64
                        chmod +x /tmp/cosign
                        /tmp/cosign sign --yes \
                          --key=/mnt/cosign-key/cosign.key \
                          --registry-referrers-mode=legacy \
                          ${REGISTRY}:${IMAGE_TAG}
                    """
                }
            }
        }

        stage('Update Manifests Repo') {
            // 예전엔 여기서 kubectl로 클러스터를 직접 바꿨다(Push 모델). 지금은 GitOps 매니페스트
            // 레포에 커밋+푸시만 하고, 클러스터에 실제로 반영하는 건 ArgoCD의 몫이다(Pull 모델) —
            // 그래서 이 스테이지 이름도 "Deploy"가 아니라 "Update Manifests Repo"다.
            steps {
                script {
                    // checkout scm이 채워주는 전체 커밋 해시를 화면 표시용으로 짧게 자른다.
                    env.GIT_COMMIT_SHORT = env.GIT_COMMIT ? env.GIT_COMMIT.take(7) : "unknown"
                    // Checkout 스테이지 시작 시점부터 지금까지 걸린 시간(초) = 이번 빌드의 "배포 랭크" 소재.
                    // 주의: 이 값은 이제 "Jenkins가 빌드+서명+매니페스트 커밋까지 끝낸 시간"이지,
                    // 실제로 클러스터에 반영되기까지의 시간이 아니다(그건 ArgoCD 동기화 몫).
                    env.DEPLOY_DURATION_SECONDS = ((System.currentTimeMillis() - env.PIPELINE_START_MS.toLong()) / 1000).toInteger().toString()
                }
                container('git') {
                    sh """
                        # yq(구조화된 YAML 편집기)를 쓴다 — sed는 "몇 번째 줄 다음 줄을 바꿔라" 식이라
                        # env 목록 순서가 조금만 바뀌어도 깨지기 쉽다. yq는 "이름이 BUILD_NUMBER인
                        # 항목의 value"처럼 구조로 찾아서 바꾸므로 몇 번을 반복 실행해도 안전하다.
                        wget -q -O /usr/local/bin/yq https://github.com/mikefarah/yq/releases/download/v4.44.3/yq_linux_amd64
                        chmod +x /usr/local/bin/yq

                        rm -rf manifests-repo
                        git clone https://\${GIT_MANIFESTS_TOKEN}@${MANIFESTS_REPO} manifests-repo
                        cd manifests-repo/${MANIFESTS_PATH}

                        # 헬스체크 실패 시 되돌릴 수 있도록, 덮어쓰기 전의 값을 워크스페이스에 파일로
                        # 남겨둔다 — 워크스페이스는 스테이지/컨테이너를 넘나들며 공유되므로, 다음
                        # "Verify Deployment" 스테이지에서 그대로 읽어서 롤백에 쓴다.
                        PREV_IMAGE=\$(yq eval '.spec.template.spec.containers[0].image' deployment.yaml)
                        PREV_BUILD_NUMBER=\$(yq eval '(.spec.template.spec.containers[0].env[] | select(.name == "BUILD_NUMBER") | .value)' deployment.yaml)
                        PREV_GIT_COMMIT=\$(yq eval '(.spec.template.spec.containers[0].env[] | select(.name == "GIT_COMMIT") | .value)' deployment.yaml)
                        PREV_DEPLOY_DURATION=\$(yq eval '(.spec.template.spec.containers[0].env[] | select(.name == "DEPLOY_DURATION_SECONDS") | .value)' deployment.yaml)
                        echo "export PREVIOUS_IMAGE=\$PREV_IMAGE" > ../rollback-info.env
                        echo "export PREVIOUS_BUILD_NUMBER=\$PREV_BUILD_NUMBER" >> ../rollback-info.env
                        echo "export PREVIOUS_GIT_COMMIT=\$PREV_GIT_COMMIT" >> ../rollback-info.env
                        echo "export PREVIOUS_DEPLOY_DURATION=\$PREV_DEPLOY_DURATION" >> ../rollback-info.env

                        yq eval -i '(.spec.template.spec.containers[0].image) = "${REGISTRY}:${IMAGE_TAG}"' deployment.yaml
                        yq eval -i '(.spec.template.spec.containers[0].env[] | select(.name == "BUILD_NUMBER") | .value) = "${env.BUILD_NUMBER}"' deployment.yaml
                        yq eval -i '(.spec.template.spec.containers[0].env[] | select(.name == "GIT_COMMIT") | .value) = "${env.GIT_COMMIT_SHORT}"' deployment.yaml
                        yq eval -i '(.spec.template.spec.containers[0].env[] | select(.name == "DEPLOY_DURATION_SECONDS") | .value) = "${env.DEPLOY_DURATION_SECONDS}"' deployment.yaml

                        git config user.email "jenkins@chaosarena.local"
                        git config user.name "jenkins-ci"
                        git add deployment.yaml
                        git commit -m "chaos-demo: bump to ${IMAGE_TAG} (build #${env.BUILD_NUMBER}, ${env.GIT_COMMIT_SHORT})" || echo "변경 없음, 커밋 스킵"
                        # KR1/KR2 두 Jenkins가 같은 main 브랜치에(서로 다른 폴더지만) 각자 커밋하므로,
                        # 하필 비슷한 시각에 겹치면 논-패스트포워드로 push가 거부될 수 있다. pull --rebase를
                        # 한 번만 하고 push하면 그 "확인 후 실행" 사이의 틈에 남이 또 push할 수 있어 여전히
                        # 실패할 수 있음을 실제로 겪었다(KR1/KR2 동시 빌드 재현 시) — 그래서 push 실패 시
                        # 다시 rebase하고 재시도하는 루프로 감싼다.
                        git pull --rebase origin main
                        for i in 1 2 3 4 5; do
                            git push origin main && break
                            echo "push 거부됨(다른 리전이 먼저 push) - \$i번째 재시도 전 재동기화"
                            sleep \$((RANDOM % 3 + 1))
                            git pull --rebase origin main
                        done
                    """
                }
            }
        }

        stage('Verify Deployment') {
            // ArgoCD가 방금 커밋을 감지해 실제로 반영했는지 확인한다. Jenkins는 클러스터 접근 권한이
            // 없으므로(GitOps 전환 때 의도적으로 제거, PROJECT_LOG 4.22절) kubectl이나 ArgoCD API가
            // 아니라 앱 자신의 /api/status를 클러스터 내부 Service DNS로 직접 호출해서 확인한다 — 새
            // 권한이 전혀 필요 없다. /health만 보면 안 되는 이유: 롤링 업데이트 중엔 구버전 파드가 아직
            // 응답할 수 있어서 /health는 계속 200이 나온다. build_number가 방금 push한 값과 일치하는지
            // 까지 확인해야 "새 버전이 실제로 응답 중"이라는 게 증명된다.
            steps {
                container('git') {
                    script {
                        def endpoint = "http://chaos-demo-nodeport.default.svc.cluster.local/api/status"
                        def healthy = false
                        for (int i = 0; i < 12; i++) {
                            def status = sh(
                                script: "wget -qO- --timeout=5 ${endpoint} || echo 'UNREACHABLE'",
                                returnStdout: true
                            ).trim()
                            def compact = status.replaceAll(/\s+/, "")
                            if (compact.contains('"build_number":"' + env.BUILD_NUMBER + '"')) {
                                healthy = true
                                break
                            }
                            sleep 10
                        }

                        if (healthy) {
                            // 배포 히스토리 타임라인용 성공 이벤트를 한 줄 기록한다(JSON Lines, 최신이 맨 위).
                            // history.jsonl 자체가 아직 없으면(최초 부트스트랩 전) yq가 에러를 내므로,
                            // deploy-history-configmap.yaml은 반드시 미리 레포에 존재해야 한다
                            // (docs/SETUP_GUIDE.md 참고, 최초 1회만 사용자가 직접 push).
                            sh """
                                cd manifests-repo/${MANIFESTS_PATH}

                                TIMESTAMP=\$(date -u +%Y-%m-%dT%H:%M:%SZ)
                                NEW_LINE='{"build_number":"${env.BUILD_NUMBER}","git_commit":"${env.GIT_COMMIT_SHORT}","status":"success","timestamp":"'"\$TIMESTAMP"'"}'

                                CURRENT_HISTORY=\$(yq eval '.data["history.jsonl"] // ""' deploy-history-configmap.yaml)
                                export NEW_HISTORY=\$({ echo "\$NEW_LINE"; echo "\$CURRENT_HISTORY"; } | head -n 10)
                                yq eval -i '.data["history.jsonl"] = strenv(NEW_HISTORY)' deploy-history-configmap.yaml

                                git add deploy-history-configmap.yaml
                                git commit -m "history: chaos-demo build #${env.BUILD_NUMBER} 배포 성공 기록" || echo "변경 없음, 커밋 스킵"
                                git pull --rebase origin main
                                for i in 1 2 3 4 5; do
                                    git push origin main && break
                                    echo "push 거부됨(다른 리전이 먼저 push) - \$i번째 재시도 전 재동기화"
                                    sleep \$((RANDOM % 3 + 1))
                                    git pull --rebase origin main
                                done
                            """
                        }

                        if (!healthy) {
                            echo "배포 후 약 2분 동안 build_number가 ${env.BUILD_NUMBER}로 바뀌지 않음 — 이전 버전으로 롤백합니다."
                            sh """
                                cd manifests-repo/${MANIFESTS_PATH}
                                source ../rollback-info.env

                                yq eval -i '(.spec.template.spec.containers[0].image) = strenv(PREVIOUS_IMAGE)' deployment.yaml
                                yq eval -i '(.spec.template.spec.containers[0].env[] | select(.name == "BUILD_NUMBER") | .value) = strenv(PREVIOUS_BUILD_NUMBER)' deployment.yaml
                                yq eval -i '(.spec.template.spec.containers[0].env[] | select(.name == "GIT_COMMIT") | .value) = strenv(PREVIOUS_GIT_COMMIT)' deployment.yaml
                                yq eval -i '(.spec.template.spec.containers[0].env[] | select(.name == "DEPLOY_DURATION_SECONDS") | .value) = strenv(PREVIOUS_DEPLOY_DURATION)' deployment.yaml

                                # 배포 히스토리 타임라인용 롤백 이벤트도 같은 커밋에 같이 기록한다.
                                TIMESTAMP=\$(date -u +%Y-%m-%dT%H:%M:%SZ)
                                NEW_LINE='{"build_number":"${env.BUILD_NUMBER}","git_commit":"${env.GIT_COMMIT_SHORT}","status":"rollback","recovered_build":"'"\$PREVIOUS_BUILD_NUMBER"'","timestamp":"'"\$TIMESTAMP"'"}'
                                CURRENT_HISTORY=\$(yq eval '.data["history.jsonl"] // ""' deploy-history-configmap.yaml)
                                export NEW_HISTORY=\$({ echo "\$NEW_LINE"; echo "\$CURRENT_HISTORY"; } | head -n 10)
                                yq eval -i '.data["history.jsonl"] = strenv(NEW_HISTORY)' deploy-history-configmap.yaml

                                git add deployment.yaml deploy-history-configmap.yaml
                                git commit -m "ROLLBACK: chaos-demo build #${env.BUILD_NUMBER} 헬스체크 실패, build #\$PREVIOUS_BUILD_NUMBER로 복구"
                                git pull --rebase origin main
                                for i in 1 2 3 4 5; do
                                    git push origin main && break
                                    echo "push 거부됨(다른 리전이 먼저 push) - \$i번째 재시도 전 재동기화"
                                    sleep \$((RANDOM % 3 + 1))
                                    git pull --rebase origin main
                                done
                            """
                            error("배포 후 헬스체크 실패 — 이전 빌드로 자동 롤백 커밋을 push했습니다.")
                        }
                    }
                }
            }
        }
    }
}
