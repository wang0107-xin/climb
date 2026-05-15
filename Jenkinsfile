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
    // 所有变量用 def 定义
    def HARBOR_CREDS = credentials("harbor")
    def IMAGE_NAME = "192.168.234.120:80/wang/flask-app:latest"

    // 第一步：拉代码
    stage('拉取代码') {
        checkout scm
    }

    // 第二步：构建镜像
    stage('构建镜像') {
        container('docker') {
            sh "docker build -t ${IMAGE_NAME} ."
        }
    }

    // 第三步：推送到 Harbor
    stage('推送到 Harbor') {
        container('docker') {
            sh "docker login 192.168.234.120:80 -u ${HARBOR_CREDS_USR} -p ${HARBOR_CREDS_PSW}"
            sh "docker push ${IMAGE_NAME}"
        }
    }

    // 第四步：部署到 K8s
    stage('部署到 K8s') {
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

    // 最后退出登录
    container('docker') {
        sh "docker logout 192.168.234.120:80"
    }
}
}