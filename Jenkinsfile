def HARBOR_HOST = "192.168.234.120"
def PROJECT_NAME = "wang"
def IMAGE_NAME   = "flask-app"
def TAG          = "latest"
def FULL_IMAGE = "${HARBOR_HOST}/${PROJECT_NAME}/${IMAGE_NAME}:${TAG}"

pipeline {
    agent any
    environment {
        HARBOR_CREDS = credentials("harbor")
    }
    stages {
        stage('测试环境') {
            steps {
                sh 'whoami'
                sh 'ls -l /var/run/docker.sock'
            }
        }

        stage('构建镜像') {
            steps {
                sh '''
                docker build -t ${FULL_IMAGE} . || true
                '''
            }
        }
    }
}