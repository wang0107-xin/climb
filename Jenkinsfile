def label = "slave-${UUID.randomUUID().toString()}"

podTemplate(label: label, containers: [
  containerTemplate(name: 'jnlp',    image: 'jenkins/inbound-agent:jdk21'),
  // 本项目是 Python Flask。原来这里是 okteto/golang.1.17 + go build，
  // 但项目里没有任何 .go 文件，所以必然失败
  containerTemplate(name: 'python',  image: 'python:3.9-slim', command: 'cat', ttyEnabled: true),
  containerTemplate(name: 'docker',  image: 'docker:latest',   command: 'cat', ttyEnabled: true),
  containerTemplate(name: 'kubectl', image: 'cnych/kubectl',   command: 'cat', ttyEnabled: true)
], serviceAccount: 'jenkins', volumes: [
  hostPathVolume(mountPath: '/var/run/docker.sock', hostPath: '/var/run/docker.sock')
]) {
  node(label) {

    // ============ 这几行按你的环境改 ============
    def registryUrl = '192.168.234.120:80'   // Harbor 地址
    def imageName   = 'wang/flask-app'       // 要和 deployment.yaml 里的镜像名一致
    def projectDir  = '.'                    // Jenkins 拉的就是 demo-project 这个仓库，工作区根目录即项目根目录
    def k8sDeployment = 'wang-flask-app'     // 要和 deployment.yaml 里的 Deployment 名一致
    def k8sContainer  = 'wang-flask-app'     // 要和 deployment.yaml 里的容器名一致
    // ==========================================

    def myRepo
    stage('拉取代码') {
      myRepo = checkout scm
    }

    def shortSha = myRepo.GIT_COMMIT.take(7)
    def image = "${registryUrl}/${imageName}:${shortSha}"
    echo "本次构建镜像：${image}"

    stage('安装依赖与检查') {
      container('python') {
        dir(projectDir) {
          sh '''
            set -e
            pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

            echo "--- 语法检查 ---"
            python -m compileall -q app wsgi.py

            echo "--- 冒烟测试：应用能否导入并初始化 ---"
            # 必须用文件型 SQLite。config.py 的 SQLALCHEMY_ENGINE_OPTIONS 里设了 pool_size，
            # 而 :memory: 用的是 StaticPool，不接受 pool_size，会直接 TypeError
            DATABASE_URL=sqlite:////tmp/ci-smoke.db SECRET_KEY=ci-smoke-test \
              python -c "from app import create_app; create_app('production'); print('[OK] app init success')"
          '''
        }
      }
    }


    stage('构建并推送镜像') {
      container('docker') {
        withCredentials([usernamePassword(credentialsId: 'harbor',
                                          usernameVariable: 'DOCKER_USER',
                                          passwordVariable: 'DOCKER_PASSWORD')]) {
          dir(projectDir) {
            // 镜像名不是密钥，用 Groovy 插值；账号密码用 \$ 转义，交给 shell 读环境变量，
            // --password-stdin 避免密码出现在进程列表里
            sh """
              set -e
              echo "\$DOCKER_PASSWORD" | docker login "${registryUrl}" -u "\$DOCKER_USER" --password-stdin
              docker build -t "${image}" .
              docker push "${image}"
            """
          }
        }
      }
    }

    stage('部署到 K8s') {
      container('kubectl') {
        withCredentials([file(credentialsId: 'kubeconfig-shengchan', variable: 'KUBECONFIG')]) {
          dir(projectDir) {
            // KUBECONFIG 已经指向配置文件，kubectl 会自动读，不需要再 cp 到 ~/.kube/config
            sh """
              set -e
              kubectl apply -f k8s.yaml
              kubectl set image deployment/${k8sDeployment} ${k8sContainer}=${image}
              kubectl rollout status deployment/${k8sDeployment} --timeout=180s
            """
          }
        }
      }
    }
  }
}
