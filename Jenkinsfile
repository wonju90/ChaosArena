// Jenkins CI/CD 파이프라인 — push 시 Kaniko 빌드+push → cosign 서명 → kubectl 배포까지 완전 자동화.
// 배경/설계 근거는 docs/PROJECT_LOG.md 3.5절, docs/CONCEPTS.md 11~13절 참고.

def REGISTRY = "55901daa-kr1-registry.container.nhncloud.com/chaosarena-registry/chaos-arena"
def IMAGE_TAG = "jenkins-${env.BUILD_NUMBER}"

pipeline {
    agent {
        kubernetes {
            yaml """
apiVersion: v1
kind: Pod
spec:
  serviceAccountName: jenkins-deployer
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
    - name: kubectl
      # bitnami/kubectl:1.33처럼 짧은 태그는 Bitnami의 카탈로그 개편(2025)으로 더 이상 존재하지 않음.
      # 예전 무료 이미지는 bitnamilegacy 네임스페이스의 전체 버전 태그로 옮겨짐.
      image: bitnamilegacy/kubectl:1.33.4-debian-12-r0
      command: ["cat"]
      tty: true
      # Bitnami 이미지는 기본적으로 non-root로 뜨는데, 그 상태에서는 Jenkins가 워크스페이스에
      # 실행 스크립트를 쓰지 못해 "process apparently never started"가 난다(cosign 스테이지와 동일 원인).
      securityContext:
        runAsUser: 0
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

        stage('Deploy') {
            steps {
                script {
                    // checkout scm이 채워주는 전체 커밋 해시를 화면 표시용으로 짧게 자른다.
                    env.GIT_COMMIT_SHORT = env.GIT_COMMIT ? env.GIT_COMMIT.take(7) : "unknown"
                    // Checkout 스테이지 시작 시점부터 지금까지 걸린 시간(초) = 이번 빌드의 "배포 랭크" 소재.
                    env.DEPLOY_DURATION_SECONDS = ((System.currentTimeMillis() - env.PIPELINE_START_MS.toLong()) / 1000).toInteger().toString()
                }
                container('kubectl') {
                    sh """
                        KUBE_TOKEN=\$(cat /var/run/secrets/kubernetes.io/serviceaccount/token)
                        KUBE_CA=/var/run/secrets/kubernetes.io/serviceaccount/ca.crt
                        KUBECTL="kubectl --server=https://kubernetes.default.svc --certificate-authority=\$KUBE_CA --token=\$KUBE_TOKEN -n default"

                        \$KUBECTL set image deployment/chaos-demo chaos-demo=${REGISTRY}:${IMAGE_TAG}
                        \$KUBECTL set env deployment/chaos-demo BUILD_NUMBER=${env.BUILD_NUMBER} GIT_COMMIT=${env.GIT_COMMIT_SHORT} DEPLOY_DURATION_SECONDS=${env.DEPLOY_DURATION_SECONDS}
                        \$KUBECTL rollout status deployment/chaos-demo --timeout=180s
                    """
                }
            }
        }
    }
}
