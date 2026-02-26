#!/usr/bin/env python3
"""
新闻公司审核员Agent — Auditor Agent
极度强迫症 + 不信任同事，严苛审查新闻公司所有工作
每日09:00 BJT自动运行（GitHub Actions），情报推送1小时后审查

检查项A: 全局记忆同步（CLAUDE.md vs 实际状态）
检查项B: Server酱通知合规（每日情报是否成功推送）
检查项C: 新闻专项（情报质量、数据源健康、分析师标准）

发现问题 → Server酱告警董事长
一切正常 → 静默（不打扰董事长）
"""
import sys
import os
import io
import json
import time
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

# Windows UTF-8
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# ============================================================
# 配置
# ============================================================
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY') or \
    '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'
ANTHROPIC_MODEL = 'claude-sonnet-4-20250514'
SERVERCHAN_KEY = os.environ.get('SERVERCHAN_KEY') or 'SCT314848TkLunKgpZEAAbT1YPYUIHrI4F'
SUPABASE_URL = os.environ.get('SUPABASE_URL') or 'https://dmdicqhkjefxethauypp.supabase.co'
SUPABASE_KEY = os.environ.get('SUPABASE_KEY') or \
    'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImRtZGljcWhramVmeGV0aGF1eXBwIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc2OTgxMTMyMiwiZXhwIjoyMDg1Mzg3MzIyfQ.hAbf2cC97-iLsmplti_S1HjnKS0h7nbs9plmkKqlMsc'

BJT = timezone(timedelta(hours=8))


# ============================================================
# 工具函数
# ============================================================
def _http_get_json(url, headers=None, timeout=12):
    hdrs = {'User-Agent': 'NewsAuditor/1.0'}
    if headers:
        hdrs.update(headers)
    req = Request(url, headers=hdrs)
    return json.loads(urlopen(req, timeout=timeout).read().decode())


def push_serverchan(title, desp):
    if not SERVERCHAN_KEY:
        return False
    try:
        data = json.dumps({'title': title, 'desp': desp}).encode('utf-8')
        req = Request(f'https://sctapi.ftqq.com/{SERVERCHAN_KEY}.send',
                      data=data, headers={'Content-Type': 'application/json; charset=utf-8'})
        resp = json.loads(urlopen(req, timeout=30).read())
        return resp.get('code') == 0
    except Exception as e:
        print(f'  [Server酱] {e}')
        return False


# ============================================================
# 检查项B: Server酱通知合规 — 每日情报是否推送成功
# ============================================================
def check_daily_push():
    """检查今日每日市场情报是否已成功推送到Supabase"""
    now = datetime.now(BJT)
    today = now.strftime('%Y-%m-%d')
    issues = []

    try:
        url = (f'{SUPABASE_URL}/rest/v1/daily_intelligence'
               f'?date=eq.{today}&select=date,news_count,created_at')
        req = Request(url, headers={
            'apikey': SUPABASE_KEY,
            'Authorization': f'Bearer {SUPABASE_KEY}',
        })
        resp = json.loads(urlopen(req, timeout=15).read().decode())

        if not resp:
            # 没有今日记录
            if now.hour >= 9:  # 已过09:00 BJT（情报应在08:00推送）
                issues.append({
                    'level': 'RED',
                    'check': 'B-每日情报推送',
                    'detail': f'{today} 每日市场情报未推送！已过08:00超过{now.hour - 8}小时。'
                })
            else:
                print(f'  [B] 今日情报尚未推送（当前{now.strftime("%H:%M")}，08:00前正常）')
        else:
            record = resp[0]
            news_count = record.get('news_count', 0)
            print(f'  [B] 今日情报已推送 ✓ (新闻数: {news_count})')

            if news_count < 5:
                issues.append({
                    'level': 'YELLOW',
                    'check': 'B-新闻采集量',
                    'detail': f'今日新闻仅{news_count}条，远低于正常水平（通常50+），数据源可能异常。'
                })

    except Exception as e:
        issues.append({
            'level': 'YELLOW',
            'check': 'B-Supabase查询',
            'detail': f'无法查询Supabase daily_intelligence表: {e}'
        })

    return issues


# ============================================================
# 检查项C: 新闻专项 — 情报质量审查（Claude Sonnet审核）
# ============================================================
def check_report_quality():
    """用Claude Sonnet审核今日情报的质量"""
    now = datetime.now(BJT)
    today = now.strftime('%Y-%m-%d')
    issues = []

    # 先拿到今日报告
    try:
        url = (f'{SUPABASE_URL}/rest/v1/daily_intelligence'
               f'?date=eq.{today}&select=report')
        req = Request(url, headers={
            'apikey': SUPABASE_KEY,
            'Authorization': f'Bearer {SUPABASE_KEY}',
        })
        resp = json.loads(urlopen(req, timeout=15).read().decode())
        if not resp or not resp[0].get('report'):
            print('  [C] 无今日报告可审核，跳过质量检查')
            return issues
        report = resp[0]['report']
    except Exception as e:
        print(f'  [C] 获取报告失败: {e}')
        return issues

    # Claude审核
    if not ANTHROPIC_API_KEY:
        print('  [C] 无API Key，跳过Claude质量审核')
        return issues

    audit_prompt = f"""你是一个极度严苛的新闻审核员，审查以下每日市场情报简报。

用以下标准逐项打分（1-10分），并列出具体问题：

1. **板块覆盖** — 是否包含加密货币、A股、全球宏观、跨市场信号四个板块？缺失任何一个扣5分。
2. **结论先行** — 每个板块是否以判断性结论开头，而非罗列数据？
3. **量化有据** — 价格变动是否有具体数字（$xxx, +x.x%），而非"上涨""下跌"等模糊词？
4. **可操作性** — 是否给出了明确的操作建议（方向+置信度+关键价位）？
5. **风险提示** — 是否有风险雷达或风险提示？
6. **数据新鲜度** — 数据是否看起来是今日最新的（非昨日数据重复）？

输出格式（严格JSON）：
{{
  "scores": {{"coverage": X, "conclusion_first": X, "quantified": X, "actionable": X, "risk_aware": X, "freshness": X}},
  "total": X,
  "pass": true/false,
  "issues": ["问题1", "问题2"]
}}

及格线：总分≥42（满分60）。低于42分判定为不合格。
只输出JSON，不要其他文字。

---

待审核报告：

{report[:8000]}"""

    try:
        payload = {
            'model': ANTHROPIC_MODEL,
            'max_tokens': 1000,
            'messages': [{'role': 'user', 'content': audit_prompt}],
        }
        data = json.dumps(payload).encode('utf-8')
        req = Request('https://api.anthropic.com/v1/messages', data=data, headers={
            'x-api-key': ANTHROPIC_API_KEY,
            'anthropic-version': '2023-06-01',
            'content-type': 'application/json',
        })
        resp = json.loads(urlopen(req, timeout=60).read().decode())
        if resp.get('content'):
            raw = resp['content'][0]['text'].strip()
            # 提取JSON（可能被包裹在```json...```中）
            if '```' in raw:
                raw = raw.split('```')[1]
                if raw.startswith('json'):
                    raw = raw[4:]
            audit = json.loads(raw.strip())

            total = audit.get('total', 0)
            passed = audit.get('pass', True)
            audit_issues = audit.get('issues', [])
            scores = audit.get('scores', {})

            score_str = ' | '.join(f'{k}:{v}' for k, v in scores.items())
            print(f'  [C] 质量评分: {total}/60 ({"PASS" if passed else "FAIL"}) [{score_str}]')

            if not passed:
                issues.append({
                    'level': 'YELLOW',
                    'check': 'C-情报质量',
                    'detail': f'今日情报质量不达标（{total}/60）。问题：' + '；'.join(audit_issues[:3])
                })
            elif audit_issues:
                print(f'  [C] 轻微问题（不告警）: {"; ".join(audit_issues[:2])}')

            tokens = resp.get('usage', {})
            print(f'  [C] 审核tokens: in={tokens.get("input_tokens",0)} out={tokens.get("output_tokens",0)}')

    except json.JSONDecodeError as e:
        print(f'  [C] Claude返回非JSON: {e}')
    except Exception as e:
        print(f'  [C] Claude审核失败: {e}')

    return issues


# ============================================================
# 检查项A: GitHub Actions工作流状态
# ============================================================
def check_github_actions():
    """检查daily_intelligence workflow最近一次运行是否成功"""
    issues = []
    gh_token = os.environ.get('GH_TOKEN') or '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'

    try:
        url = 'https://api.github.com/repos/helloworldoccupied/news-secretary/actions/runs?per_page=3'
        req = Request(url, headers={
            'Authorization': f'token {gh_token}',
            'Accept': 'application/vnd.github.v3+json',
        })
        resp = json.loads(urlopen(req, timeout=15).read().decode())
        runs = resp.get('workflow_runs', [])

        if not runs:
            issues.append({
                'level': 'YELLOW',
                'check': 'A-GitHub Actions',
                'detail': '无法获取GitHub Actions运行记录'
            })
            return issues

        latest = runs[0]
        status = latest.get('status', '')
        conclusion = latest.get('conclusion', '')
        name = latest.get('name', '')
        run_started = latest.get('run_started_at', '')

        print(f'  [A] 最近运行: {name} | 状态: {status}/{conclusion} | 时间: {run_started}')

        if conclusion == 'failure':
            issues.append({
                'level': 'RED',
                'check': 'A-GitHub Actions',
                'detail': f'最近一次GitHub Actions运行失败！workflow: {name}, 时间: {run_started}'
            })
        elif status == 'in_progress':
            print(f'  [A] workflow正在运行中')

    except Exception as e:
        print(f'  [A] GitHub API查询失败: {e}')

    return issues


# ============================================================
# 主流程
# ============================================================
def main():
    now = datetime.now(BJT)
    print(f'\n{"="*60}')
    print(f'  新闻公司审核员Agent v1.0')
    print(f'  {now.strftime("%Y-%m-%d %H:%M:%S")} BJT')
    print(f'{"="*60}')

    all_issues = []

    print('\n[A] 检查GitHub Actions状态...')
    all_issues.extend(check_github_actions())

    print('\n[B] 检查每日情报推送...')
    all_issues.extend(check_daily_push())

    print('\n[C] 审核情报质量...')
    all_issues.extend(check_report_quality())

    # 汇总
    reds = [i for i in all_issues if i['level'] == 'RED']
    yellows = [i for i in all_issues if i['level'] == 'YELLOW']

    print(f'\n{"="*60}')
    print(f'  审核完成 | 红色告警: {len(reds)} | 黄色警告: {len(yellows)}')
    print(f'{"="*60}')

    # 有问题才告警，一切正常不打扰董事长
    if reds or yellows:
        title = f'【新闻公司审核员】{"🔴严重" if reds else "🟡"}发现{len(all_issues)}个问题'
        lines = ['## 新闻公司审核报告\n']
        for issue in all_issues:
            emoji = '🔴' if issue['level'] == 'RED' else '🟡'
            lines.append(f'{emoji} **{issue["check"]}**: {issue["detail"]}\n')
        lines.append(f'\n---\n*审核时间: {now.strftime("%Y-%m-%d %H:%M")} BJT*')
        desp = '\n'.join(lines)

        ok = push_serverchan(title, desp)
        print(f'  告警推送: {"OK" if ok else "FAIL"}')
    else:
        print('  一切正常，不打扰董事长 ✓')


if __name__ == '__main__':
    main()
