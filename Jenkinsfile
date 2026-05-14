pipeline {
    agent any
    environment {
        HARBOR_CREDS = credentials("harbor")
        IMAGE_NAME = "192.168.234.120:80/wang/flask-app:latest"
    }
    stages {
        stage('构建镜像') {
            steps {
                sh "docker build -t ${IMAGE_NAME} ."
            }
        }
        stage('推送到 Harbor') {
            steps {
                sh "docker login 192.168.234.120:80 -u ${HARBOR_CREDS_USR} -p ${HARBOR_CREDS_PSW}"
                sh "docker push ${IMAGE_NAME}"
            }
        }

        stage('部署到 K8s') {
            steps {
                withCredentials([file(credentialsId: 'kubeconfig', variable: 'KUBECONFIG_FILE')]) {
                    sh '''
                        mkdir -p ~/.kube
                        cp "${KUBECONFIG_FILE}" ~/.kube/config
                        chmod 600 ~/.kube/config

                        kubectl apply -f deployment.yaml
                        kubectl set image deployment/flask-app flask-app=${IMAGE_NAME}
                    '''
                }
            }
        }
    }
    post {
        always {
            sh "docker logout 192.168.234.120:80"
        }
    }
}