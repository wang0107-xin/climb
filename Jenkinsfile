def label = "slave-${UUID.randomUUID().toString()}"

// =====================================================================
// 开关区
//
// 每个环节都留一个开关，这是刻意的：出误报时改这里一个值就能关掉那一环，
// 而不是回滚整个流水线。一次加一堆卡点 → 流水线天天红 → 所有人学会忽略它。
// =====================================================================
def MIRROR_AGENT_IMAGES   = false  // 三个 agent 容器是否也走 Harbor（先确认 Harbor 里有这 3 个镜像）
def RUN_UNIT_TESTS        = true
def RUN_SMOKE_TEST        = true
def SMOKE_REAL_CRAWL      = false  // 冒烟是否真打两次抓取（第二次走缓存路径）：需要 QA 有公网出口，会慢 20s+
def ENFORCE_QUALITY_GATE  = false  // 阶段 1.3：观察期只汇总不阻断，调好误报后改 true
def ENABLE_NOTIFY         = false  // 阶段 1.4：通知渠道还没定，先关
def CLEAN_WORKSPACE       = true   // 阶段 0.2：构建结束清工作区
def PRUNE_DANGLING_IMAGES = true   // 阶段 1：回收被覆盖的旧镜像层
def KEEP_BUILDS           = 10     // 阶段 0.5：保留最近 N 次构建
def KEEP_DAYS             = 7      // 阶段 0.5：保留 N 天
def PIP_INDEX             = 'https://pypi.tuna.tsinghua.edu.cn/simple'

// =====================================================================
// 环境配置区：按你的环境改
// =====================================================================
def registryUrl   = '192.168.234.120:80'   // Harbor
def imageName     = 'wang/flask-app'       // 业务镜像名，要和 manifest 里的名字一致
def k8sDeployment = 'wang-flask-app'
def k8sContainer  = 'wang-flask-app'
def k8sService    = 'wang-flask-app'
def projectDir    = '.'

// 阶段 0.1 分支指向：哪个分支部署到哪个环境。
// 不在这张表里的分支（feature/* 之类）只构建、不部署 —— 这是刻意的，
// 免得随便一个分支都能往生产推。
def branchTargets = [
  'dev'   : [ns: 'qa',      manifest: 'k8s/qa/app.yaml', label: 'QA'],
  'main'  : [ns: 'default', manifest: 'k8s.yaml',        label: '生产'],
  'master': [ns: 'default', manifest: 'k8s.yaml',        label: '生产'],
]

// 阶段 0.3 镜像内网化。
// 基础镜像 Harbor 里已经有（library/python:3.9-slim），所以这里**不需要推任何镜像**，
// 只是把引用指过去。三个 agent 容器默认还走公网：确认 Harbor 里有对应镜像后，
// 把 MIRROR_AGENT_IMAGES 改成 true；那些镜像要能被拉下来，还需要
// harbor-pull secret 挂在 jenkins 这个 ServiceAccount 上（见 docs/stage0-runbook.md）。
def imgPython  = "${registryUrl}/library/python:3.9-slim"
def imgJnlp    = MIRROR_AGENT_IMAGES ? "${registryUrl}/library/inbound-agent:jdk21" : 'jenkins/inbound-agent:jdk21'
def imgDocker  = MIRROR_AGENT_IMAGES ? "${registryUrl}/library/docker:27-cli"      : 'docker:latest'
def imgKubectl = MIRROR_AGENT_IMAGES ? "${registryUrl}/library/kubectl:latest"     : 'cnych/kubectl'


// 阶段 1.4 通知。默认不启用；渠道定下来后：
//   1. Jenkins 里新建 secret text 凭据，ID 填 dingtalk-webhook，值是完整 webhook 地址
//   2. 把 ENABLE_NOTIFY 改成 true
// 整个函数包在 try/catch 里：通知发不出去绝不能把构建搞红。
def notify(String status, String branch, String imageTag) {
  try {
    container('python') {
      withCredentials([string(credentialsId: 'dingtalk-webhook', variable: 'NOTIFY_WEBHOOK')]) {
        sh """
          NOTIFY_CHANNEL=dingtalk \\
          NOTIFY_WEBHOOK="\$NOTIFY_WEBHOOK" \\
          NOTIFY_STATUS="${status}" \\
          NOTIFY_JOB="${env.JOB_NAME}" \\
          NOTIFY_BUILD="${env.BUILD_NUMBER}" \\
          NOTIFY_BRANCH="${branch}" \\
          NOTIFY_IMAGE="${imageTag}" \\
          NOTIFY_URL="${env.BUILD_URL}" \\
          python ci/notify.py || true
        """
      }
    }
  } catch (e) {
    echo "[warn] 通知发送失败（不影响构建结果）：${e}"
  }
}


podTemplate(label: label, containers: [
  containerTemplate(name: 'jnlp', image: imgJnlp),
  // 本项目是 Python Flask。原来这里是 okteto/golang.1.17 + go build，
  // 但项目里没有任何 .go 文件，所以必然失败
  containerTemplate(name: 'python', image: imgPython, command: 'cat', ttyEnabled: true,
    resourceRequestCpu: '200m', resourceRequestMemory: '256Mi',
    resourceLimitCpu: '1000m',   resourceLimitMemory: '1Gi'),
  containerTemplate(name: 'docker', image: imgDocker, command: 'cat', ttyEnabled: true,
    resourceRequestCpu: '100m', resourceRequestMemory: '256Mi',
    resourceLimitCpu: '1000m',   resourceLimitMemory: '512Mi'),
  containerTemplate(name: 'kubectl', image: imgKubectl, command: 'cat', ttyEnabled: true,
    resourceRequestCpu: '100m', resourceRequestMemory: '128Mi',
    resourceLimitCpu: '500m',    resourceLimitMemory: '256Mi')
], serviceAccount: 'jenkins', volumes: [
  hostPathVolume(mountPath: '/var/run/docker.sock', hostPath: '/var/run/docker.sock')
]) {
  node(label) {

    def myRepo, shortSha, image, branchName, target
    def deployed = false

    // 阶段 0.5 磁盘基线：构建记录保留策略。
    // 小硬盘的流水线首先死于磁盘满，而不是死于功能。这里配不上（权限不够）也不影响构建。
    try {
      properties([buildDiscarder(logRotator(numToKeepStr: "${KEEP_BUILDS}", daysToKeepStr: "${KEEP_DAYS}"))])
    } catch (e) {
      echo "[warn] 保留策略没配上（需要 Job 配置权限），去 Jenkins 任务里手动设：${e}"
    }

    try {

      stage('拉取代码') {
        myRepo = checkout scm
        branchName = (env.BRANCH_NAME ?: myRepo.GIT_BRANCH ?: 'dev').replaceFirst('^origin/', '')
        target = branchTargets[branchName]
        shortSha = myRepo.GIT_COMMIT.take(7)
        image = "${registryUrl}/${imageName}:${shortSha}"
        echo """分支      : ${branchName}
提交      : ${shortSha}
目标环境  : ${target ? target.label + '（namespace=' + target.ns + '）' : '仅构建，不部署'}
本次镜像  : ${image}"""
      }


      stage('安装依赖与语法检查') {
        container('python') {
          dir(projectDir) {
            sh """
              set -e
              mkdir -p reports
              pip install --no-cache-dir -r requirements.txt ${RUN_UNIT_TESTS ? '-r requirements-dev.txt' : ''} -i ${PIP_INDEX}

              echo "--- 语法检查 ---"
              python -m compileall -q app wsgi.py ci

              echo "--- 应用能否导入并初始化 ---"
              # 必须用文件型 SQLite。config.py 的 SQLALCHEMY_ENGINE_OPTIONS 里设了 pool_size，
              # 而 :memory: 用的是 StaticPool，不接受 pool_size，会直接 TypeError
              DATABASE_URL=sqlite:////tmp/ci-smoke.db SECRET_KEY=ci-smoke-test \\
                python -c "from app import create_app; create_app('production'); print('[OK] app init success')"
            """
          }
        }
      }


      stage('单元测试') {
        if (RUN_UNIT_TESTS) {
          container('python') {
            dir(projectDir) {
              sh '''
                set -e
                mkdir -p reports
                python -m pytest -q
              '''
            }
          }
        } else {
          echo '[跳过] RUN_UNIT_TESTS=false'
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
        if (target == null) {
          echo "[跳过] 分支 ${branchName} 不在 branchTargets 里，只构建不部署"
        } else {
          container('kubectl') {
            withCredentials([file(credentialsId: 'kubeconfig-shengchan', variable: 'KUBECONFIG')]) {
              dir(projectDir) {
                // KUBECONFIG 已经指向配置文件，kubectl 会自动读，不需要再 cp 到 ~/.kube/config
                sh """
                  set -e
                  kubectl apply -f ${target.manifest} -n ${target.ns}
                  kubectl set image deployment/${k8sDeployment} ${k8sContainer}=${image} -n ${target.ns}
                  kubectl rollout status deployment/${k8sDeployment} -n ${target.ns} --timeout=180s
                """
              }
            }
          }
          deployed = true
        }
      }


      stage('节点冒烟') {
        if (RUN_SMOKE_TEST && deployed) {
          // 1) kubectl 容器：把"实际部署成了什么"落盘，顺便算出集群内的 Service 地址。
          //    同一 Pod 里各容器共享工作区，所以用文件把参数传给 python 容器。
          container('kubectl') {
            withCredentials([file(credentialsId: 'kubeconfig-shengchan', variable: 'KUBECONFIG')]) {
              dir(projectDir) {
                // 不用 heredoc：Groovy 字符串里的缩进会让 heredoc 结束符匹配不上
                sh """
                  set -e
                  mkdir -p reports
                  NS="${target.ns}"; DEP="${k8sDeployment}"; SVC="${k8sService}"
                  ACTUAL_IMAGE=\$(kubectl get deploy/\$DEP -n \$NS -o jsonpath='{.spec.template.spec.containers[0].image}')
                  READY=\$(kubectl get deploy/\$DEP -n \$NS -o jsonpath='{.status.readyReplicas}')
                  TOTAL=\$(kubectl get deploy/\$DEP -n \$NS -o jsonpath='{.spec.replicas}')
                  POD=\$(kubectl get pod -n \$NS -l app=\$DEP -o jsonpath='{.items[0].metadata.name}')
                  RESTARTS=\$(kubectl get pod -n \$NS -l app=\$DEP -o jsonpath='{.items[0].status.containerStatuses[0].restartCount}')
                  {
                    echo "DEPLOY_NS=\$NS"
                    echo "DEPLOY_SERVICE=\$SVC"
                    echo "DEPLOY_BASE_URL=http://\$SVC.\$NS.svc.cluster.local"
                    echo "DEPLOY_IMAGE=\$ACTUAL_IMAGE"
                    echo "DEPLOY_EXPECTED_IMAGE=${image}"
                    echo "DEPLOY_READY_REPLICAS=\${READY:-0}"
                    echo "DEPLOY_REPLICAS=\${TOTAL:-0}"
                    echo "DEPLOY_POD=\$POD"
                    echo "DEPLOY_RESTARTS=\${RESTARTS:-0}"
                  } > reports/deploy.env
                  cat reports/deploy.env
                """
              }
            }
          }
          // 2) python 容器：打真实业务路径。rollout status 只证明探针过了，
          //    这里证明的是"业务真的能响应"
          container('python') {
            dir(projectDir) {
              sh """
                set -e
                python ci/smoke_test.py ${SMOKE_REAL_CRAWL ? '--real-crawl' : ''}
              """
            }
          }
        } else {
          echo "[跳过] RUN_SMOKE_TEST=${RUN_SMOKE_TEST}，本次是否部署=${deployed}"
        }
      }


      // 阶段 1.3 质量门禁：汇总前面各环节的结果。
      // 放在所有验证环节之后；阶段 3 的制品晋升要接在它后面。
      stage('质量门禁') {
        container('python') {
          dir(projectDir) {
            sh """
              set -e
              mkdir -p reports
              python ci/quality_gate.py ${ENFORCE_QUALITY_GATE ? '--enforce' : ''}
            """
          }
        }
      }

    } catch (err) {
      currentBuild.result = 'FAILURE'
      echo "构建失败：${err}"
      throw err

    } finally {

      // 阶段 1.4 Post 收尾。脚本式流水线没有声明式那个 post 块，
      // 所以收尾逻辑挂在这里 —— finally 是异常安全的。
      stage('Post 收尾') {
        try {
          // 1) 归档。必须在清理之前：删了工作区就没东西可归档了
          dir(projectDir) {
            junit allowEmptyResults: true, testResults: 'reports/junit.xml'
            archiveArtifacts artifacts: 'reports/**', allowEmptyArchive: true
          }
        } catch (e) {
          echo "[warn] 归档失败（不影响构建结果）：${e}"
        }

        // 2) 通知（默认关）
        if (ENABLE_NOTIFY) {
          notify(currentBuild.result ?: 'SUCCESS', branchName ?: '-', image ?: '-')
        }

        // 3) 回收悬空镜像。放在清工作区之前：工作区删掉后容器 cwd 就没了，sh 会失败
        if (PRUNE_DANGLING_IMAGES) {
          try {
            container('docker') {
              sh 'docker image prune -f'
            }
          } catch (e) {
            echo "[warn] 镜像回收失败（不影响构建结果）：${e}"
          }
        }

        // 4) 清工作区（阶段 0.2）
        if (CLEAN_WORKSPACE) {
          deleteDir()
        }
      }
    }
  }
}
