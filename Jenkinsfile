pipeline {
    agent any
    environment {
        HARBOR_CREDS = credentials("harbor")
    }
    stages {
        stage('构建镜像') {
            steps {
                sh "docker build -t 192.168.234.120/wang/flask-app:latest ."
            }
        }
        stage('推送到 Harbor') {
            steps {
                sh "docker login 192.168.234.120 -u admin -p Harbor12345"
                sh "docker push 192.168.234.120/wang/flask-app:latest"
            }
        }
        stage('部署到 K8s') {
            steps {
                sh "kubectl apply -f deployment.yaml"
                sh "kubectl set image deployment/flask-app flask-app=192.168.234.120/wang/flask-app:latest"
            }
        }
    }
}