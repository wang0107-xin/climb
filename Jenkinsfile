def label = "jenkins-slave-${UUID.randomUUID().toString()}"

podTemplate(
    label: label,
    containers: [
        containerTemplate(name: 'docker', image: 'docker:latest', command: 'cat', ttyEnabled: true),
        containerTemplate(name: 'kubectl', image: 'cnych/kubectl:latest', command: 'cat', ttyEnabled: true)
    ],
    volumes: [hostPathVolume(mountPath: '/var/run/docker.sock', hostPath: '/var/run/docker.sock')]
) {

node(label) {
    def IMAGE_NAME = "192.168.234.120:80/wang/flask-app:latest"

    stage('拉取代码') { checkout scm }

    stage('构建镜像') {
        container('docker') { sh "docker build -t ${IMAGE_NAME} ." }
    }

    stage('推送到 Harbor') {
        container('docker') {
            withCredentials([usernamePassword(credentialsId: 'harbor', usernameVariable: 'USER', passwordVariable: 'PWD')]) {
                sh "docker login 192.168.234.120:80 -u ${USER} -p ${PWD}"
                sh "docker push ${IMAGE_NAME}"
            }
        }
    }

    stage('部署到 K8s') {
        container('kubectl') {
            withCredentials([file(credentialsId: 'kubeconfig', variable: 'KUBECONFIG_FILE')]) {
                sh '''
                    mkdir -p ~/.kube
                    cp "${KUBECONFIG_FILE}" ~/.kube/config
                    chmod 600 ~/.kube/config
                    kubectl apply -f deployment.yaml
                '''
            }
        }
    }

    stage('登出清理') {
        container('docker') { sh "docker logout 192.168.234.120:80" }
    }
}
}