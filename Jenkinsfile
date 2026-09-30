def label = "slave-${UUID.randomUUID().toString()}"

// =====================================================================
// 开关区
//
// 每个环节都留一个开关，这是刻意的：出误报时改这里一个值就能关掉那一环，
// 而不是回滚整个流水线。一次加一堆卡点 → 流水线天天红 → 所有人学会忽略它。
// =====================================================================
def MIRROR_AGENT_IMAGES   = false  // 三个 agent 容器是否也走 Harbor（先确认 Harbor 里有这 3 个镜像）
def RUN_UNIT_TESTS        = true
def RUN_RUFF              = true   // 阶段 2.1：静态分析（这个 stage 自己不阻断，但门禁会）
def RUN_BANDIT            = true   // 阶段 2.2：安全扫描（同上）
def RUN_SMOKE_TEST        = true
def SMOKE_REAL_CRAWL      = false  // 冒烟是否真打两次抓取（第二次走缓存路径）：需要 QA 有公网出口，会慢 20s+
def ENFORCE_QUALITY_GATE  = true   // 阶段 1.3：2026-09-30 翻开关 —— 门禁表里任何一条 ❌ 从此真的把构建判红
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
// 这张表要和**远端实际存在的分支**一致 —— 本仓库远端只有 dev 和 main（`git ls-remote --heads`）。
// 别出于"保险"把 master 加回来：这个仓库早期默认分支叫 master，后来改成了 main，
// 而 Jenkins 工作区里可能还留着陈旧的 origin/master 引用（git fetch 不带 --prune 不会清理
// 已被删除的分支）。把它写进这张表，会让一个远端已经不存在的分支看起来还能构建。
// 不在这张表里的分支（feature/* 之类）只构建、不部署 —— 这是刻意的，
// 免得随便一个分支都能往生产推。
def branchTargets = [
  'dev' : [ns: 'qa',      manifest: 'k8s/qa/app.yaml',   label: 'QA'],
  'main': [ns: 'default', manifest: 'k8s/main/k8s.yaml', label: '生产'],
]

// 阶段 0.3 镜像内网化。
// 基础镜像 Harbor 里已经有（library/python:3.9-slim），所以这里**不需要推任何镜像**，
// 只是把引用指过去。三个 agent 容器默认还走公网：确认 Harbor 里有对应镜像后，
// 把 MIRROR_AGENT_IMAGES 改成 true；那些镜像要能被拉下来，还需要
// harbor-pull secret 挂在 jenkins 这个 ServiceAccount 上（见 docs/stage0-runbook.md 的 0.3）。
//
// 每组的公网坐标和 Harbor 坐标写在相邻两行、**tag 刻意保持一致**：
// 翻这个开关时变的应该只是"从哪儿拉"，不该顺手把版本也换了。
// （原来 docker 那行公网写 :latest、Harbor 写 27-cli，就是这种对不上的隐患。）
//
// docker 从 :latest 钉成 27-cli，理由是"同一个东西不能有两个答案"：
// 否则出事时没人说得清跑的是哪个版本，升级也从来不是谁主动决定的。
//
// ⚠️ 但改 tag 是有代价的：节点上没有这个 tag，kubelet 就得现拉一次。
//    实测踩过 —— 改成 27-cli 后第一次构建，容器卡在 ContainerCreating 十几分钟，
//    插件等满 1000 秒超时、放弃、建了第二个 Pod 才好（那时镜像刚拉完，
//    事件里写的已经是 already present on machine，看起来像"跟拉镜像无关"）。
//    所以：tag 定下来就别来回改；非改不可，先在节点上把新镜像拉好（见 docs/stage0-runbook.md 0.3）。
//    另外别拿"latest 会被强制 imagePullPolicy=Always"当理由 —— 实测这个 Pod 里四个容器
//    都是插件自己设的 IfNotPresent，跟 tag 是不是 latest 无关。
def imgPython  = "${registryUrl}/library/python:3.9-slim"
def imgJnlp    = MIRROR_AGENT_IMAGES ? "${registryUrl}/library/inbound-agent:jdk21" : 'jenkins/inbound-agent:jdk21'
def imgDocker  = MIRROR_AGENT_IMAGES ? "${registryUrl}/library/docker:27-cli"       : 'docker:27-cli'
def imgKubectl = MIRROR_AGENT_IMAGES ? "${registryUrl}/library/kubectl:latest"      : 'cnych/kubectl:latest'



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


// agent Pod 的命名空间必须写死在这里。
// 不写 namespace 时它跟随 Jenkins 云配置（那台配的是 default），而下面 serviceAccount 用的
// 'jenkins' 住在 devops。K8s 的 ServiceAccount 准入要求 SA 和 Pod 同命名空间，对不上就直接
// 拒绝创建 Pod（serviceaccount "jenkins" not found），构建卡在起 Pod 那一步、走不到后面的 stage。
// 也不能图省事在 default 里再建一个同名 SA —— 0.3 的 harbor-pull 是挂在这个 SA 上的，
// 两个命名空间各一个 jenkins 以后必然指错。
// 定了 devops 之后，docs/stage0-runbook.md 里 0.3 那条 patch 的 <agent 命名空间> 就是 devops。
//
// podRetention: never() —— 构建一结束就把 agent Pod 删掉。
// 不写这一行，插件默认是 `Always`（留着），于是每构建一次就在 devops 里堆一个
// `Completed` 状态的 slave-xxx Pod；每个 Pod 还带着它的 emptyDir 工作区
// （checkout 出来的代码 + __pycache__ + reports），一直占着节点磁盘 ——
// 而这台机器最紧的就是磁盘。这就是验收「连续跑 10 次磁盘不持续增长」过不去的一半原因。
//   never()     → 构建结束立刻删（现在选这个，小硬盘优先）
//   minutes(5)  → 留 5 分钟让你进去看现场，之后自己走
//   onFailure() → 只在红的构建上留现场
// 如果这行报 `No such DSL method 'never' found`（这版插件没有该 DSL），
// 就把这行删掉，去 Jenkins → 系统管理 → 云 → Kubernetes → Pod Retention 改成 Never。
podTemplate(label: label, namespace: 'devops', podRetention: never(), containers: [
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


      // 阶段 2.1 + 2.2 + 2.3：静态分析与安全扫描，**放同一个并行块**。
      // 位置在"构建并推送镜像"之前 —— 这就是"左移"的含义：在产出制品之前先扫代码。
      //
      // 两者放一起不是图省事，是因为它们本来就该并行：互不依赖、都是秒级，
      // 串起来只是白等。规划里也写着这一条 —— 它们要一起加，分两次加等于把并行结构
      // 拆了再加回来。
      //
      // ⚠️ 并行 + container() 在个别 kubernetes-plugin 版本上会偶发卡死，所以这一组合
      //    只被验证过**一次**（构建 #48 是串行版跑绿的，它没有验证并行）。
      //    排查"agent 上线后流水线一步不走"时确认过：那次的病因在节点侧
      //    （Pod 1000 秒起不来 + node body 不动），**根本没执行到这个 stage**。
      //    所以不为此付"连绿 3 次"的代价，直接用一次构建验它：
      //      绿   → 并行成立，留着；
      //      卡住 → 把下面两个分支拆成串行（各起一个 container('python') 块），
      //             那是已验证过的形态（#48）。两个扫描各 1 秒，串行不花时间。
      //
      // 观察期：ci/static_analysis.py 发现问题也返回 0，条数交给后面的「质量门禁」汇总，
      // 所以这里不会因为"代码有告警"而红。真正会红的是**工具自己没跑起来**（退出码非 0）——
      // 那种情况必须红：否则报告是空的，门禁会当成"这一环没启用"，一路绿着过去。
      stage('静态分析与安全扫描（并行）') {
        if (RUN_RUFF || RUN_BANDIT) {
          def scans = [:]
          if (RUN_RUFF) {
            scans['静态分析 ruff'] = {
              container('python') {
                dir(projectDir) { sh 'python ci/static_analysis.py ruff' }
              }
            }
          }
          if (RUN_BANDIT) {
            scans['安全扫描 bandit'] = {
              container('python') {
                dir(projectDir) { sh 'python ci/static_analysis.py bandit' }
              }
            }
          }
          parallel(scans)
        } else {
          echo "[跳过] RUN_RUFF=${RUN_RUFF}，RUN_BANDIT=${RUN_BANDIT}"
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
            withCredentials([file(credentialsId: 'kubeconfig', variable: 'KUBECONFIG')]) {
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
            withCredentials([file(credentialsId: 'kubeconfig', variable: 'KUBECONFIG')]) {
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

        // 4) 清工作区（阶段 0.2）：先用 root 把权限放宽，再删
        //    为什么要两步 —— 实测踩过的：
        //    deleteDir() 是以 jnlp 容器的身份执行的（uid 1000 的 jenkins），而 reports/ 和
        //    __pycache__ 是 python 容器建的 —— library/python:3.9-slim 默认以 root 跑。
        //    uid 1000 既不能 chmod 也不能 unlink root 名下的文件，于是
        //    "Operation not permitted" → CompositeIOException: Unable to delete ...
        //    所以第一步先用一个 root 容器把整个工作区改成谁都能动：
        //      chmod -R a+rwX .      （X 只给目录加执行位 —— 删除要的是**父目录**可写，
        //                             文件本身的权限位不影响 unlink，但统一放宽省得漏）
        //    为什么用 python 容器做：它是 root，且它一定在（哪怕 RUN_UNIT_TESTS=false）。
        //    docker / kubectl 也是 root，用哪个都行。
        //    为什么不用 `rm -rf` 一把梭：那等于自己实现一遍 deleteDir，还得让 root 去删
        //    自己脚下的 cwd；deleteDir 是 Jenkins 自己的收尾语义，能用就别替它。
        //    两个 try/catch 各自独立：收尾步骤的本分是收尾，不是否决构建结果 ——
        //    和上面 1)2)3) 一个道理（不收异常，它会从 finally 抛出去，把本该绿的构建判成 FAILURE）。
        //    最后：即便真没删干净也没有后果 —— 工作区是 emptyDir，Pod 一销毁
        //    （podRetention: never()）就跟着没了，最多留一行 [warn]。
        if (CLEAN_WORKSPACE) {
          try {
            container('python') {
              sh 'chmod -R a+rwX .'
            }
          } catch (e) {
            echo "[warn] 放宽工作区权限失败（继续尝试删除）：${e}"
          }
          try {
            deleteDir()
          } catch (e) {
            echo "[warn] 清工作区失败（不影响构建结果）：${e}"
          }
        }
      }
    }
  }
}
