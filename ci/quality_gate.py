#!/usr/bin/env python
"""质量门禁（阶段 1.3）：把前面各环节的结果汇总成一张表。

按规划的「原则 3」，**默认只汇总、不阻断**：观察期跑一段、误报调完了，
再把 Jenkinsfile 里的 ENFORCE_QUALITY_GATE 改成 true，它才会真的让构建失败。
一次加一堆卡点的结果是流水线天天红，然后所有人学会忽略它 —— 那比没有更糟。

输入（都在 reports/ 下，缺哪个就把哪条标成"未产出"，**不算失败**）：
  junit.xml     单元测试结果
  coverage.xml  覆盖率
  deploy.env    部署后实际的镜像 / 副本数 / 重启次数（kubectl 容器写）
  smoke.json    节点冒烟结果
  ruff.json     静态分析结果（ci/static_analysis.py 写，阶段 2.1）
  bandit.json   安全扫描结果（ci/static_analysis.py 写，阶段 2.2）

输出：reports/gate-summary.md（给人看）、reports/gate-summary.json（给机器看）
退出码：非 --enforce 恒为 0；--enforce 且有启用的检查失败 → 1
"""
import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
REPORTS = BASE_DIR / 'reports'

# Windows 控制台默认 GBK，直接 print 中文/emoji 会 UnicodeEncodeError。
# 容器里是 UTF-8 没问题，但在本地跑就会炸，所以显式转一下。
try:
    sys.stdout.reconfigure(encoding='utf-8')
except (AttributeError, ValueError):
    pass


def parse_junit(path):
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == 'testsuite' else root.findall('testsuite')
    total = failures = errors = skipped = 0
    for s in suites:
        total += int(s.get('tests', 0))
        failures += int(s.get('failures', 0))
        errors += int(s.get('errors', 0))
        skipped += int(s.get('skipped', 0))
    return total, failures, errors, skipped


def parse_coverage(path):
    root = ET.parse(path).getroot()
    return float(root.get('line-rate', 0)) * 100


def parse_env_file(path):
    data = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        if '=' in line:
            key, value = line.split('=', 1)
            data[key.strip()] = value.strip()
    return data


def collect(min_coverage=None):
    """把各环节的结果读成一张检查表。

    每条都是 (名称, 是否启用, 是否通过, 说明)。"未产出"= 不启用 = 不算失败，
    这样单元测试关掉、或者分支只构建不部署时，门禁不会凭空报红。
    """
    checks = []
    ### (name, is_enabled, ok, detail)
    # ---- 单元测试 ----
    junit = REPORTS / 'junit.xml'
    if junit.exists():
        total, failures, errors, skipped = parse_junit(junit)
        ok = total > 0 and failures == 0 and errors == 0
        detail = f'{total} 个用例，失败 {failures}，错误 {errors}，跳过 {skipped}'
        checks.append(('单元测试', True, ok, detail))
    else:
        checks.append(('单元测试', False, True, '未产出 junit.xml'))

    # ---- 覆盖率 ----
    coverage = REPORTS / 'coverage.xml'
    if coverage.exists():
        rate = parse_coverage(coverage)
        if min_coverage is None:
            # 阶段 1 不设阈值：先用几轮观察期看看稳定值在哪，避免拍脑袋定个数字天天红
            checks.append(('覆盖率', True, True, f'{rate:.1f}%（未设阈值，仅记录）'))
        else:
            checks.append((
                '覆盖率', True, rate >= min_coverage,
                f'{rate:.1f}%（阈值 {min_coverage:.1f}%）',
            ))
    else:
        checks.append(('覆盖率', False, True, '未产出 coverage.xml'))

    # ---- 部署结果 ----
    deploy_env = REPORTS / 'deploy.env'
    if deploy_env.exists():
        d = parse_env_file(deploy_env)
        actual = d.get('DEPLOY_IMAGE', '')
        expected = d.get('DEPLOY_EXPECTED_IMAGE', '')
        checks.append((
            '部署镜像与本次构建一致', True, actual == expected,
            f'实际 {actual}｜期望 {expected}',
        ))

        ready = int(d.get('DEPLOY_READY_REPLICAS', 0) or 0)
        replicas = int(d.get('DEPLOY_REPLICAS', 0) or 0)
        checks.append((
            '副本全部就绪', True, replicas > 0 and ready >= replicas,
            f'{ready}/{replicas}（namespace={d.get("DEPLOY_NS", "?")}，pod={d.get("DEPLOY_POD", "?")}）',
        ))

        restarts = int(d.get('DEPLOY_RESTARTS', 0) or 0)
        checks.append((
            'Pod 无重启', True, restarts == 0,
            f'重启 {restarts} 次',
        ))
    else:
        for name in ('部署镜像与本次构建一致', '副本全部就绪', 'Pod 无重启'):
            checks.append((name, False, True, '未产出 deploy.env（本次未部署）'))

    # ---- 节点冒烟 ----
    smoke = REPORTS / 'smoke.json'
    if smoke.exists():
        s = json.loads(smoke.read_text(encoding='utf-8'))
        failed = [c['name'] for c in s.get('checks', []) if not c['ok']]
        detail = f'全过（{s.get("base_url", "?")}）' if not failed else '失败：' + '、'.join(failed)
        checks.append(('节点冒烟', True, bool(s.get('ok')), detail))
    else:
        checks.append(('节点冒烟', False, True, '未产出 smoke.json'))

    # ---- 静态分析 / 安全扫描（阶段 2.1 / 2.2）----
    # 两份报告由 ci/static_analysis.py 归一化成同一个 schema，所以这里一个循环就够。
    # 注意 detail 里不能用半角竖线 —— 它会把这行 markdown 表格切成两列。
    for tool, name in (('ruff', '静态分析(ruff)'), ('bandit', '安全扫描(bandit)')):
        report = REPORTS / f'{tool}.json'
        if not report.exists():
            checks.append((name, False, True, f'未产出 {tool}.json'))
            continue

        r = json.loads(report.read_text(encoding='utf-8'))
        if r.get('error'):
            # 有报告但工具没跑起来 —— 这是流水线的故障，不是"没启用"，必须判失败
            checks.append((name, True, False, f'工具没跑起来：{r["error"]}'))
            continue

        items = r.get('items', [])
        if not items:
            checks.append((name, True, True, '0 条' + (f'；{r["note"]}' if r.get('note') else '')))
            continue

        # 摘要里给出"按规则码的分布 + 前几条的 file:line"：
        # 阶段 2 的验收标准是"每类问题都能在报告里定位到具体文件行号"，所以行号要在门禁表里就能看见，
        # 不能只给个数字让人再去翻 json。
        head = '、'.join(f'{code} {n}' for code, n in list(r.get('by_code', {}).items())[:4])
        where = '、'.join(f'{i["file"]}:{i["line"]}' for i in items[:3])
        more = f'，等 {len(items)} 条' if len(items) > 3 else ''
        checks.append((name, True, False, f'{len(items)} 条（{head}）；如 {where}{more}'))

    return checks


def render_markdown(checks, enforced):
    enabled = [c for c in checks if c[1]]
    failed = [c for c in enabled if not c[2]]
    lines = [
        '## 质量门禁汇总',
        '',
        f'模式：**{"门禁期（会阻断）" if enforced else "观察期（只汇总，不阻断）"}**',
        '',
        '| 检查项 | 结果 | 说明 |',
        '|---|---|---|',
    ]
    for name, is_enabled, ok, detail in checks:
        if not is_enabled:
            mark = '—'
        else:
            mark = '✅' if ok else '❌'
        lines.append(f'| {name} | {mark} | {detail} |')
    lines.append('')
    lines.append(f'启用 {len(enabled)} 项，失败 {len(failed)} 项。')
    if not enforced and failed:
        lines.append('')
        lines.append('> 观察期：以上失败**不会**让构建变红。调好误报后把 `ENFORCE_QUALITY_GATE` 改成 `true`。')
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--enforce', action='store_true', help='启用阻断：有失败就退出码 1')
    parser.add_argument('--min-coverage', type=float, default=None,
                        help='覆盖率阈值（%%）。不给就只记录不判定')
    args = parser.parse_args()

    checks = collect(args.min_coverage)
    markdown = render_markdown(checks, args.enforce)
    print(markdown)

    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / 'gate-summary.md').write_text(markdown + '\n', encoding='utf-8')
    (REPORTS / 'gate-summary.json').write_text(
        json.dumps({
            'enforced': args.enforce,
            'checks': [
                {'name': n, 'enabled': e, 'ok': o, 'detail': d} for n, e, o, d in checks
            ],
        }, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )

    failed = [n for n, e, o, _ in checks if e and not o]
    if args.enforce and failed:
        print(f'[gate] 门禁未通过：{"、".join(failed)}')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
