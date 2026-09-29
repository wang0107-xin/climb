#!/usr/bin/env python
"""部署后节点冒烟：打**真实业务路径**，而不是只看探针。

为什么需要它：`kubectl rollout status` 只能证明 readiness/liveness 探针过了。
探针打的是 `/`，只要 Flask 起来了就返回 200 —— 但"探针过了、业务挂了"两者完全
可以同时成立（依赖没装、数据库连不上、镜像版本不对、路由注册失败）。
所以这里断言的是**响应内容**，不是状态码本身。

地址来源（按顺序取第一个拿到的）：
  --base-url http://host:port
  reports/deploy.env 里的 DEPLOY_BASE_URL（Jenkinsfile 里由 kubectl 容器写入）
  环境变量 SMOKE_BASE_URL

退出码：全部通过 → 0；有失败 → 1。结果写 reports/smoke.json。
"""
import argparse
import json
import os
import sys
from pathlib import Path

import requests

BASE_DIR = Path(__file__).resolve().parent.parent
REPORT = BASE_DIR / 'reports' / 'smoke.json'
DEPLOY_ENV = BASE_DIR / 'reports' / 'deploy.env'

EXPECTED_HOME_MSG = 'Flask Crawler API Running'
# Windows 控制台默认 GBK，直接 print 中文会 UnicodeEncodeError
try:
    sys.stdout.reconfigure(encoding='utf-8')
except (AttributeError, ValueError):
    pass
# 故意用一个不存在的平台，走 routes.crawl 的异常分支
BAD_PLATFORM = '__smoke_no_such_platform__'

TIMEOUT = 15


def read_base_url_from_deploy_env():
    if not DEPLOY_ENV.exists():
        return None
    for line in DEPLOY_ENV.read_text(encoding='utf-8').splitlines():
        if line.startswith('DEPLOY_BASE_URL='):
            return line.split('=', 1)[1].strip()
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', default=None)
    parser.add_argument(
        '--real-crawl',
        action='store_true',
        help='对 douban 连打两次 POST /crawl。需要 QA 有公网出口，会慢 20s+，默认关闭',
    )
    args = parser.parse_args()

    base_url = args.base_url or read_base_url_from_deploy_env() or os.environ.get('SMOKE_BASE_URL')
    if not base_url:
        print('[smoke] 拿不到服务地址：既没有 --base-url，也没有 reports/deploy.env')
        return 2
    base_url = base_url.rstrip('/')
    print(f'[smoke] 目标：{base_url}')

    session = requests.Session()
    results = []

    def run(name, fn, enabled=True):
        if not enabled:
            results.append({'name': name, 'ok': True, 'skipped': True, 'detail': '未启用'})
            print(f'  --  {name}：未启用')
            return
        try:
            detail = fn()
            results.append({'name': name, 'ok': True, 'detail': detail})
            print(f'  OK  {name}：{detail}')
        except Exception as e:  # 任何异常都算这条用例失败，不中断后面的
            detail = f'{type(e).__name__}: {e}'
            results.append({'name': name, 'ok': False, 'detail': detail})
            print(f'  !!  {name}：{detail}')

    # ---- 1) 首页：状态码 + Content-Type + 内容三样一起断言（原本拆成两条用例，
    #         但打的是同一个请求，合并省一次往返，失败信息也没丢）----
    def home_content():
        r = session.get(f'{base_url}/', timeout=TIMEOUT)
        assert r.status_code == 200, f'期望 200，实际 {r.status_code}'
        ctype = r.headers.get('Content-Type', '')
        assert 'application/json' in ctype, (
            f'Content-Type={ctype!r} —— 端口上应答的可能不是我们的应用'
        )
        body = r.json()
        assert body.get('msg') == EXPECTED_HOME_MSG, f'msg 不对：{body!r}'
        return f"200，msg={body['msg']}"

    # ---- 2) 不存在的路径 → 404（"确实是我们的应用在应答"的旁证）----
    def unknown_path_404():
        r = session.get(f'{base_url}/__smoke_no_such_path__', timeout=TIMEOUT)
        assert r.status_code == 404, f'期望 404，实际 {r.status_code}'
        return '404'

    # ---- 3) 抓取接口的异常分支：必须是 JSON 结构，而不是 Flask 的 HTML 错误页 ----
    # 这条能抓住"路由挂了 / 异常处理没兜住 / 被网关抢答"这类问题
    def crawl_error_branch():
        r = session.post(f'{base_url}/crawl/{BAD_PLATFORM}', timeout=TIMEOUT)
        assert r.status_code == 500, f'期望 500，实际 {r.status_code}'
        body = r.json()
        assert 'error' in body, f'响应里没有 error 字段：{body!r}'
        assert BAD_PLATFORM in body['error'], f"error 内容不对：{body['error']!r}"
        return f"500，error={body['error']}"

    # ---- 4) 可选：真抓两次同一个平台（默认关，会走真实外网）----
    # 打两次是有意的：第二次会命中 execute_crawl 上的缓存，走的是"从缓存里取结果"
    # 那条路径。那条路上原来会 500（缓存里塞了绑在已关闭会话上的 ORM 对象），
    # 而单次调用永远踩不到 —— 所以这条同时也是那个 bug 的回归检查。
    def real_crawl_twice():
        first = session.post(f'{base_url}/crawl/douban', timeout=180)
        assert first.status_code == 201, (
            f'第一次期望 201，实际 {first.status_code}：{first.text[:200]}'
        )
        body = first.json()
        # 只断言"结构对"，不断言 count > 0：抓取结果依赖对方站点当天长什么样，
        # 抓到 0 条不等于我们的服务坏了（weibo 在本机真抓时就返回过 0 条）。
        # 断言 count>0 只会让流水线因为豆瓣改版变红，那种红没有信息量。
        assert isinstance(body.get('count'), int), f'响应结构不对：{body!r}'
        assert body.get('file_path', '').endswith('.csv'), f'响应结构不对：{body!r}'

        second = session.post(f'{base_url}/crawl/douban', timeout=60)
        assert second.status_code == 201, (
            f'第二次（命中缓存）期望 201，实际 {second.status_code}：{second.text[:200]}'
        )
        return f"两次都是 201，count={body['count']}"

    print('[smoke] 用例：')
    run('首页内容与 Content-Type 正确', home_content)
    run('未知路径返回 404', unknown_path_404)
    run('抓取接口异常分支返回 JSON', crawl_error_branch)
    run('真实抓取两次（含缓存路径）', real_crawl_twice, enabled=args.real_crawl)

    ok = all(r['ok'] for r in results)
    enabled_count = sum(1 for r in results if not r.get('skipped'))
    failed = [r for r in results if not r['ok']]

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(
        json.dumps({'base_url': base_url, 'ok': ok, 'checks': results}, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )

    print(f"[smoke] {enabled_count} 条启用，{len(failed)} 条失败 → {'通过' if ok else '失败'}")
    print(f'[smoke] 报告：{REPORT}')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
