def label = "jenkins-slave-${UUID.randomUUID().toString()}"

podTemplate(
    label: label,
    containers: [
        containerTemplate(
            name: 'docker',
            image: 'docker:latest',
            command: 'cat',
            ttyEnabled: true
        ),
        containerTemplate(
            name: 'kubectl',
            image: 'cnych/kubectl:latest',
            command: 'cat',
            ttyEnabled: true
        )
    ],
    volumes: [
        hostPathVolume(mountPath: '/var/run/docker.sock', hostPath: '/var/run/docker.sock')
    ]
) {

node(label) {
    environment {
        HARBOR_CREDS = credentials("harbor")
        IMAGE_NAME = "192.168.234.120:80/wang/flask-app:latest"
    }

    stages {
        stage('拉取代码') {
            steps {
                checkout scm
            }
        }

        stage('构建镜像') {
            steps {
                container('docker') {
                    sh "docker build -t ${IMAGE_NAME} ."
                }
            }
        }

        stage('推送到 Harbor') {
            steps {
                container('docker') {
                    sh "docker login 192.168.234.120:80 -u ${HARBOR_CREDS_USR} -p ${HARBOR_CREDS_PSW}"
                    sh "docker push ${IMAGE_NAME}"
                }
            }
        }

        stage('部署到 K8s') {
            steps {
                container('kubectl') {
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
    }

    post {
        always {
            container('docker') {
                sh "docker logout 192.168.234.120:80"
            }
        }
    }
}
}