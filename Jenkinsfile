// 定义你自己的 Harbor 信息（这是核心！）
def HARBOR_HOST = "192.168.234.120"
def PROJECT_NAME = "wang"
def IMAGE_NAME   = "flask-app"
def TAG          = "latest"  // 也可以用 ${BUILD_NUMBER}

// 最终完整镜像名
def FULL_IMAGE = "${HARBOR_HOST}/${PROJECT_NAME}/${IMAGE_NAME}:${TAG}"

pipeline {
    agent any
    environment {
        // Harbor 凭据（你 Jenkins 里的那个 Harbor 账号密码）
        HARBOR_CREDS = credentials("你Harbor的凭据ID")
    }
    stages {
        stage('构建镜像') {
            steps {
                sh 'docker build -t ${FULL_IMAGE} .'
            }
        }
        stage('推送到 Harbor') {
            steps {
                sh 'docker login ${HARBOR_HOST} -u ${HARBOR_CREDS_USR} -p ${HARBOR_CREDS_PSW}'
                sh 'docker push ${FULL_IMAGE}'
            }
        }
        stage('部署到 K8s') {
            steps {
                sh '''
                    kubectl apply -f deployment.yaml
                    kubectl set image deployment/flask-app flask-app=${FULL_IMAGE}
                '''
            }
        }
    }
}