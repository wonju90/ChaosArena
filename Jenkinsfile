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
      image: curlimages/curl:8.11.0
      command: ["cat"]
      tty: true
      env:
        - name: DOCKER_CONFIG
          value: /home/curl_user/.docker
        - name: COSIGN_PASSWORD
          valueFrom:
            secretKeyRef:
              name: cosign-key
              key: password
      volumeMounts:
        - name: ncr-auth
          mountPath: /home/curl_user/.docker
        - name: cosign-key
          mountPath: /mnt/cosign-key
    - name: kubectl
      # bitnami/kubectl:1.33처럼 짧은 태그는 Bitnami의 카탈로그 개편(2025)으로 더 이상 존재하지 않음.
      # 예전 무료 이미지는 bitnamilegacy 네임스페이스의 전체 버전 태그로 옮겨짐.
      image: bitnamilegacy/kubectl:1.33.4-debian-12-r0
      command: ["cat"]
      tty: true
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
                        curl -sSL -o /tmp/cosign https://github.com/sigstore/cosign/releases/download/v2.4.1/cosign-linux-amd64
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
                container('kubectl') {
                    sh """
                        KUBE_TOKEN=\$(cat /var/run/secrets/kubernetes.io/serviceaccount/token)
                        KUBE_CA=/var/run/secrets/kubernetes.io/serviceaccount/ca.crt
                        KUBECTL="kubectl --server=https://kubernetes.default.svc --certificate-authority=\$KUBE_CA --token=\$KUBE_TOKEN -n default"

                        \$KUBECTL set image deployment/chaos-demo chaos-demo=${REGISTRY}:${IMAGE_TAG}
                        \$KUBECTL rollout status deployment/chaos-demo --timeout=180s
                    """
                }
            }
        }
    }
}
