#!/usr/bin/env python3
"""
统一LLM调用层 — 通过OpenRouter访问多模型
所有情报线的LLM调用统一收敛到此模块，不再直接调用Anthropic/DeepSeek等单独API。

支持模型（均通过OpenRouter转接，单一API Key）：
  - deepseek/deepseek-chat (DeepSeek V3.2, 最便宜, $0.14/$0.28/M)
  - qwen/qwen3.5-plus-02-15 (Qwen 3.5 Plus, 1M上下文, $0.26/$1.56/M)
  - z-ai/glm-5 (GLM-5, 中国市场专长, $0.80/$2.56/M)
  - google/gemini-3.1-flash-lite-preview (Gemini 3.1, 数据分析, $0.25/$1.50/M)
  - x-ai/grok-4.1-fast (Grok 4.1, 市场情绪, $0.20/$0.50/M)

董事会2026-03-04选型决议：
  Line 2 加密投研: 主力 deepseek, 备选 qwen
  Line 3 A股情报: 主力 qwen, 备选 glm5
  Line 4 AI产业:  主力 deepseek, 备选 gemini
"""
import os
import json
from urllib.request import Request, urlopen

OPENROUTER_API_KEY = os.environ.get('OPENROUTER_API_KEY', '')
OPENROUTER_API = 'https://openrouter.ai/api/v1/chat/completions'

# 预定义模型 — 短名→OpenRouter model ID
MODELS = {
    'deepseek': 'deepseek/deepseek-chat',
    'qwen': 'qwen/qwen3.5-plus-02-15',
    'glm5': 'z-ai/glm-5',
    'gemini': 'google/gemini-3.1-flash-lite-preview',
    'grok': 'x-ai/grok-4.1-fast',
}


def call_llm(system_prompt, user_prompt, model='deepseek', fallback='qwen',
             max_tokens=8000, timeout=180):
    """
    调用LLM分析（通过OpenRouter统一网关）。

    Args:
        system_prompt: 系统提示词（角色设定+方法论）
        user_prompt: 用户消息（数据+指令）
        model: 主力模型短名 ('deepseek'/'qwen'/'glm5'/'gemini'/'grok')
        fallback: 备选模型短名，主力失败时自动切换
        max_tokens: 最大输出token数
        timeout: API超时秒数

    Returns:
        str: LLM响应文本，所有模型均失败返回None
    """
    if not OPENROUTER_API_KEY:
        print('  [llm] ❌ OPENROUTER_API_KEY 未配置')
        return None

    model_id = MODELS.get(model, model)
    fallback_id = MODELS.get(fallback, fallback) if fallback else None

    # 尝试主力模型
    print(f'  [llm] 调用主力模型 {model_id}...')
    result = _call_openrouter(model_id, system_prompt, user_prompt, max_tokens, timeout)
    if result:
        return result

    # 主力失败 → 自动切换备选
    if fallback_id and fallback_id != model_id:
        print(f'  [llm] 主力失败，切换备选 {fallback_id}...')
        result = _call_openrouter(fallback_id, system_prompt, user_prompt, max_tokens, timeout)
        if result:
            return result

    print('  [llm] ❌ 所有模型均失败')
    return None


def _call_openrouter(model_id, system_prompt, user_prompt, max_tokens, timeout):
    """底层OpenRouter API调用（OpenAI兼容格式）"""
    headers = {
        'Authorization': f'Bearer {OPENROUTER_API_KEY}',
        'Content-Type': 'application/json',
        'HTTP-Referer': 'https://chaoshpc.com',
        'X-Title': 'Intelligence System',
    }

    payload = {
        'model': model_id,
        'messages': [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_prompt},
        ],
        'max_tokens': max_tokens,
    }

    try:
        body = json.dumps(payload).encode('utf-8')
        req = Request(OPENROUTER_API, data=body, headers=headers, method='POST')
        resp = urlopen(req, timeout=timeout)
        result = json.loads(resp.read())

        # 解析响应
        msg = result['choices'][0]['message']
        content = msg.get('content')

        # thinking模型（GLM-5等）可能content=null，思考过程在reasoning字段
        if not content:
            content = msg.get('reasoning', '')

        if not content:
            print(f'  [llm] {model_id} 返回空响应')
            return None

        # 日志
        usage = result.get('usage', {})
        tokens_in = usage.get('prompt_tokens', 0)
        tokens_out = usage.get('completion_tokens', 0)
        cost = usage.get('total_cost', 0)
        cost_str = f' (${cost:.4f})' if cost else ''
        print(f'  [llm] ✅ {model_id}: {tokens_in} in / {tokens_out} out{cost_str}')
        return content

    except Exception as e:
        print(f'  [llm] ❌ {model_id} 失败: {e}')
        return None
