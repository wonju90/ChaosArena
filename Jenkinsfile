// Jenkins CI/CD 파이프라인 — push 시 Kaniko 빌드+push → cosign 서명까지만 담당(CI).
// 배포(CD)는 여기서 kubectl로 직접 하지 않고, ChaosArena-manifests 레포에 이미지 태그를 커밋+푸시하면
// 클러스터 안의 ArgoCD가 그 변경을 감지해서 스스로 반영한다(GitOps, Pull 모델).
// 배경/설계 근거는 docs/PROJECT_LOG.md 3.5절, docs/CONCEPTS.md 11~13절·Push vs Pull 절 참고.

def REGISTRY = "55901daa-kr1-registry.container.nhncloud.com/chaosarena-registry/chaos-arena"
def IMAGE_TAG = "jenkins-${env.BUILD_NUMBER}"
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
                        cd manifests-repo/argocd-managed

                        yq eval -i '(.spec.template.spec.containers[0].image) = "${REGISTRY}:${IMAGE_TAG}"' deployment.yaml
                        yq eval -i '(.spec.template.spec.containers[0].env[] | select(.name == "BUILD_NUMBER") | .value) = "${env.BUILD_NUMBER}"' deployment.yaml
                        yq eval -i '(.spec.template.spec.containers[0].env[] | select(.name == "GIT_COMMIT") | .value) = "${env.GIT_COMMIT_SHORT}"' deployment.yaml
                        yq eval -i '(.spec.template.spec.containers[0].env[] | select(.name == "DEPLOY_DURATION_SECONDS") | .value) = "${env.DEPLOY_DURATION_SECONDS}"' deployment.yaml

                        git config user.email "jenkins@chaosarena.local"
                        git config user.name "jenkins-ci"
                        git add deployment.yaml
                        git commit -m "chaos-demo: bump to ${IMAGE_TAG} (build #${env.BUILD_NUMBER}, ${env.GIT_COMMIT_SHORT})" || echo "변경 없음, 커밋 스킵"
                        git push origin main
                    """
                }
            }
        }
    }
}
