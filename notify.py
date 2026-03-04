#!/usr/bin/env python3
"""
统一推送层 — 所有推送收敛到此模块
双通道：
  - 飞书 (Feishu/Lark): 正文主通道，发送投研报告全文
  - Server酱 (ServerChan): 状态提醒通道，只发送简短状态

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
FEISHU_APP_ID = os.environ.get('FEISHU_APP_ID', '')
FEISHU_APP_SECRET = os.environ.get('FEISHU_APP_SECRET', '')
FEISHU_CHAT_ID = os.environ.get('FEISHU_CHAT_ID', '')

SERVERCHAN_API = 'https://sctapi.ftqq.com/{key}.send'
FEISHU_TOKEN_API = 'https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal'
FEISHU_MSG_API = 'https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id'


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
# 飞书 — 正文主通道
# ============================================================
def _get_feishu_token():
    """获取飞书 tenant_access_token"""
    if not FEISHU_APP_ID or not FEISHU_APP_SECRET:
        return None
    try:
        data = json.dumps({
            'app_id': FEISHU_APP_ID,
            'app_secret': FEISHU_APP_SECRET
        }).encode('utf-8')
        req = Request(FEISHU_TOKEN_API, data=data,
                      headers={'Content-Type': 'application/json'})
        resp = json.loads(urlopen(req, timeout=10).read())
        if resp.get('code') == 0:
            return resp.get('tenant_access_token')
        print(f'  [notify] 飞书token获取失败: {resp}')
        return None
    except Exception as e:
        print(f'  [notify] 飞书token异常: {e}')
        return None


def push_feishu_report(title, content, chat_id=None):
    """
    飞书正文推送（长消息）。
    用于：发送投研报告、新闻简报等完整正文。

    Args:
        title: 消息标题
        content: 正文内容（markdown 格式）
        chat_id: 飞书群 chat_id，默认用环境变量中的 FEISHU_CHAT_ID
    """
    target_chat = chat_id or FEISHU_CHAT_ID
    if not target_chat:
        print(f'  [notify] 飞书 chat_id 未配置，跳过正文推送')
        return False

    token = _get_feishu_token()
    if not token:
        print(f'  [notify] 飞书 token 获取失败，跳过正文推送')
        return False

    # 飞书消息卡片格式 — 按##标题分段，每段独立div+分隔线，提升可读性
    elements = []

    # 按 ## 标题拆分内容为多个段落
    sections = re.split(r'(?=^## )', content[:30000], flags=re.MULTILINE)
    sections = [s.strip() for s in sections if s.strip()]

    if not sections:
        # 没有标题结构，直接放一个大块
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": content[:30000]}
        })
    else:
        for i, section in enumerate(sections):
            # 提取标题和正文
            lines = section.split('\n', 1)
            heading = lines[0].lstrip('#').strip() if lines[0].startswith('#') else ''
            body = lines[1].strip() if len(lines) > 1 else section

            if heading:
                # 分隔线（非首个段落）
                if i > 0:
                    elements.append({"tag": "hr"})
                # 段落标题（加粗大字）
                elements.append({
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": f"**📌 {heading}**"}
                })

            # 段落正文
            if body:
                elements.append({
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": body}
                })

    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "template": "blue"
        },
        "elements": elements
    }

    msg_body = {
        "receive_id": target_chat,
        "msg_type": "interactive",
        "content": json.dumps(card)
    }

    try:
        data = json.dumps(msg_body).encode('utf-8')
        req = Request(FEISHU_MSG_API, data=data, headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {token}'
        })
        resp = json.loads(urlopen(req, timeout=15).read())
        ok = resp.get('code') == 0
        print(f'  [notify] 飞书正文推送{"成功" if ok else "失败"}: {title}')
        return ok
    except Exception as e:
        print(f'  [notify] 飞书正文推送异常: {e}')
        return False


# ============================================================
# 兼容层 — 供现有脚本平滑迁移
# ============================================================
def push_serverchan_report(title, content):
    """
    Server酱长正文推送（向后兼容）。
    飞书未配置时的 fallback 通道。
    长报告会按 ## 标题自动拆分为多条消息。
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
