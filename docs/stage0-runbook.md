# 阶段 0 + 阶段 1 落地手册

代码里已经做完的部分不在这里重复。这份只写**必须在 Jenkins / Harbor / K8s 上手工做**的事，
以及验收怎么跑。

> 代词说明：下面命令里的 `<agent 命名空间>` 指 agent Pod 落在哪个命名空间。**它的值现在是 `devops`** ——
> `Jenkinsfile` 的 `podTemplate` 里写死了 `namespace: 'devops'`，和它用的 `serviceAccount: 'jenkins'`
> 在同一个命名空间（K8s 要求 SA 和 Pod 同命名空间，对不上 Pod 直接创建不出来，见 0.1 的第二个 ⚠️）。
> 要确认：`kubectl get pods -A | grep jnlp`。

---

## 0.1 分支指向（Jenkins 任务侧）

流水线里已经把「哪个分支去哪个环境」写死了（`Jenkinsfile` 顶部的 `branchTargets`）：
`dev` → `qa` 命名空间，`main` → `default`（生产），其它分支只构建不部署。

任务侧要配的只有一件事：**让它真的能拿到分支名**。

- **推荐**：把任务建成 **Multibranch Pipeline**（多分支流水线）。这样 `env.BRANCH_NAME`
  会有值，dev / main 各自触发各自的构建。
- 如果坚持用普通流水线任务：`env.BRANCH_NAME` 是空的，流水线会退回读
  `checkout scm` 返回的 `GIT_BRANCH`。这时任务里 Branch Specifier 必须写成 `*/dev`
  或 `*/main`，否则同一个任务每次拉的分支不一样，"分支指向"就还是假的。

### ⚠️ 一定要顺手做掉：清掉陈旧的 origin/master

**这个坑真实发生过。** 一次构建"成功"了，但检出的是 `origin/master`（commit `4c51c60`，
commit message 一个 "5"），跑的是改名前的旧 Jenkinsfile —— master 上有几个 stage、
产出什么，全由旧文件说了算。绿了，但和你要验的 dev 上的改动毫无关系。

成因是两件事叠在一起：

1. 这个仓库早期默认分支叫 `master`，后来改成了 `main`，**远端已经把这个分支删了**
   （`git ls-remote --heads` 现在只返回 `dev` 和 `main`）。
2. Jenkins 那份克隆**不会自动清理已删除分支的引用** —— `git fetch` 不带 `--prune`，
   `refs/remotes/origin/master` 就一直留着，指向那个旧提交。
   于是任务配着 `*/master`（普通流水线任务的默认值）时，它"成功地"检出了一个
   远端根本不存在的分支。

做法二选一：

- 任务配置 → Additional Behaviours → 加一条 **Wipe out repository & force clone**（推荐，长期有效）
- 或者手动删掉工作区：`/var/jenkins_home/workspace/<任务名>` 和 `<任务名>@script` 两个目录

**怎么确认检出对了**：构建日志里那行 `Checking out Revision ...` 括号里应该是 `origin/dev`
（或 `origin/main`），不是 `origin/master`；后面 `Commit message:` 应该是你刚推的那条。

**怎么确认生效**：构建日志开头会打印

```
分支      : dev
提交      : abc1234
目标环境  : QA（namespace=qa）
本次镜像  : 192.168.234.120:80/wang/flask-app:abc1234
```

`目标环境` 那行是 `仅构建，不部署` 就说明分支名没取到，或者分支不在表里。

### ⚠️ agent Pod 的命名空间必须和 serviceAccount 成对

**这个也真实踩过。** agent Pod 原先落在 `default` —— 因为 `podTemplate` 早先没写 `namespace`，
就跟随云配置（那台配的是 `default`）；而 `serviceAccount` 写的是 `jenkins`，这个 SA 住在 `devops`。
K8s 的 ServiceAccount 准入要求 **SA 和 Pod 同命名空间**，对不上就直接拒绝创建 Pod：

```
error looking up service account default/jenkins: serviceaccount "jenkins" not found
```

为什么以前没炸：实际跑上集群的那份 Jenkinsfile（master 上的旧版）**压根没有 `serviceAccount` 这一行**，
用的就是 `default` 里自带的 SA。所以这个错误一直藏在新版文件里，直到切到 `dev` 分支才露出来 ——
和上面 `origin/master` 是同一类问题：**配置里写的东西和它实际会跑的地方对不上，而且一直没跑到那条路径上。**

现在的做法是在 `podTemplate` 里把两样写在一起：

```groovy
podTemplate(label: label, namespace: 'devops', serviceAccount: 'jenkins', containers: [...])
```

**写死比改云配置好**：改动只影响这一条流水线（云配置是所有任务共享的），而且命名空间和 SA 写在同一个地方，
一眼能看出这俩是一对 —— 这个坑能藏这么久，恰恰是因为它们分别写在两处、没人对照过。

**别这么修**：在 `default` 里再建一个叫 `jenkins` 的 SA 去凑。0.3 的 `harbor-pull` 就是挂在这个 SA 上的，
两个命名空间各一个同名 SA，以后一定指错。

---

## 0.3 镜像内网化（不需要推任何镜像）

**什么都不用做。** 基础镜像 `library/python:3.9-slim` 已经在 Harbor 里了（Dockerfile 用的就是它），
`Jenkinsfile` 里的 `python` 容器现在直接指向它。pytest / 覆盖率是构建时 `pip install`
进这个容器的几十 MB 包，不产生新镜像。

**可选的下一步**：把 `jnlp` / `docker` / `kubectl` 这三个 agent 容器的镜像也内网化。
现在它们默认还从 Docker Hub 拉（`MIRROR_AGENT_IMAGES = false`）。要做的话：

1. 确认 Harbor 里已经有（或镜像过来）这三个：

   | 用途 | Harbor 路径 | 上游来源 |
   |---|---|---|
   | Jenkins agent | `library/inbound-agent:jdk21` | `jenkins/inbound-agent:jdk21` |
   | 构建/推送镜像 | `library/docker:27-cli` | `docker:27-cli`（原来用的 `docker:latest`） |
   | 部署与查状态 | `library/kubectl:latest` | `cnych/kubectl` |

2. 建拉取凭据，并挂到 agent 用的 ServiceAccount 上 —— **挂 SA 这一步不能省**，
   `jnlp` 容器也是靠这个 SA 拉镜像的：

   ```bash
   kubectl create secret docker-registry harbor-pull \
     --docker-server=192.168.234.120:80 \
     --docker-username='<harbor 用户名>' \
     --docker-password='<harbor 密码>' \
     -n devops

   kubectl patch serviceaccount jenkins -n devops \
     -p '{"imagePullSecrets":[{"name":"harbor-pull"}]}'
   ```

3. 把 `Jenkinsfile` 里的 `MIRROR_AGENT_IMAGES` 改成 `true`，看一眼能不能起 Pod。
   起不来就把这个开关改回 `false`，流水线立刻恢复 —— 这就是留开关的意义。

---

## 0.4 QA 命名空间

已经写在 `k8s/qa/app.yaml` 里了（Namespace + Deployment + Service 一个文件），
`kubectl apply` 会自动建出来，不用手工 `kubectl create namespace`。

**可选但建议**：给 QA 建它自己的 secret（不建也不卡 Pod，会退回 `config.py` 的默认密钥）：

```bash
kubectl create secret generic wang-flask-app-secret -n qa \
  --from-literal=secret-key="$(openssl rand -hex 32)"
# Windows 上没有 openssl 的话：
#   python -c "import secrets;print(secrets.token_hex(32))"
```

**怎么进 QA 看**（Service 是 NodePort，但端口没写死）：

```bash
kubectl get svc wang-flask-app -n qa          # 看分配到的 nodePort
kubectl port-forward -n qa svc/wang-flask-app 8080:80
# 然后浏览器打开 http://localhost:8080
```

---

## 0.5 磁盘基线

小硬盘的流水线**首先死于磁盘满**，不是死于功能。三件事：

### Jenkins 构建保留策略

流水线里已经用 `properties([buildDiscarder(...)])` 配了（保留最近 10 次 / 7 天）。
如果日志里出现 `[warn] 保留策略没配上`，说明任务权限不够，去界面上手动设：

> 任务 → 配置 → 丢弃旧的构建（Discard old builds）→
> 保持构建的天数 `7`、保持构建的最大个数 `10`

多分支流水线要在**每个分支任务**上设，或者用 Organization Folder 那层的设置统一下发。

### Harbor 制品保留策略

**这个不配，仓库几天就爆。** 每构建一次就多一个短 SHA tag。

> Harbor → 项目 → 策略 → 保留策略（Retention）→ 添加规则

| 项目 | 规则 | 建议 |
|---|---|---|
| `wang`（业务镜像） | 保留最近推送的 **10** 个 artifact | 每天 02:00 执行 |
| `library`（基础镜像） | 保留最近推送的 **3~5** 个 | 按需，一般不动 |

注意 Harbor 的保留策略默认是**只预览不删除**（dry run），要手动把开关关掉才真的删。

### 节点悬空镜像

流水线每轮结束会跑 `docker image prune -f`（开关 `PRUNE_DANGLING_IMAGES`）。
它只清没标签的悬空层，不会动别的构建正在用的镜像。

---

## 阶段 1 前置：Jenkins 插件

| 插件 | 用途 | 检查方式 |
|---|---|---|
| JUnit | 解析 `reports/junit.xml` | 插件管理里搜 "JUnit"，通常默认已装 |
| Workspace Cleanup | 没用到（用的是流水线内置的 `deleteDir()`，不需要插件） | — |

`junit` 步骤找不到会报 `No such DSL method`，那就是插件没装。

---

## 验收怎么跑

按照规划里的三条验收标准，逐条对应：

### 1. 故意提交一个坏改动 → 红，且指出是哪一环

每种坏法对应哪个环节红，可以照这个表试：

| 把什么改坏 | 应该红在哪 | 报什么 |
|---|---|---|
| `app/routes.py` 里 `home()` 的返回值改成别的字符串 | 单元测试 | `test_home_returns_running_message` 断言失败 |
| `wsgi.py` 里的变量名 `app` 改掉 | 安装依赖与语法检查 | 应用初始化那步报 ImportError |
| `k8s/qa/app.yaml` 的 `targetPort` 改成 5001 | 部署到 K8s | `rollout status` 超时 180s |
| `app/services/crawler_service.py` 里去掉 `db.session.rollback()` | 单元测试 | `test_crawl_commit_failure_rolls_back` 失败 |
| `execute_crawl` 的返回值改回 `return rec`（把 ORM 对象塞进缓存） | 单元测试 | `test_execute_crawl_returns_plain_dict_not_orm_object` 失败；冒烟打开真抓取时第二次调用也会红 |
| `Jenkinsfile` 里 `podTemplate` 的 `namespace` 改成 `default`（和 `serviceAccount: 'jenkins'` 对不上） | 起 agent Pod（在「拉取代码」之前） | `serviceaccount "jenkins" not found`，Pod 创建被拒 |

### 2. 正常改动 → 绿，服务在 QA 可用

推 dev 分支，绿了之后：

```bash
kubectl get deploy,pod,svc -n qa
# 然后按 0.4 里的 port-forward 打开看一眼
```

### 3. 连续跑 10 次，磁盘占用不持续增长

```bash
# 构建前
df -h /
du -sh /var/lib/docker
du -sh <jenkins 工作区目录>

# 连跑 10 次构建后再看一遍
```

三处都不该持续涨：Jenkins 构建记录（保留策略）、Harbor 里 `wang` 项目的 tag 数（保留策略）、
节点上的悬空镜像（`docker image prune`）。

**Harbor 的 tag 数会涨到 10 然后稳住在 10**，这是对的；只涨不降才说明保留策略没生效。

---

## 每次构建归档了什么

`reports/` 目录整个会被 `archiveArtifacts` 收走，在构建页面左侧「构建产物」里：

| 文件 | 内容 | 谁产出的 |
|---|---|---|
| `junit.xml` | 单元测试结果（Jenkins 会渲染成趋势图） | pytest |
| `coverage.xml` | 覆盖率明细 | pytest-cov |
| `deploy.env` | 实际部署的镜像 / 副本数 / 重启次数 | kubectl 容器 |
| `smoke.json` | 冒烟逐条结果 | ci/smoke_test.py |
| `gate-summary.md` / `.json` | 质量门禁汇总表 | ci/quality_gate.py |

---

## 阶段 1 里几个刻意的取舍

- **冒烟默认不真打豆瓣抓取**（`SMOKE_REAL_CRAWL = false`）。那会走真实外网、10 页 + 每页
  `sleep(1)`，QA 有没有公网出口还没确认。首页内容 + 抓取接口异常分支这两条默认开，
  已经能覆盖"探针过了但业务挂了"。确认 QA 有出口后再打开。
  打开时会对 douban **连打两次**（不是一次）：第二次走的是 `execute_crawl` 的缓存路径，
  那条路上原来必 500（缓存里塞了绑在已关闭会话上的 ORM 对象，见交付说明第七节），
  而单次调用永远踩不到。多打一次的代价是几毫秒。
- **真抓取那条不断言"抓到多少条"**，只断言两次都 201、响应结构对。抓多少取决于对方站点
  当天长什么样（本机真抓 weibo 就返回过 0 条），拿它当断言只会让流水线因为豆瓣改版变红，
  那种红没有信息量 —— 和"单元测试一律不碰外网"是同一个道理。
- **质量门禁默认不阻断**（`ENFORCE_QUALITY_GATE = false`）。按规划的「原则 3」，先跑观察期
  看失败率，调好误报再升级成卡点。日志和 `gate-summary.md` 里都会写清当前是哪个模式。
- **覆盖率不设阈值**。先用几轮观察期看看稳定值在哪，再定数字 —— 拍脑袋定个 80% 只会
  让流水线天天红。
- **单元测试一律不碰外网**。真实网络会让流水线因为豆瓣改版或网络抖动而红，这种红没有
  信息量，只会让人学会忽略流水线。网络那部分专门留给冒烟。
- **收尾四步都不许把构建搞红**（归档 / 通知 / 回收悬空镜像 / 清工作区）。"清工作区"这一步尤其需要
  包 try/catch，而且不是"怕万一"：它以 `jnlp` 容器的身份执行（uid 1000 的 `jenkins`），而 `reports/`
  和各处 `__pycache__` 是 `python`、`kubectl` 容器以 **root** 建的 —— uid 1000 既不能 chmod 也不能
  unlink root 名下的文件，`deleteDir()` 必然报 `Operation not permitted`。不收这个异常，它会从
  `finally` 里抛出去，把一次本该绿的构建判成 FAILURE（第一次跑新版流水线就是这么红的）。
  工作区是 `emptyDir` 且每轮 Pod 都是新的（label 带随机 UUID），所以"没删干净"本身没有后果。
  真要让它删干净，得在删之前先用 root 身份 `chmod -R a+rwX .` —— 现在不需要。
