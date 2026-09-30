# 踩坑与待办记录（阶段 0 / 1 / 2）

> 这份只记**真实卡住过的地方**：现象 → 成因 → 怎么修的 → 怎么防止再犯。
> 手册性的内容（每步该在界面上点什么、怎么验收）在 `stage0-runbook.md`。
> 代码结构不在这里重复。
>
> 收尾状态：`dev` 分支全绿（最近一次绿色构建 #48，提交 `cb4e067`），流水线 **9 个 stage** 全过
> （阶段 2 的扫描 stage 加进来之后从 8 变 9，见 `stage2-runbook.md`），QA 命名空间里服务可用。
> **还没翻的开关和还没做的验收，都在最后第四节。**

---

## 一、这一轮新增了什么

范围：`ab586c5`（动手之前）→ `8be014a`，11 个提交，22 个文件，+1651 / −92 行。

### 1. 应用 bug 修复（3 个文件）

`app/services/crawler_service.py`、`app/routes.py`、`app/utils/decorators.py`。
见下面**坑 1** 和**坑 7.1**（请求日志的 `path` 带了个多余的 `?`）。

### 2. 测试（新增 `tests/` + `pytest.ini` + `requirements-dev.txt`）

| 文件 | 覆盖什么 |
|---|---|
| `tests/conftest.py` | `app` / `client` fixture、假的爬虫、临时 SQLite |
| `tests/test_routes.py` | 12 条：路由、错误分支、**缓存路径**（坑 1 的回归测试） |
| `tests/test_crawlers.py` | 两个爬虫的解析逻辑（喂假 HTML，不碰外网） |
| `tests/test_services.py` | 落库、失败回滚 |
| `tests/test_models.py` | `to_dict()`、字段默认值 |
| `tests/test_logging.py` | 请求日志的字段与 `path` |

25 个用例、覆盖率 98%（168 条语句）。**单元测试一律不碰外网** —— 真实网络会让流水线因为豆瓣改版而红，那种红没有信息量。

### 3. 流水线脚本（新增 `ci/`）

| 文件 | 作用 |
|---|---|
| `ci/smoke_test.py` | 部署后的节点冒烟：首页内容与 Content-Type、抓取接口的异常分支；`--real-crawl` 时真打**两次**豆瓣抓取 |
| `ci/quality_gate.py` | 把各环节结果汇总成一张表，`--enforce` 才阻断（现在是观察期，不阻断） |
| `ci/notify.py` | 钉钉/企微通知，默认关（`ENABLE_NOTIFY=false`，渠道还没定） |

### 4. 部署清单

- **新增 `k8s/qa/app.yaml`** —— Namespace + Deployment + Service 一个文件（QA 环境，`dev` 分支）
- **`k8s.yaml` 挪到 `k8s/main/k8s.yaml`** —— 生产（`main` 分支），挪完踩了**坑 5**
- 两份清单里 Deployment / Service **刻意同名**，隔离靠 namespace，Jenkinsfile 的参数就不用按环境分叉

### 5. `Jenkinsfile` 重写（5 阶段 → 8 阶段）

拉取代码 / 安装依赖与语法检查 / 单元测试 / 构建并推送镜像 / 部署到 K8s / 节点冒烟 / 质量门禁 / Post 收尾。

三个关键设计：

- **顶部一个开关区**：每个环节一个开关（`RUN_UNIT_TESTS`、`RUN_SMOKE_TEST`、`ENFORCE_QUALITY_GATE`…）。出误报时改一个值就能关掉那一环，而不是回滚整个流水线。
- **镜像 tag 从 `:latest` 改成 7 位短 SHA** —— 这才让"部署镜像与本次构建一致"这条门禁成为可能。
- **收尾四步都不许把构建搞红**（归档 / 通知 / 回收镜像 / 清工作区），全包 `try/catch`，见**坑 4**。

### 6. 文档与配置

- **新增 `docs/stage0-runbook.md`** —— 必须在 Jenkins / Harbor / K8s 上手工做的事 + 验收怎么跑
- `.gitignore` / `.dockerignore` 补全（见**坑 6**）
- 删掉 `requirements.lock` —— 和 `requirements.txt` 逐字节相同，且没有任何地方引用

---

## 二、踩过的坑

### 坑 1：缓存里塞 ORM 对象 → 一小时内的第二次抓取必 500

**这是这一轮最严重的一个，而且是接口线上会炸的那种。**

**现象**：`POST /crawl/douban` 连打两次，第一次 201，第二次 500：

```
Instance <CrawlResult at 0x...> is not bound to a Session; attribute refresh
operation cannot proceed (DetachedInstanceError)
```

**成因**：`execute_crawl` 上挂了 `@cache.memoize(timeout=3600)`，而**缓存缓存的是函数的返回值本身**，Flask-Caching 的 `SimpleCache` 就是一个内存字典、存的是**对象引用**（不做序列化）。第一次调用返回 ORM 对象 `rec`，它绑在那次请求的数据库会话上；请求结束会话关闭。一小时内第二次命中缓存 → 拿到绑在已关闭会话上的实例 → 一读属性就 `DetachedInstanceError`。

**为什么单次调用永远踩不到**：只有"同一平台一小时内第二次"才走缓存路径。所以本地手工点一下、跑一次冒烟，全都是绿的。

**修法**：`execute_crawl` 返回 `rec.to_dict()` —— 一个自包含的 dict，不再需要碰数据库。注意**必须在 `app_context` 里拍平**：`commit()` 之后属性已过期，出了上下文就读不到了。

**防止再犯**（两条测试，就是上面那个"手工测不到"的补丁）：

- `test_execute_crawl_returns_plain_dict_not_orm_object` —— 类型必须是 `dict`
- `test_crawl_same_platform_twice_hits_cache_and_still_201` —— 连打两次都 201，且只落库一条

**验证方式**：真起了一个 Flask 服务打两次（不是 `test_client`），201 → 201，第二次 0.71ms、第一次 12.26ms，延迟差就是缓存命中的证据。

**⚠️ 别把它改回去**：返回 dict 不是"图省事"，缓存里不能放 ORM 对象。代码注释里写了原因。

---

### 坑 2：Jenkins 一直在构建 master，而远端根本没有 master

**现象**：构建 `Finished: SUCCESS`，但——

```
Started by GitLab push by Administrator          ← 推送确实触发了
Checking out Revision 4c51c60... (origin/master)  ← 但它去建的是 master
Commit message: "5"
```

阶段只有 5 个（改名前的旧 Jenkinsfile），跑的代码和 dev 上的改动毫无关系。**绿了，但什么都没验到。**

**成因（两件事叠加）**：

1. 任务配着 `*/master`（普通流水线任务的**默认值**），而 GitLab webhook 是"任何 push 都触发"。于是不管你推哪个分支，它都跑一次 master。
2. 这个仓库早期默认分支叫 master、后来改成 main，**远端已经把 master 删了**（`git ls-remote --heads` 只剩 dev / main）。但 Jenkins 那份克隆里 `refs/remotes/origin/master` 还在 —— `git fetch` 不带 `--prune` 不会清理已删除分支的引用。于是它"成功地"检出了一个远端不存在的分支。

**修法**：

- 任务侧：`Branches to build` 从 `*/master` 改成 `*/dev`，或直接改成多分支流水线；Additional Behaviours 加一条 **Wipe out repository & force clone**（清掉陈旧引用，连 `@script` 目录一起清）
- 项目侧：`branchTargets` 里删掉 master 那一行，并写上注释说明为什么不能加回来

**怎么确认修好了**：日志里 `Checking out Revision ...` 括号内是 `origin/dev`，`Commit message` 是你刚推的那条，开头四行是

```
分支      : dev
提交      : 8be014a
目标环境  : QA（namespace=qa）
本次镜像  : 192.168.234.120:80/wang/flask-app:8be014a
```

**顺带发现**：master 那条线上还留着 `deployment.yaml`（dev 上早就换成 `k8s/` 了）和一个坏 Dockerfile `CMD ["python", "app.py"]`（仓库里从来没 `app.py`）。所以那次构建不仅跑的是旧流程，连产出物都是坏的 —— 那个 `:latest` 镜像起来就退。

---

### 坑 3：agent Pod 的命名空间和 serviceAccount 对不上

**现象**：`podTemplate` 里写了 `serviceAccount: 'jenkins'`，但 agent Pod 被创建在 `default` 命名空间，而 `jenkins` 这个 SA 住在 `devops`。K8s 的 ServiceAccount 准入要求 **SA 和 Pod 同命名空间**，对不上直接拒绝创建：

```
error looking up service account default/jenkins: serviceaccount "jenkins" not found
```

构建会卡在"起 Pod"那一步，**根本走不到后面的 stage**。

**为什么一直没炸**：实际跑上集群的那份 Jenkinsfile（master 上的旧版）**压根没有 `serviceAccount` 这一行**，用的是 `default` 命名空间里自带的 SA。所以这个错误一直藏在新版文件里，直到切到 `dev` 分支才露出来。

**修法**：把两样写在同一个地方——

```groovy
podTemplate(label: label, namespace: 'devops', serviceAccount: 'jenkins', containers: [...])
```

`podTemplate` 不写 `namespace` 时会跟随 Jenkins 云配置（那台配的是 `default`），所以必须写死。**写死比改云配置好**：改动只影响这一条流水线（云配置是所有任务共享的），而且命名空间和 SA 写在同一个地方，一眼能看出这俩是一对 —— 这个坑能藏这么久，恰恰是因为它们分别写在两处、没人对照过。

**⚠️ 别这么修**：在 `default` 里再建一个叫 `jenkins` 的 SA 去凑。0.3 的 `harbor-pull` 就是挂在这个 SA 上的，两个命名空间各一个同名 SA，以后一定指错。

---

### 坑 4：清工作区把一次本该绿的构建判成 FAILURE

**现象**：第一次跑新版流水线，7 个 stage 都过了，最后：

```
[Pipeline] deleteDir
hudson.remoting.ProxyException: java.nio.file.FileSystemException:
  .../workspace/python1/ci/__pycache__/notify.cpython-39.pyc: Operation not permitted
...
Unable to delete '/home/jenkins/agent/workspace/python1'
Finished: FAILURE
```

**成因**：同一个 Pod 里两个容器的 **uid 不一致**。

| | 身份 | uid | 建了什么 |
|---|---|---|---|
| `jnlp` 容器 | `deleteDir()` 以它的身份执行 | 1000（`jenkins`） | git 检出的文件 |
| `python` / `kubectl` 容器 | 跑 compileall / pytest / 写 `reports/` | **0（root）** | `reports/`、各处 `__pycache__` |

uid 1000 既不能 chmod 也不能 unlink root 名下的文件 → `Operation not permitted` → `CompositeIOException`。而这个异常是从 **`finally` 块里抛出去**的，于是整个构建被判 FAILURE。

**为什么"绕开"不行**：试过让 python 容器别写 `.pyc`（`PYTHONPYCACHEPREFIX`），但 `reports/` 这个目录**必须**由容器以 root 建（归档要读它），一样删不掉。所以 try/catch 不是妥协，**是这一步唯一正确的写法**。

**修法**：把 `deleteDir()` 包进 try/catch，和收尾的其它三步保持一致 —— 收尾步骤的本分是收尾，不是否决构建结果。

**代价说清楚**：这层 try/catch 会把"工作区没清干净"变成静默。当前架构下没有后果（见下），但**如果哪天换成持久化工作区（PVC 或固定 label），它会把真问题盖住** —— 那时候要改成"先用 root 身份 `chmod -R a+rwX .`，再删"。

> **2026-09-30：那个"哪天"提前来了（虽然架构没换）：现在就是这么写的。**
> `Jenkinsfile` 的 Post 收尾里，`deleteDir()` 之前多了一步 `container('python') { sh 'chmod -R a+rwX .' }`。
> 理由不是"emptyDir 兜底不成立"（那套推理今天依然成立），而是**每次都出现的那行 `[warn]` 本身有害** ——
> 一行永远在的警告，会把收尾段落变成噪音掩体：真出问题时没人会注意到多了一行。
> 一步 chmod 就让它真的删干净，收尾段落恢复成"没事就是没事"。
> **同时 `podTemplate` 加了 `podRetention: never()`**（构建一结束就删 agent Pod），
> 见第四节 —— 这两件事合起来才是"用完的东西自己消失"。

**顺带搞清的一件事**：工作区是 `emptyDir`，而且每轮 `label` 都带随机 UUID —— **新构建 = 新 Pod = 新 emptyDir**。所以：

- 清不掉的那些文件会随 Pod 销毁一起消失，"没删干净"本身没有后果
- **每次重新部署 QA，数据库都会从零开始**（新 Pod = 新卷 = 空文件 → `create_all()` 重新建表，之前的 `crawl_result` 记录全没）

对 QA 来说这是好事（每轮环境干净），但别把它当能存东西的地方。

---

### 坑 5：清单挪了位置，Jenkinsfile 的路径没跟着改（埋着，还没炸）

**现象**：把 main 的清单从仓库根 `k8s.yaml` 挪到 `k8s/main/k8s.yaml`，但 `Jenkinsfile` 的 `branchTargets` 里还写着 `manifest: 'k8s.yaml'`。挪动**之前**这是自洽的（根目录确实有那个文件），所以肉眼审不出来 —— 一提交就断：`main` 分支下次构建时 `kubectl apply -f k8s.yaml` 会报 `error: the path "k8s.yaml" does not exist`，`部署到 K8s` 直接红。

**怎么发现的**：提交前对着"哪里引用了这些清单"逐个 grep（`Jenkinsfile` / `.dockerignore` / `docs/`），一共三处，两处过时。

**修法**：

- `Jenkinsfile` 里改成 `k8s/main/k8s.yaml`
- `.dockerignore` 里那行 `k8s/main/k8s.yaml` 删掉 —— 上一行的 `k8s` 已经把整个目录排除了，它是多余的
- `.dockerignore` 注释里"见 `deployment.yaml`"改成实际路径

**教训**：**挪文件时，要 grep 引用它的地方**，尤其是那种"路径写在配置文件里、编译期不报错"的引用。

---

### 坑 6：加了 .gitignore 就以为文件不进仓库了 —— 对已跟踪的文件无效

`.gitignore` 里明明写了 `__pycache__/`、`*.py[cod]`、`.env`、`.env.*`、`.idea/`，但**这些规则对已经跟踪的文件无效** —— 它们是在补 `.gitignore` 之前就提交进去的。同一个坑在这个仓库里有四份：

| 什么 | 几个 | 来源提交 | 状态 |
|---|---|---|---|
| `.env`（里面是 `SECRET_KEY=dev-secret-123456`） | 1 | `fcc0fb3` | **还在仓库里** |
| `instance/dev.db`（本地跑出来的开发数据） | 1 | `fcc0fb3` | 已清（`ca9c550`） |
| `app/**/__pycache__/*.cpython-39.pyc` | 11 | `fcc0fb3` | **还在** |
| `.idea/`（PyCharm 工程文件） | 6 | `11fbd97` | **还在** |

**修法**：对剩下的跑一次 `git rm -r --cached <路径>`（文件留在本地磁盘上，只是不再跟踪），然后提交。

**`.env` 有个连带问题必须一起处理**：`app/config.py` 里

```python
SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL')   # 没有默认值
```

`.env` 一取消跟踪，新克隆的人跑 `python wsgi.py` 会因为 URI 是 `None` 直接炸。所以要么给个默认值，要么**同时提一个 `.env.example`**。（Jenkins 侧不受影响：单元测试用 `conftest.py` 自己的 URI，K8s 清单里显式注入了环境变量。）

---

### 坑 7：两个把自己骗过去的小坑

这两条不涉及业务代码，但都让人白花过时间，记下来。

#### 7.1 请求日志的 `path` 带了个多余的 `?`

`app/utils/decorators.py` 里用 `request.full_path` 记 `path`，而 Flask 在**没有查询串**时会补一个孤零零的 `?`（`/crawl/douban?`）。这个字段是要进日志、被断言的东西，带这种噪音以后没法做精确匹配。修法：`.rstrip('?')`。

#### 7.2 本地验证时，一个残留的探针进程冒充了验证结果

**现象**：本地起 Flask 服务验证坑 1 的修复，结果是"改之前也 500、改之后也 500"，看起来像修改完全无效 —— 白查了半个多小时。

**成因**：上一轮会话留下的探针进程还监听着那个端口。**Windows 的 `SO_REUSEADDR` 允许重复绑定同一个端口**，新服务"绑定成功"，而请求全被**旧进程**（跑的还是修改前的代码）接走。

**防再犯（两条，必须都做）**：

1. 端口每次随机：`socket.bind(('127.0.0.1', 0))` 拿空闲端口，别写死
2. 加自检端点，先证明"应答的是我自己的进程"：

```python
@app.route('/__probe_whoami')
def _whoami():
    return {'pid': os.getpid()}
```

就绪探测时断言 `pid == os.getpid()`，不对就直接退出。

查残留：`netstat -ano | grep <端口>` + `tasklist //FI "IMAGENAME eq python.exe"` → `taskkill //PID <pid> //F`。

**教训**：拿真服务器验证行为时，**先证明"我打到的是自己的进程"，再谈结论**。

---

## 三、顺手清掉的

- `requirements.lock` —— 和 `requirements.txt` 逐字节相同（`diff` 验证过），且没有任何地方引用
- `.dockerignore` 里多余的 `k8s/main/k8s.yaml`、注释里过时的 `deployment.yaml`
- `Jenkinsfile` 的 `branchTargets` 里 master 那一行（见坑 2）
- `docs/stage0-runbook.md` 里几处过时描述（"`podTemplate` 里没写 namespace"等）
- 本地探针脚本、临时 CSV、`reports/` 下的验证产物

---

## 四、还没解决 / 待观察

| 事项 | 状态 | 说明 |
|---|---|---|
| 门禁还是观察期（`ENFORCE_QUALITY_GATE=false`） | **待翻** | 检查全都**只记录、不阻断**。这是**刻意的**（规划原则 3：先出报告、看误报率，再上卡点），不是没做完 —— 理由全文在 `stage2-runbook.md`「什么时候从观察期升级成卡点」。**只差一个前置**：下面 `Pod 无重启` 那条得先绿。翻法：`Jenkinsfile:15` 改成 `true` |
| 2.3 并行只验证过**一次** | 等这次构建 | `parallel` + `container()` 在个别 kubernetes-plugin 版本上偶发卡死，所以这一版只被**一次**构建验证过（之前跑绿的是串行版，那次不含并行）。跑绿就留着；卡住就拆回串行，拆法写在 `stage2-runbook.md` 开头那段 note 里 |
| `create_all()` 的并发竞态 | 观察中 | `create_app()` 里 `db.create_all()`，而镜像是 `gunicorn --workers 2` —— 两个 worker 首启可能抢着建表。**目前没有任何证据它真发生过**（唯一一次"Pod 重启 1 次"是人工干预造成的），所以先不改代码：下次构建全程不碰 Pod，看门禁那条还是不是 ❌，是才是真问题 |
| 「Pod 无重启」这条门禁会被污染 | 已知道 | 它读的是 `restartCount`，探针杀的、进程崩的、你手动 pause/重开容器的**全都算**。看到 ❌ 先自问一句"这个 Pod 我动过吗" |
| 验收① 故意改坏 → 红 | 没做 | runbook 的「阶段 2 的验收怎么跑」里有对照表，挑一行试 |
| 验收③ 连跑 10 次磁盘不涨 | 没做 | `df -h /` + `du -sh /var/lib/docker` + Harbor 的 tag 数。**别为此专门跑 10 次** —— 真正要证的只是"Pod 用完会自己消失"，一次构建 + `kubectl get pods -n devops` 就够了 |
| 坑 6 遗留：`.env` / 11 个 `.pyc` / 6 个 `.idea/` 还在仓库里 | 没做 | 修法见坑 6。**`.env` 优先**：里面是 `SECRET_KEY=dev-secret-123456`，虽然只是开发值，但"密钥进过仓库"这件事本身该清掉。取消跟踪的同时要补一个 `.env.example`，否则新克隆的人 `python wsgi.py` 会因为 URI 是 `None` 直接炸 |
| **Harbor 制品保留策略** | 可选，不急 | **原判「不配几天就把仓库撑爆」是错的，2026-09-30 更正**：`Dockerfile` 的顺序是 `COPY requirements.txt` → `RUN pip install` → `COPY . .`，所以基础层和依赖层**跨构建共享**，每次真正新增的只有 `COPY . .` 那个代码层（几 MB）；Harbor 是内容寻址的，层没变就不重复存。**最硬的证据：48 次构建下来机器没事。** 配法见 runbook 0.5，有空点两下当保险即可 |
| 0.3 agent 容器镜像内网化 | 可选，不急 | **什么时候开**：当 Pod 起得慢开始碍事时（拉公网镜像最慢的一次卡到过 1000 秒超时）。开关 `MIRROR_AGENT_IMAGES` 就是为它准备的；注意 `harbor-pull` secret 必须挂在 **agent 用的那个 SA** 上（现在是 `devops/jenkins`），挂错 Pod 直接起不来 |
| 1.4 通知 | 可选，不急 | **什么时候开**：当你开始"构建红了、几天后才知道"时。`ci/notify.py` 已经写好了（钉钉/企微），只缺一个 webhook 地址 —— 渠道定了就把 `ENABLE_NOTIFY` 翻 `true` |
| `SMOKE_REAL_CRAWL` 一直关着 | 刻意 | 开了冒烟会真打两次豆瓣抓取，需要 QA 有公网出口、慢 20s+。缓存路径已经有单元测试钉着（`test_crawl_same_platform_twice_hits_cache_and_still_201`），所以真实环境这条不是必须 |
