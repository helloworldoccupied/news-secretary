#!/usr/bin/env python3
"""
统一推送层 — 所有推送收敛到此模块
单通道：Server酱 (ServerChan) — 推送到董事长微信

飞书已于2026-03-04完全废弃（董事长决策），所有推送统一Server酱。
任何脚本不应直接调用推送 API，统一通过本模块的函数调用。
"""
import os
import json
import time
import re
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

# ============================================================
# 配置（从环境变量读取）
# ============================================================
SERVERCHAN_KEY = os.environ.get('SERVERCHAN_KEY', '')
SERVERCHAN_API = 'https://sctapi.ftqq.com/{key}.send'


# ============================================================
# Server酱 — 状态提醒通道
# ============================================================
def push_serverchan_status(task_name, status, summary=''):
    """
    Server酱状态推送（短消息）。
    用于：任务开始/成功/失败/审核告警。
    不用于发送长正文。

    Args:
        task_name: 任务名称，如 "加密投研日报", "审核员巡检"
        status: 状态，如 "开始", "成功", "失败", "告警"
        summary: 简短摘要（1-2句），可选
    """
    if not SERVERCHAN_KEY:
        print(f'  [notify] Server酱 key 未配置，跳过状态推送')
        return False

    status_emoji = {
        '开始': '🟡', '成功': '✅', '失败': '❌', '告警': '🚨'
    }.get(status, '📋')

    title = f'【情报】{status_emoji} {task_name} — {status}'
    desp = summary if summary else ''

    try:
        data = json.dumps({'title': title, 'desp': desp}).encode('utf-8')
        req = Request(
            SERVERCHAN_API.format(key=SERVERCHAN_KEY),
            data=data,
            headers={'Content-Type': 'application/json; charset=utf-8'},
            method='POST'
        )
        resp = json.loads(urlopen(req, timeout=15).read())
        ok = resp.get('code') == 0
        print(f'  [notify] Server酱状态推送{"成功" if ok else "失败"}: {title}')
        return ok
    except Exception as e:
        print(f'  [notify] Server酱状态推送异常: {e}')
        return False


# ============================================================
# Server酱 — 长正文推送（主通道）
# ============================================================
def push_serverchan_report(title, content):
    """
    Server酱长正文推送。
    长报告会按 ## 标题自动拆分为多条消息（Server酱单条限制25000字符）。
    """
    if not SERVERCHAN_KEY:
        print(f'  [notify] Server酱 key 未配置，跳过报告推送')
        return False

    # 短内容直接发
    if len(content) <= 25000:
        return _raw_serverchan(title, content)

    # 长内容按 ## 标题拆分
    sections = re.split(r'(?=^## )', content, flags=re.MULTILINE)
    sections = [s.strip() for s in sections if s.strip()]

    if not sections:
        return _raw_serverchan(title, content[:25000])

    messages = []
    current = ''
    current_title = ''

    for section in sections:
        if len(current) + len(section) > 25000:
            if current:
                messages.append((current_title, current))
            current = section
            m = re.match(r'^## (.+)', section)
            current_title = m.group(1) if m else '续'
        else:
            if not current_title:
                m = re.match(r'^## (.+)', section)
                current_title = m.group(1) if m else '报告'
            current += '\n\n' + section if current else section

    if current:
        messages.append((current_title, current))

    # 二次拆分：单个消息仍超25000字符时按字符硬切
    final_messages = []
    for msg_title, msg_content in messages:
        if len(msg_content) <= 25000:
            final_messages.append((msg_title, msg_content))
        else:
            chunks = [msg_content[i:i+25000] for i in range(0, len(msg_content), 25000)]
            for j, chunk in enumerate(chunks):
                suffix = f' 续{j+1}' if j > 0 else ''
                final_messages.append((f'{msg_title}{suffix}', chunk))

    total = len(final_messages)
    ok = True
    for i, (sec_title, sec_content) in enumerate(final_messages, 1):
        tag = f'({i}/{total})' if total > 1 else ''
        result = _raw_serverchan(f'{title} {sec_title}{tag}', sec_content)
        ok = ok and result
        if i < total:
            time.sleep(2)
    return ok


def _raw_serverchan(title, desp):
    """底层 Server酱 API 调用"""
    try:
        data = json.dumps({'title': title, 'desp': desp}).encode('utf-8')
        req = Request(
            SERVERCHAN_API.format(key=SERVERCHAN_KEY),
            data=data,
            headers={'Content-Type': 'application/json; charset=utf-8'},
            method='POST'
        )
        resp = json.loads(urlopen(req, timeout=15).read())
        ok = resp.get('code') == 0
        print(f'  [notify] Server酱{"成功" if ok else "失败"}: {title}')
        return ok
    except Exception as e:
        print(f'  [notify] Server酱异常: {e}')
        return False
