#!/usr/bin/env python
"""构建结束发通知（阶段 1.4）。

**默认不启用**：Jenkinsfile 里 ENABLE_NOTIFY = false。
**这份实现没有在真实渠道上验证过**（渠道还没定）—— 接上之后先手动跑一次确认，
再打开开关。Jenkinsfile 那边的调用包了 try/catch，发不出去不会让构建变红。

环境变量：
  NOTIFY_CHANNEL  dingtalk | wecom
  NOTIFY_WEBHOOK  完整 webhook 地址（Jenkins 里存成 secret text 凭据）
  NOTIFY_STATUS / NOTIFY_JOB / NOTIFY_BUILD / NOTIFY_BRANCH / NOTIFY_IMAGE / NOTIFY_URL

手动试一次：
  NOTIFY_CHANNEL=dingtalk NOTIFY_WEBHOOK='https://...' NOTIFY_STATUS=SUCCESS \
    NOTIFY_JOB=demo NOTIFY_BUILD=1 NOTIFY_BRANCH=dev NOTIFY_IMAGE=x NOTIFY_URL=y \
    python ci/notify.py
"""
import os
import sys

import requests

# Windows 控制台默认 GBK，直接 print 中文/emoji 会 UnicodeEncodeError
try:
    sys.stdout.reconfigure(encoding='utf-8')
except (AttributeError, ValueError):
    pass

CHANNEL = os.environ.get('NOTIFY_CHANNEL', 'dingtalk')
WEBHOOK = os.environ.get('NOTIFY_WEBHOOK', '')


def build_text():
    status = os.environ.get('NOTIFY_STATUS', 'UNKNOWN')
    icon = {'SUCCESS': '✅', 'FAILURE': '❌'}.get(status, '⚠️')
    lines = [
        f'{icon} **{status}**',
        f'- 任务：{os.environ.get("NOTIFY_JOB", "-")} #{os.environ.get("NOTIFY_BUILD", "-")}',
        f'- 分支：{os.environ.get("NOTIFY_BRANCH", "-")}',
        f'- 镜像：{os.environ.get("NOTIFY_IMAGE", "-")}',
        f'- 详情：[构建日志]({os.environ.get("NOTIFY_URL", "")})',
    ]
    return '\n'.join(lines)


def build_payload(text):
    # 钉钉和企微的 markdown 字段名不一样：一个是 markdown.text，一个是 markdown.content
    if CHANNEL == 'wecom':
        return {'msgtype': 'markdown', 'markdown': {'content': text}}
    return {
        'msgtype': 'markdown',
        'markdown': {
            'title': f'{os.environ.get("NOTIFY_STATUS", "")} {os.environ.get("NOTIFY_JOB", "")}',
            'text': text,
        },
    }


def main():
    if not WEBHOOK:
        print('[notify] 没有 NOTIFY_WEBHOOK，跳过')
        return 1

    payload = build_payload(build_text())
    resp = requests.post(WEBHOOK, json=payload, timeout=10)

    # 钉钉/企微都是 HTTP 200 但 body 里带 errcode —— 只看状态码会漏掉失败
    try:
        body = resp.json()
    except ValueError:
        body = {}
    errcode = body.get('errcode', body.get('code', 0))
    print(f'[notify] HTTP {resp.status_code}，errcode={errcode}，body={resp.text[:200]}')

    if resp.status_code >= 400 or errcode not in (0, None):
        print('[notify] 发送失败')
        return 1
    print('[notify] 发送成功')
    return 0


if __name__ == '__main__':
    sys.exit(main())
