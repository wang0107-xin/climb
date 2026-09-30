#!/usr/bin/env python
"""静态分析与安全扫描的驱动器（阶段 2.1 ruff / 阶段 2.2 bandit）。

为什么不把命令行直接写进 Jenkinsfile：

1. 要区分"发现了问题"和"工具自己没跑起来"—— 而两个工具的退出码含义不一样
   （ruff 0=干净 1=有问题 2=工具出错；bandit 默认"发现问题"就返回 1，得加 `--exit-zero`
   才能把两者分开）。写在 shell 里要么一堆 if，要么用 `|| true` 把工具出错也一起吞掉——
   吞掉之后报告是空的，门禁会把它当成"这一环没启用"，一路绿着过去。
2. 两个工具的报告格式不同。这里归一化成同一份 schema 再交给 ci/quality_gate.py，
   门禁脚本就不用认识两个工具各自的 JSON 结构。
3. 本地可以单独跑，不用起 Jenkins：python ci/static_analysis.py ruff

用法：
  python ci/static_analysis.py ruff     # -> reports/ruff.json
  python ci/static_analysis.py bandit   # -> reports/bandit.json

退出码：
  0   = 跑完了。**发现问题也是 0** —— 按规划的「原则 3」，观察期只出报告不阻断，
        条数交给质量门禁汇总。要真卡住构建，改 Jenkinsfile 的 ENFORCE_QUALITY_GATE。
  非 0 = 工具本身出错、或没产出可解析的报告。这是流水线自己的故障，必须红 ——
        否则"扫了个寂寞"会被当成"扫过了，很干净"。
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
REPORTS = BASE_DIR / 'reports'

# Windows 控制台默认 GBK，直接 print 中文会 UnicodeEncodeError。
# 容器里是 UTF-8 没问题，但在本地跑就会炸，所以显式转一下（和 quality_gate.py 一样的处理）。
try:
    sys.stdout.reconfigure(encoding='utf-8')
except (AttributeError, ValueError):
    pass


# bandit 的 B104（绑定 0.0.0.0）必须跳过，而且不是图省事：
# 容器里的服务只能绑 0.0.0.0 —— 绑 127.0.0.1 等于只有容器自己访问得到，Pod 外面谁来都不通，
# 访问控制在 K8s 这一层做（Service / NetworkPolicy）。
# 留着它，报告里就永远挂着一条无法消除的告警，而一条永远不消的告警会教会所有人忽略整个报告。
BANDIT_SKIPS = ['B104']

TOOLS = {
    'ruff': {
        'desc': '静态分析（规范 / 坏味道）',
        # 扫 `.` 而不是只扫 app：测试和 ci 脚本也一起扫。`.venv` / `reports` / `instance`
        # 由 ruff 按 .gitignore 自己过滤掉，不用手写 exclude。
        'args': ['check', '.', '--output-format=json'],
        'ok_codes': {0, 1},          # 1 = 发现问题（观察期正常）；2 才是工具出错
        'disabled_note': '规则集在 ruff.toml 里',
    },
    'bandit': {
        'desc': '安全扫描（SAST）',
        # 只扫 app 和 wsgi.py —— 这两个才是要打进镜像的代码。
        # tests/ 和 ci/ 里 assert 成片，扫进去只会让安全报告被自己人的测试噪音占满。
        'args': ['-r', 'app', 'wsgi.py', '-f', 'json', '-q',
                 '--exit-zero',
                 '-s', ','.join(BANDIT_SKIPS)],
        'ok_codes': {0},             # --exit-zero 已经把"发现问题"变成 0，所以非 0 一定是真出错
        'disabled_note': f'跳过 {", ".join(BANDIT_SKIPS)}（容器内必须绑 0.0.0.0）',
    },
}


def rel(path):
    """报告里的路径统一成 repo 根下的相对路径，正斜杠。

    两个工具给的路径格式不一样：ruff 给绝对路径，bandit 给 '.\\wsgi.py' 这种。
    不归一化的话，同一份报告被 Jenkins 和本地跑出来会是两种样子。
    """
    p = (path or '').replace('\\', '/')
    try:
        return os.path.relpath(p).replace('\\', '/')
    except ValueError:      # 跨盘符时 relpath 会抛，退回去用原值
        return p


def parse_ruff(payload):
    """ruff 的 JSON -> 统一的条目列表。

    ruff 的字段是嵌套的（location.row / location.column），而且它**故意**不把行号放在
    顶层 —— 一条告警可以跨多行，location 是起点、end_location 是终点。
    """
    items = []
    for d in payload:
        loc = d.get('location') or {}
        items.append({
            'code': d.get('code') or '?',
            'file': rel(d.get('filename')),
            'line': loc.get('row', 0),
            'col': loc.get('column', 0),
            'severity': d.get('severity', 'error'),
            'message': d.get('message', ''),
        })
    return items


def parse_bandit(payload):
    """bandit 的 JSON -> 统一的条目列表。顺带把 errors（bandit 自己遇到的解析失败）带出来。"""
    items = []
    for d in payload.get('results', []):
        items.append({
            'code': d.get('test_id') or '?',
            'file': rel(d.get('filename')),
            'line': d.get('line_number', 0),
            'col': d.get('col_offset', 0),
            'severity': d.get('issue_severity', ''),
            'message': d.get('issue_text', ''),
        })
    return items, payload.get('errors') or []


def by_code(items):
    counts = {}
    for it in items:
        counts[it['code']] = counts.get(it['code'], 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def write_report(tool, payload):
    path = REPORTS / f'{tool}.json'
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return path


def fail(tool, reason, detail=''):
    """工具没跑起来：报告里写明原因，然后非 0 退出。

    报告**一定要写**：门禁看到 reports/<tool>.json 存在但 error 非空，会判成"门禁未通过"。
    如果干脆不写文件，门禁会当成"这一环没启用"（`未产出`）而放过 —— 那才是真的危险。
    """
    payload = {
        'tool': tool, 'ok': False, 'error': reason, 'error_detail': detail,
        'count': 0, 'by_code': {}, 'items': [],
    }
    path = write_report(tool, payload)
    print(f'[static_analysis] {tool} 没跑起来：{reason}')
    if detail:
        print(detail)
    print(f'[static_analysis] 原因已写进 {path}')
    return 2


def main():
    parser = argparse.ArgumentParser(description='静态分析 / 安全扫描驱动器')
    parser.add_argument('tool', choices=sorted(TOOLS), help='跑哪个工具')
    parser.add_argument('--max-items', type=int, default=50,
                        help='控制台最多列几条明细（默认 50，全量始终在 reports/<tool>.json 里）')
    args = parser.parse_args()

    spec = TOOLS[args.tool]
    cmd = [sys.executable, '-m', args.tool] + spec['args']
    print(f"[static_analysis] {spec['desc']}")
    print(f"[static_analysis] $ {' '.join(cmd)}")
    print(f"[static_analysis] {spec['disabled_note']}")

    REPORTS.mkdir(parents=True, exist_ok=True)

    proc = subprocess.run(cmd, capture_output=True, text=True,
                          encoding='utf-8', errors='replace', cwd=str(BASE_DIR))

    if proc.returncode not in spec['ok_codes']:
        return fail(args.tool, f'{args.tool} 退出码 {proc.returncode}（工具出错，不是发现问题）',
                    (proc.stderr or '').strip()[-2000:])

    try:
        raw = json.loads(proc.stdout or '')
    except json.JSONDecodeError as e:
        return fail(args.tool, f'{args.tool} 的输出不是合法 JSON：{e}',
                    (proc.stdout or '')[:500] + (proc.stderr or '')[-500:])

    if args.tool == 'ruff':
        items = parse_ruff(raw)
        extra = None
    else:
        items, tool_errors = parse_bandit(raw)
        if tool_errors:
            # bandit 对某些文件解析失败时会把原因放在 errors 里，但整体仍然算跑完。
            # 不静默吞掉：报出来，但不判失败。
            print(f'[static_analysis] 注意：bandit 有 {len(tool_errors)} 条解析错误：')
            for e in tool_errors[:5]:
                print(f'    {e}')
        extra = spec['disabled_note']

    counts = by_code(items)
    payload = {
        'tool': args.tool,
        'ok': True,
        'error': None,
        'desc': spec['desc'],
        'command': ' '.join(cmd),
        'note': extra,
        'count': len(items),
        'by_code': counts,
        'items': items,
    }
    path = write_report(args.tool, payload)

    # ---- 控制台摘要：给人看的。全量明细在 json 里 ----
    if not items:
        print(f'[static_analysis] {args.tool}：0 条')
    else:
        summary = '、'.join(f'{k} {v}' for k, v in counts.items())
        print(f'[static_analysis] {args.tool}：{len(items)} 条（{summary}）')
        for it in items[:args.max_items]:
            print(f"    {it['file']}:{it['line']}:{it['col']}  {it['code']}  {it['message']}")
        if len(items) > args.max_items:
            print(f"    ...（还有 {len(items) - args.max_items} 条，全量见 {path.name}）")
    print(f'[static_analysis] 报告已写出：{path}')

    # 观察到问题也算成功 —— 观察期由质量门禁汇总，不由这一步阻断
    return 0


if __name__ == '__main__':
    sys.exit(main())
