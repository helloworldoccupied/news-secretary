#!/usr/bin/env python3
"""
统一LLM调用层 — Claude Sonnet为主力，中国LLM为fallback

全集团LLM统一为Claude Sonnet（CLAUDE.md铁律），Anthropic API已充值。
三线情报全部使用Claude Sonnet直连Anthropic API，中国LLM仅作为fallback。

主力模型：
  - claude-sonnet（直连Anthropic API，全集团标准，质量最高）

Fallback模型（Claude不可用时自动切换，通过OpenRouter）：
  - deepseek (DeepSeek V3.2)
  - qwen (Qwen 3.5 Plus)
  - glm5 (GLM-5, 智谱直连备选)

董事长2026-03-04决策：Anthropic官方充值，全线用Claude Sonnet。
"""
import os
import json
from urllib.request import Request, urlopen

# === Claude Sonnet 直连 Anthropic API（主力） ===
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
ANTHROPIC_API = 'https://api.anthropic.com/v1/messages'
ANTHROPIC_MODEL = 'claude-sonnet-4-20250514'

# === OpenRouter（fallback通道） ===
OPENROUTER_API_KEY = os.environ.get('OPENROUTER_API_KEY', '')
OPENROUTER_API = 'https://openrouter.ai/api/v1/chat/completions'

# === 智谱直连（GLM-5 fallback） ===
ZHIPU_API_KEY = os.environ.get('ZHIPU_API_KEY', '')
ZHIPU_API = 'https://open.bigmodel.cn/api/paas/v4/chat/completions'
ZHIPU_MODEL = 'glm-4-plus'

# 哪些模型有直连fallback
DIRECT_FALLBACKS = {'glm5', 'sonnet'}

# 预定义模型 — 短名→OpenRouter model ID（仅fallback使用）
MODELS = {
    'sonnet': 'anthropic/claude-sonnet-4-20250514',  # OpenRouter也可走，但优先直连
    'deepseek': 'deepseek/deepseek-chat',
    'qwen': 'qwen/qwen3.5-plus-02-15',
    'glm5': 'z-ai/glm-5',
    'gemini': 'google/gemini-3.1-flash-lite-preview',
    'grok': 'x-ai/grok-4.1-fast',
}


def call_llm(system_prompt, user_prompt, model='sonnet', fallback='deepseek',
             max_tokens=8000, timeout=180):
    """
    调用LLM分析。

    路由逻辑：
      1. model='sonnet' → 直连Anthropic API（主力，最高质量）
      2. 其他模型 → OpenRouter统一网关
      3. 主力失败 → fallback模型（通过OpenRouter）
      4. 特定模型有直连fallback（如glm5→智谱直连）

    Args:
        system_prompt: 系统提示词（角色设定+方法论）
        user_prompt: 用户消息（数据+指令）
        model: 主力模型短名 ('sonnet'/'deepseek'/'qwen'/'glm5'/'gemini'/'grok')
        fallback: 备选模型短名，主力失败时自动切换
        max_tokens: 最大输出token数
        timeout: API超时秒数

    Returns:
        str: LLM响应文本，所有模型均失败返回None
    """
    # ===== 主力模型 =====
    if model == 'sonnet':
        # Claude Sonnet 直连 Anthropic API（最高优先级）
        if ANTHROPIC_API_KEY:
            print(f'  [llm] 调用主力模型 Claude Sonnet (直连Anthropic)...')
            result = _call_anthropic_direct(system_prompt, user_prompt, max_tokens, timeout)
            if result:
                return result
        else:
            print('  [llm] ⚠️ ANTHROPIC_API_KEY 未配置，跳过Anthropic直连')

        # Anthropic直连失败 → 尝试OpenRouter走Sonnet
        if OPENROUTER_API_KEY:
            model_id = MODELS.get('sonnet', 'anthropic/claude-sonnet-4-20250514')
            print(f'  [llm] Anthropic直连失败，尝试OpenRouter走 {model_id}...')
            result = _call_openrouter(model_id, system_prompt, user_prompt, max_tokens, timeout)
            if result:
                return result
    else:
        # 非Sonnet模型 → OpenRouter
        model_id = MODELS.get(model, model)
        if OPENROUTER_API_KEY:
            print(f'  [llm] 调用主力模型 {model_id}...')
            result = _call_openrouter(model_id, system_prompt, user_prompt, max_tokens, timeout)
            if result:
                return result
        else:
            print('  [llm] ⚠️ OPENROUTER_API_KEY 未配置，跳过OpenRouter')

        # OpenRouter失败 → 尝试直连fallback（如果该模型支持）
        if model in DIRECT_FALLBACKS:
            if model == 'glm5':
                print(f'  [llm] OpenRouter失败，尝试智谱直连 {ZHIPU_MODEL}...')
                result = _call_zhipu_direct(system_prompt, user_prompt, max_tokens, timeout)
                if result:
                    return result

    # ===== Fallback模型 =====
    if fallback:
        fallback_id = MODELS.get(fallback, fallback)
        main_id = MODELS.get(model, model)
        if fallback_id != main_id:
            # 先尝试直连（如果fallback是sonnet）
            if fallback == 'sonnet' and ANTHROPIC_API_KEY:
                print(f'  [llm] 切换备选模型 Claude Sonnet (直连Anthropic)...')
                result = _call_anthropic_direct(system_prompt, user_prompt, max_tokens, timeout)
                if result:
                    return result

            # OpenRouter走fallback
            if OPENROUTER_API_KEY:
                print(f'  [llm] 切换备选模型 {fallback_id}...')
                result = _call_openrouter(fallback_id, system_prompt, user_prompt, max_tokens, timeout)
                if result:
                    return result

            # fallback是glm5时尝试智谱直连
            if fallback == 'glm5':
                print(f'  [llm] 尝试智谱直连 {ZHIPU_MODEL}...')
                result = _call_zhipu_direct(system_prompt, user_prompt, max_tokens, timeout)
                if result:
                    return result

    print('  [llm] ❌ 所有模型均失败')
    return None


def _call_anthropic_direct(system_prompt, user_prompt, max_tokens, timeout):
    """直连Anthropic API（Messages API格式，与OpenAI不同）。

    Anthropic Messages API文档: https://docs.anthropic.com/en/api/messages
    请求格式与OpenAI不同：system是顶层字段，不在messages数组内。
    """
    if not ANTHROPIC_API_KEY:
        print('  [llm] ⚠️ ANTHROPIC_API_KEY 未配置，跳过Anthropic直连')
        return None

    headers = {
        'x-api-key': ANTHROPIC_API_KEY,
        'anthropic-version': '2023-06-01',
        'Content-Type': 'application/json',
    }

    payload = {
        'model': ANTHROPIC_MODEL,
        'max_tokens': max_tokens,
        'system': system_prompt,
        'messages': [
            {'role': 'user', 'content': user_prompt},
        ],
    }

    try:
        body = json.dumps(payload).encode('utf-8')
        req = Request(ANTHROPIC_API, data=body, headers=headers, method='POST')
        resp = urlopen(req, timeout=timeout)
        result = json.loads(resp.read())

        # 解析Anthropic响应格式（与OpenAI不同）
        # Anthropic: {"content": [{"type": "text", "text": "..."}], "usage": {...}}
        content_blocks = result.get('content', [])
        text_parts = []
        for block in content_blocks:
            if block.get('type') == 'text':
                text_parts.append(block.get('text', ''))

        content = '\n'.join(text_parts)

        if not content:
            print(f'  [llm] Anthropic {ANTHROPIC_MODEL} 返回空响应')
            return None

        # 日志
        usage = result.get('usage', {})
        tokens_in = usage.get('input_tokens', 0)
        tokens_out = usage.get('output_tokens', 0)
        print(f'  [llm] ✅ Anthropic {ANTHROPIC_MODEL}: {tokens_in} in / {tokens_out} out')
        return content

    except Exception as e:
        print(f'  [llm] ❌ Anthropic {ANTHROPIC_MODEL} 失败: {e}')
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


def _call_zhipu_direct(system_prompt, user_prompt, max_tokens, timeout):
    """直连智谱AI API（OpenAI兼容格式），OpenRouter上游故障时的fallback。

    智谱API文档: https://open.bigmodel.cn/dev/api
    使用glm-4-plus模型，中国大陆直连可用，无需翻墙。
    """
    if not ZHIPU_API_KEY:
        print('  [llm] ⚠️ ZHIPU_API_KEY 未配置，跳过智谱直连')
        return None

    headers = {
        'Authorization': f'Bearer {ZHIPU_API_KEY}',
        'Content-Type': 'application/json',
    }

    payload = {
        'model': ZHIPU_MODEL,
        'messages': [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_prompt},
        ],
        'max_tokens': max_tokens,
    }

    try:
        body = json.dumps(payload).encode('utf-8')
        req = Request(ZHIPU_API, data=body, headers=headers, method='POST')
        resp = urlopen(req, timeout=timeout)
        result = json.loads(resp.read())

        # 解析响应（OpenAI兼容格式）
        content = result['choices'][0]['message'].get('content', '')
        if not content:
            print(f'  [llm] 智谱直连 {ZHIPU_MODEL} 返回空响应')
            return None

        # 日志
        usage = result.get('usage', {})
        tokens_in = usage.get('prompt_tokens', 0)
        tokens_out = usage.get('completion_tokens', 0)
        print(f'  [llm] ✅ 智谱直连 {ZHIPU_MODEL}: {tokens_in} in / {tokens_out} out')
        return content

    except Exception as e:
        print(f'  [llm] ❌ 智谱直连 {ZHIPU_MODEL} 失败: {e}')
        return None
