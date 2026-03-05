#!/usr/bin/env python3
"""
晨间总快照 — Market Morning Snapshot
每天晨间第一个推送产品，4个板块固定顺序。

板块（顺序不可变）：
  1. 虚拟资产 (crypto_summary)
  2. A股 (ashare_summary)
  3. AI / 具身机器人 (ai_robotics_summary)
  4. 今日机会与风险 (today_opportunities + today_risks + execution_note)

流程：采集数据 → 结构化 JSON → Claude 生成快照 → Server酱推送（飞书已废弃）
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
# 配置（全部从环境变量读取）
# ============================================================
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
ANTHROPIC_MODEL = 'claude-sonnet-4-20250514'
SUPABASE_URL = os.environ.get('SUPABASE_URL', '')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY', '')

UA = {'User-Agent': 'MarketSnapshot/1.0'}
BJT = timezone(timedelta(hours=8))


# ============================================================
# 数据采集（轻量，快速，只取核心指标）
# ============================================================
def _get_json(url, timeout=10):
    try:
        req = Request(url, headers=UA)
        return json.loads(urlopen(req, timeout=timeout).read().decode())
    except Exception as e:
        print(f'  [fetch] {url[:60]}... failed: {e}')
        return None


def collect_crypto():
    """虚拟资产核心指标"""
    data = {}

    # BTC/ETH 价格
    prices = _get_json('https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum,solana&vs_currencies=usd&include_24hr_change=true')
    if prices:
        data['prices'] = prices

    # 全局市场
    global_data = _get_json('https://api.coingecko.com/api/v3/global')
    if global_data and 'data' in global_data:
        g = global_data['data']
        data['total_market_cap'] = g.get('total_market_cap', {}).get('usd')
        data['market_cap_change_24h'] = g.get('market_cap_change_percentage_24h_usd')
        data['btc_dominance'] = g.get('market_cap_percentage', {}).get('btc')

    # Fear & Greed
    fg = _get_json('https://api.alternative.me/fng/?limit=1')
    if fg and fg.get('data'):
        data['fear_greed'] = {
            'value': int(fg['data'][0]['value']),
            'label': fg['data'][0]['value_classification']
        }

    return data


def collect_ashare():
    """A股核心指标"""
    data = {}

    # 上证指数
    try:
        url = 'https://push2.eastmoney.com/api/qt/stock/get?fields=f43,f44,f45,f46,f47,f170&secid=1.000001'
        result = _get_json(url)
        if result and result.get('data'):
            d = result['data']
            data['sh_index'] = {
                'price': d.get('f43', 0) / 100,
                'change_pct': d.get('f170', 0) / 100,
                'high': d.get('f44', 0) / 100,
                'low': d.get('f45', 0) / 100,
            }
    except Exception:
        pass

    # 深证成指
    try:
        url = 'https://push2.eastmoney.com/api/qt/stock/get?fields=f43,f170&secid=0.399001'
        result = _get_json(url)
        if result and result.get('data'):
            d = result['data']
            data['sz_index'] = {
                'price': d.get('f43', 0) / 100,
                'change_pct': d.get('f170', 0) / 100,
            }
    except Exception:
        pass

    return data


def collect_ai_robotics():
    """AI / 具身机器人板块（公开信息源）"""
    data = {}

    # NVIDIA 股价（AI风向标）
    try:
        url = 'https://query1.finance.yahoo.com/v8/finance/chart/NVDA?range=2d&interval=1d'
        result = _get_json(url)
        if result:
            meta = result.get('chart', {}).get('result', [{}])[0].get('meta', {})
            data['nvda'] = {
                'price': meta.get('regularMarketPrice'),
                'prev_close': meta.get('chartPreviousClose'),
            }
            if data['nvda']['price'] and data['nvda']['prev_close']:
                data['nvda']['change_pct'] = round(
                    (data['nvda']['price'] / data['nvda']['prev_close'] - 1) * 100, 2)
    except Exception:
        pass

    # 机器人ETF（BOTZ）
    try:
        url = 'https://query1.finance.yahoo.com/v8/finance/chart/BOTZ?range=2d&interval=1d'
        result = _get_json(url)
        if result:
            meta = result.get('chart', {}).get('result', [{}])[0].get('meta', {})
            data['botz'] = {
                'price': meta.get('regularMarketPrice'),
                'prev_close': meta.get('chartPreviousClose'),
            }
            if data['botz']['price'] and data['botz']['prev_close']:
                data['botz']['change_pct'] = round(
                    (data['botz']['price'] / data['botz']['prev_close'] - 1) * 100, 2)
    except Exception:
        pass

    return data


def collect_macro():
    """宏观关联指标"""
    data = {}
    symbols = {
        'DXY': 'DX-Y.NYB',
        'gold': 'GC=F',
        'us10y': '^TNX',
        'spx': '^GSPC',
    }
    for name, symbol in symbols.items():
        try:
            url = f'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=2d&interval=1d'
            result = _get_json(url)
            if result:
                meta = result.get('chart', {}).get('result', [{}])[0].get('meta', {})
                price = meta.get('regularMarketPrice')
                prev = meta.get('chartPreviousClose')
                data[name] = {'price': price}
                if price and prev:
                    data[name]['change_pct'] = round((price / prev - 1) * 100, 2)
        except Exception:
            pass
    return data


# ============================================================
# 结构化 JSON 构建
# ============================================================
def build_structured_data(crypto, ashare, ai_robo, macro):
    """将采集的原始数据构建为工单规定的结构化 JSON"""
    now = datetime.now(BJT)

    structured = {
        'date': now.strftime('%Y-%m-%d'),
        'time_bjt': now.strftime('%H:%M'),
        'crypto_summary': _format_crypto(crypto),
        'ashare_summary': _format_ashare(ashare),
        'ai_robotics_summary': _format_ai_robo(ai_robo),
        'macro_context': _format_macro(macro),
        'today_opportunities': '',   # Claude 填充
        'today_risks': '',           # Claude 填充
        'execution_note': '',        # Claude 填充
    }
    return structured


def _format_crypto(data):
    parts = []
    prices = data.get('prices', {})
    for coin, key in [('BTC', 'bitcoin'), ('ETH', 'ethereum'), ('SOL', 'solana')]:
        p = prices.get(key, {})
        price = p.get('usd')
        chg = p.get('usd_24h_change')
        if price:
            parts.append(f'{coin} ${price:,.0f}' + (f' ({chg:+.1f}%)' if chg else ''))

    cap = data.get('total_market_cap')
    if cap:
        parts.append(f'总市值 ${cap/1e12:.2f}T')

    dom = data.get('btc_dominance')
    if dom:
        parts.append(f'BTC市占 {dom:.1f}%')

    fg = data.get('fear_greed', {})
    if fg.get('value'):
        parts.append(f'恐贪指数 {fg["value"]} ({fg["label"]})')

    return ' | '.join(parts) if parts else '数据暂不可用'


def _format_ashare(data):
    parts = []
    sh = data.get('sh_index', {})
    if sh.get('price'):
        parts.append(f'上证 {sh["price"]:.2f} ({sh.get("change_pct", 0):+.2f}%)')

    sz = data.get('sz_index', {})
    if sz.get('price'):
        parts.append(f'深证 {sz["price"]:.2f} ({sz.get("change_pct", 0):+.2f}%)')

    return ' | '.join(parts) if parts else '非交易时间或数据暂不可用'


def _format_ai_robo(data):
    parts = []
    nvda = data.get('nvda', {})
    if nvda.get('price'):
        parts.append(f'NVDA ${nvda["price"]:.2f} ({nvda.get("change_pct", 0):+.1f}%)')

    botz = data.get('botz', {})
    if botz.get('price'):
        parts.append(f'BOTZ ${botz["price"]:.2f} ({botz.get("change_pct", 0):+.1f}%)')

    return ' | '.join(parts) if parts else '数据暂不可用'


def _format_macro(data):
    parts = []
    for name, label in [('DXY', '美元'), ('gold', '黄金'), ('us10y', '美10Y'), ('spx', 'SPX')]:
        d = data.get(name, {})
        if d.get('price'):
            chg = d.get('change_pct')
            parts.append(f'{label} {d["price"]:.2f}' + (f' ({chg:+.1f}%)' if chg else ''))
    return ' | '.join(parts) if parts else '数据暂不可用'


# ============================================================
# Claude 分析（生成结构化快照）
# ============================================================
def call_claude(structured_data):
    """让 Claude 基于结构化数据生成快照"""
    if not ANTHROPIC_API_KEY:
        print('  [claude] API key 未配置')
        return None

    system_prompt = """你是一位资深市场分析师，负责生成每日晨间快照。

要求：
- 输出严格 JSON 格式，包含 6 个字段
- 每个字段内容简短（2-4句话），移动端易读
- 短句优先，每板块先结论后要点
- 不要写成宏观长文
- 结论明确，不模棱两可
- 用中文"""

    user_msg = f"""基于以下市场数据，生成晨间快照 JSON。

当前数据：
{json.dumps(structured_data, ensure_ascii=False, indent=2)}

请输出严格 JSON（不要 markdown 代码块），包含以下 6 个字段：
{{
  "crypto_summary": "虚拟资产板块总结（2-4句）",
  "ashare_summary": "A股板块总结（2-4句）",
  "ai_robotics_summary": "AI/具身机器人板块总结（2-4句）",
  "today_opportunities": "今日潜在机会（2-3条要点）",
  "today_risks": "今日需关注的风险（2-3条要点）",
  "execution_note": "操作提示（1-2句，最重要的行动建议）"
}}"""

    try:
        body = json.dumps({
            'model': ANTHROPIC_MODEL,
            'max_tokens': 2000,
            'temperature': 0.3,
            'system': system_prompt,
            'messages': [{'role': 'user', 'content': user_msg}],
        }).encode('utf-8')

        req = Request('https://api.anthropic.com/v1/messages', data=body, headers={
            'Content-Type': 'application/json',
            'x-api-key': ANTHROPIC_API_KEY,
            'anthropic-version': '2023-06-01',
        })

        resp = json.loads(urlopen(req, timeout=60).read().decode())
        if resp.get('content') and len(resp['content']) > 0:
            text = resp['content'][0].get('text', '')
            # 解析 JSON
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                import re
                match = re.search(r'\{[\s\S]*\}', text)
                if match:
                    return json.loads(match.group())
            print(f'  [claude] JSON解析失败: {text[:200]}')
        return None
    except Exception as e:
        print(f'  [claude] 调用失败: {e}')
        return None


# ============================================================
# 渲染为推送正文
# ============================================================
def render_snapshot(snapshot, date_str):
    """将结构化 JSON 渲染为Server酱可读的正文"""
    lines = [
        f'# 晨间快照 {date_str}',
        '',
        '## 1. 虚拟资产',
        snapshot.get('crypto_summary', '暂无数据'),
        '',
        '## 2. A股',
        snapshot.get('ashare_summary', '暂无数据'),
        '',
        '## 3. AI / 具身机器人',
        snapshot.get('ai_robotics_summary', '暂无数据'),
        '',
        '## 4. 今日机会与风险',
        '',
        '**机会:**',
        snapshot.get('today_opportunities', '暂无'),
        '',
        '**风险:**',
        snapshot.get('today_risks', '暂无'),
        '',
        '---',
        f'> {snapshot.get("execution_note", "")}',
    ]
    return '\n'.join(lines)


# ============================================================
# 存档
# ============================================================
def archive_to_supabase(date_str, snapshot_json, rendered_text):
    """存档到 Supabase"""
    if not SUPABASE_URL or not SUPABASE_KEY:
        print('  [archive] Supabase 未配置，跳过存档')
        return False
    try:
        row = {
            'date': date_str,
            'title': f'[Snapshot] {date_str} 晨间快照',
            'content': rendered_text[:50000],
            'raw_data': json.dumps(snapshot_json, ensure_ascii=False)[:50000],
        }
        body = json.dumps(row).encode('utf-8')
        req = Request(f'{SUPABASE_URL}/rest/v1/daily_intelligence', data=body, headers={
            'apikey': SUPABASE_KEY, 'Authorization': f'Bearer {SUPABASE_KEY}',
            'Content-Type': 'application/json', 'Prefer': 'return=minimal',
        }, method='POST')
        urlopen(req, timeout=15)
        print('  Supabase 存档成功')
        return True
    except Exception as e:
        print(f'  Supabase 存档失败: {e}')
        return False


# ============================================================
# 主流程
# ============================================================
def main():
    from notify import push_serverchan_report, push_serverchan_status

    now = datetime.now(BJT)
    date_str = now.strftime('%Y-%m-%d')

    print(f'\n{"="*50}')
    print(f'  晨间快照 — Market Morning Snapshot')
    print(f'  {now.strftime("%Y-%m-%d %H:%M:%S")} BJT')
    print(f'{"="*50}\n')

    push_serverchan_status('晨间快照', '开始', f'{date_str} 数据采集中')

    # Step 1: 数据采集
    print('Step 1: 采集数据...')
    crypto = collect_crypto()
    ashare = collect_ashare()
    ai_robo = collect_ai_robotics()
    macro = collect_macro()

    # Step 2: 构建结构化 JSON
    print('Step 2: 构建结构化数据...')
    structured = build_structured_data(crypto, ashare, ai_robo, macro)
    print(f'  数据字段: {list(structured.keys())}')

    # Step 3: Claude 生成快照
    print('Step 3: Claude 分析...')
    snapshot = call_claude(structured)

    if snapshot:
        print(f'  快照生成成功: {list(snapshot.keys())}')
    else:
        # fallback: 直接用原始数据
        print('  Claude 分析失败，使用原始数据 fallback')
        snapshot = {
            'crypto_summary': structured['crypto_summary'],
            'ashare_summary': structured['ashare_summary'],
            'ai_robotics_summary': structured['ai_robotics_summary'],
            'today_opportunities': '数据采集完成，AI 分析暂不可用',
            'today_risks': '请手动查看各板块数据',
            'execution_note': 'Claude 分析未生成，仅展示原始数据',
        }

    # Step 4: 渲染 + 推送
    print('Step 4: 推送...')
    rendered = render_snapshot(snapshot, date_str)
    title = f'【晨间快照】{date_str}'

    # Server酱推送（飞书已废弃）
    push_ok = push_serverchan_report(title, rendered)

    # 检查数据完整性
    partial = snapshot.get('execution_note', '') != ''
    if push_ok and not partial:
        push_serverchan_status('晨间快照', '成功', f'{date_str} 已推送')
    elif push_ok and partial:
        push_serverchan_status('晨间快照', '成功', f'{date_str} 已推送（部分数据降级）')
    else:
        push_serverchan_status('晨间快照', '失败', f'{date_str} Server酱推送失败')

    # Step 5: 存档
    print('Step 5: 存档...')
    archive_to_supabase(date_str, snapshot, rendered)

    print(f'\n{"="*50}')
    print(f'  晨间快照完成')
    print(f'{"="*50}\n')


if __name__ == '__main__':
    main()
