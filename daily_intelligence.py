#!/usr/bin/env python3
"""
每日市场情报系统 v2.0 — Daily Market Intelligence
首席分析师（Chief Analyst）· Claude Sonnet 深度分析
每日08:00 BJT 自动运行（GitHub Actions cron: '0 0 * * *' UTC）
覆盖: 全球宏观 | 加密货币 | A股市场 | 跨市场信号
推送: Server酱(微信) + Supabase存档
LLM: Claude Sonnet (Anthropic API)

替代旧版 news_secretary.py（新闻大秘v3.0）
"""
import sys
import os
import io
import json
import time
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from urllib.parse import quote as url_quote

# Windows UTF-8 兼容
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
UA = {'User-Agent': 'DailyIntelligence/2.0 (+https://chaoshpc.com)'}
MAX_AGE_HOURS = 48


# ============================================================
# 通用HTTP工具
# ============================================================
def _http_get_json(url, headers=None, timeout=12):
    hdrs = dict(UA)
    if headers:
        hdrs.update(headers)
    req = Request(url, headers=hdrs)
    return json.loads(urlopen(req, timeout=timeout).read().decode())


def _parse_pub_date(date_str):
    if not date_str or not date_str.strip():
        return None
    date_str = date_str.strip()
    try:
        return parsedate_to_datetime(date_str)
    except Exception:
        pass
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except Exception:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except Exception:
            pass
    return None


# ============================================================
# 数据采集：加密货币（OKX + mempool + Fear&Greed）
# ============================================================
def collect_crypto_data():
    data = {}
    for inst, key in [('BTC-USDT', 'BTC'), ('ETH-USDT', 'ETH')]:
        try:
            d = _http_get_json(f'https://www.okx.com/api/v5/market/ticker?instId={inst}')['data'][0]
            price = float(d['last'])
            open24 = float(d['open24h'])
            change = (price - open24) / open24 * 100 if open24 else 0
            data[f'{key}_price'] = price
            data[f'{key}_change'] = round(change, 2)
            data[f'{key}_high'] = float(d['high24h'])
            data[f'{key}_low'] = float(d['low24h'])
            data[f'{key}_vol'] = float(d.get('volCcy24h', 0))
            print(f'  {key}: ${price:,.0f} ({change:+.2f}%)')
        except Exception as e:
            print(f'  [OKX {key}] {e}')

    for inst, key in [('BTC-USDT-SWAP', 'BTC'), ('ETH-USDT-SWAP', 'ETH')]:
        try:
            d = _http_get_json(f'https://www.okx.com/api/v5/public/funding-rate?instId={inst}')['data'][0]
            rate = float(d['fundingRate']) * 100
            data[f'{key}_funding'] = round(rate, 4)
        except Exception as e:
            print(f'  [OKX {key} funding] {e}')

    for inst, key in [('BTC-USDT-SWAP', 'BTC'), ('ETH-USDT-SWAP', 'ETH')]:
        try:
            d = _http_get_json(f'https://www.okx.com/api/v5/public/open-interest?instType=SWAP&instId={inst}')['data'][0]
            data[f'{key}_oi'] = float(d.get('oi', 0))
        except Exception as e:
            print(f'  [OKX {key} OI] {e}')

    try:
        d = _http_get_json('https://www.okx.com/api/v5/rubik/stat/contracts/long-short-account-ratio?ccy=BTC&period=1D')
        if d.get('data'):
            ratio = float(d['data'][0][1])
            data['BTC_ls_ratio'] = ratio
            data['BTC_ls_signal'] = '多头拥挤' if ratio > 2 else ('空头拥挤' if ratio < 0.8 else '均衡')
    except Exception as e:
        print(f'  [OKX L/S] {e}')

    try:
        d = _http_get_json('https://api.alternative.me/fng/?limit=2')
        if d.get('data'):
            cur = d['data'][0]
            prev = d['data'][1] if len(d['data']) > 1 else {}
            val = int(cur['value'])
            cls_map = {"Extreme Fear": "极度恐惧", "Fear": "恐惧", "Neutral": "中性",
                       "Greed": "贪婪", "Extreme Greed": "极度贪婪"}
            data['fng_value'] = val
            data['fng_class'] = cls_map.get(cur['value_classification'], cur['value_classification'])
            data['fng_prev'] = int(prev.get('value', 0))
    except Exception as e:
        print(f'  [FNG] {e}')

    try:
        d = _http_get_json('https://mempool.space/api/v1/fees/recommended')
        data['fee_fast'] = d.get('fastestFee', 0)
        data['fee_mid'] = d.get('halfHourFee', 0)
        data['fee_slow'] = d.get('hourFee', 0)
    except Exception as e:
        print(f'  [Mempool fee] {e}')
    try:
        d = _http_get_json('https://mempool.space/api/v1/difficulty-adjustment')
        data['diff_progress'] = round(d.get('progressPercent', 0), 1)
        data['diff_est_change'] = round(d.get('difficultyChange', 0), 2)
    except Exception as e:
        print(f'  [Mempool diff] {e}')
    try:
        d = _http_get_json('https://mempool.space/api/v1/mining/hashrate/1w')
        if d.get('currentHashrate'):
            data['hashrate_ehs'] = round(d['currentHashrate'] / 1e18, 1)
    except Exception as e:
        print(f'  [Mempool hashrate] {e}')

    return data


# ============================================================
# 数据采集：传统市场（Yahoo Finance）
# ============================================================
def _yahoo_quote(symbol, label):
    try:
        url = f'https://query1.finance.yahoo.com/v8/finance/chart/{url_quote(symbol, safe="")}?range=5d&interval=1d'
        d = _http_get_json(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }, timeout=10)
        meta = d['chart']['result'][0]['meta']
        price = meta.get('regularMarketPrice', 0)
        prev = meta.get('chartPreviousClose', meta.get('previousClose', 0))
        change = ((price - prev) / prev * 100) if prev else 0
        print(f'  {label}: {price:.2f} ({change:+.2f}%)')
        return {'price': round(price, 4), 'change': round(change, 2)}
    except Exception as e:
        print(f'  [Yahoo {label}] {e}')
        return None


def collect_macro_data():
    data = {}
    for key, symbol, label in [
        ('dxy', 'DX-Y.NYB', 'DXY美元指数'),
        ('gold', 'GC=F', '黄金'),
        ('us10y', '^TNX', '10Y美债'),
        ('usdcny', 'CNY=X', 'USD/CNY'),
    ]:
        r = _yahoo_quote(symbol, label)
        if r:
            data[f'{key}_price'] = r['price']
            data[f'{key}_change'] = r['change']
    return data


# ============================================================
# 数据采集：A股市场（东方财富）
# ============================================================
def _eastmoney_index(secid, label):
    try:
        url = f'https://push2.eastmoney.com/api/qt/stock/get?secid={secid}&fields=f43,f44,f45,f46,f170,f48'
        d = _http_get_json(url)
        info = d.get('data')
        if not info or info.get('f43') is None:
            print(f'  [{label}] 无数据（非交易时段）')
            return None
        price = info['f43'] / 100 if isinstance(info['f43'], int) else info['f43']
        change = info.get('f170', 0)
        change = change / 100 if isinstance(change, int) else change
        turnover = info.get('f48', 0)
        print(f'  {label}: {price:.2f} ({change:+.2f}%)')
        return {'price': price, 'change': change, 'turnover': turnover}
    except Exception as e:
        print(f'  [东方财富 {label}] {e}')
        return None


def collect_ashare_data():
    data = {}
    for key, secid, label in [
        ('csi300', '1.000300', '沪深300'),
        ('shcomp', '1.000001', '上证综指'),
        ('chinext', '0.399006', '创业板指'),
    ]:
        r = _eastmoney_index(secid, label)
        if r:
            data[f'{key}_price'] = r['price']
            data[f'{key}_change'] = r['change']
            if r.get('turnover'):
                data[f'{key}_turnover'] = r['turnover']

    try:
        url = 'https://push2.eastmoney.com/api/qt/kamt.rtmin/get?fields1=f1,f2,f3,f4&fields2=f51,f52,f53,f54,f55,f56'
        d = _http_get_json(url)
        s2n = d.get('data', {}).get('s2n', [])
        if s2n and isinstance(s2n, list):
            for item in reversed(s2n):
                if isinstance(item, str) and ',' in item:
                    fields = item.split(',')
                    if len(fields) >= 4 and fields[3] != '-':
                        try:
                            data['nb_total'] = float(fields[3])
                            data['nb_hgt'] = float(fields[1]) if fields[1] != '-' else 0
                            data['nb_sgt'] = float(fields[2]) if fields[2] != '-' else 0
                            print(f'  北向资金: {data["nb_total"]/10000:.2f}亿')
                        except ValueError:
                            pass
                        break
    except Exception as e:
        print(f'  [北向资金] {e}')

    return data


# ============================================================
# 数据采集：经济日历（Forex Factory）
# ============================================================
def collect_calendar():
    events = []
    try:
        all_ev = _http_get_json('https://nfs.faireconomy.media/ff_calendar_thisweek.json')
        now = datetime.now(BJT)
        today = now.strftime('%Y-%m-%d')
        for ev in all_ev:
            date_str = ev.get('date', '')
            if not date_str.startswith(today):
                continue
            impact = ev.get('impact', '').lower()
            if impact not in ('high', 'medium'):
                continue
            try:
                dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                bjt_str = dt.astimezone(BJT).strftime('%H:%M')
            except Exception:
                bjt_str = '待定'
            events.append({
                'time_bjt': bjt_str, 'country': ev.get('country', ''),
                'title': ev.get('title', ''), 'impact': ev.get('impact', ''),
                'forecast': ev.get('forecast', ''), 'previous': ev.get('previous', ''),
            })
        print(f'  今日事件: {len(events)}个')
    except Exception as e:
        print(f'  [经济日历] {e}')
    return events


# ============================================================
# 新闻采集
# ============================================================
RSS_SOURCES = [
    ('Reuters', 'https://news.google.com/rss/search?q=site:reuters.com+economy+OR+federal+reserve+OR+markets&hl=en-US&gl=US&ceid=US:en', 'macro', 10),
    ('Bloomberg', 'https://news.google.com/rss/search?q=site:bloomberg.com+economy+OR+markets+OR+fed+OR+treasury&hl=en-US&gl=US&ceid=US:en', 'macro', 8),
    ('WSJ', 'https://news.google.com/rss/search?q=site:wsj.com+economy+OR+markets+OR+federal+reserve&hl=en-US&gl=US&ceid=US:en', 'macro', 8),
    ('FT', 'https://news.google.com/rss/search?q=site:ft.com+economy+OR+markets+OR+central+bank&hl=en-US&gl=US&ceid=US:en', 'macro', 8),
    ('GNews Macro', 'https://news.google.com/rss/search?q=federal+reserve+OR+CPI+OR+tariff+OR+interest+rate+OR+inflation&hl=en-US&gl=US&ceid=US:en', 'macro', 10),
    ('CoinDesk', 'https://www.coindesk.com/arc/outboundfeeds/rss/', 'crypto', 10),
    ('CoinTelegraph', 'https://cointelegraph.com/rss', 'crypto', 10),
    ('The Block', 'https://www.theblock.co/rss.xml', 'crypto', 8),
    ('Bitcoin Magazine', 'https://bitcoinmagazine.com/feed', 'crypto', 6),
    ('Decrypt', 'https://decrypt.co/feed', 'crypto', 6),
    ('DL News', 'https://www.dlnews.com/arc/outboundfeeds/rss/', 'crypto', 6),
    ('GNews Crypto', 'https://news.google.com/rss/search?q=bitcoin+OR+ethereum+OR+crypto+regulation+OR+BTC+ETF&hl=en-US&gl=US&ceid=US:en', 'crypto', 10),
    ('金色财经', 'https://www.jinse.cn/rss', 'crypto', 8),
    ('PANews', 'https://www.panewslab.com/rss/index.html', 'crypto', 6),
    ('律动BlockBeats', 'https://www.theblockbeats.info/rss', 'crypto', 6),
    ('36氪', 'https://36kr.com/feed', 'china', 8),
    ('GNews China', 'https://news.google.com/rss/search?q=China+economy+OR+PBOC+OR+yuan+OR+A-shares+OR+stimulus&hl=en-US&gl=US&ceid=US:en', 'china', 8),
]


def fetch_rss(name, url, max_items=8):
    news = []
    now_utc = datetime.now(timezone.utc)
    try:
        raw = urlopen(Request(url, headers=UA), timeout=10).read()
        root = ET.fromstring(raw)
        items = root.findall('.//item')
        is_atom = not items
        if is_atom:
            ns = {'atom': 'http://www.w3.org/2005/Atom'}
            items = root.findall('.//atom:entry', ns)
        dc_ns = {'dc': 'http://purl.org/dc/elements/1.1/'}
        atom_ns = {'atom': 'http://www.w3.org/2005/Atom'}
        for item in items[:max_items * 3]:
            if is_atom:
                title = (item.findtext('atom:title', '', atom_ns) or '').strip()
                link_el = item.find('atom:link', atom_ns)
                link = link_el.get('href', '') if link_el is not None else ''
                pub_str = (item.findtext('atom:published', '', atom_ns) or
                           item.findtext('atom:updated', '', atom_ns) or '').strip()
            else:
                title = (item.findtext('title') or '').strip()
                link = (item.findtext('link') or '').strip()
                pub_str = (item.findtext('pubDate') or
                           item.findtext('dc:date', '', dc_ns) or '').strip()
            if not title:
                continue
            dt = _parse_pub_date(pub_str)
            if dt and (now_utc - dt).total_seconds() > MAX_AGE_HOURS * 3600:
                continue
            desc = ''
            if not is_atom:
                desc = re.sub(r'<[^>]+>', '', (item.findtext('description') or ''))[:200]
            news.append({'title': title[:200], 'link': link[:500], 'source': name, 'desc': desc})
            if len(news) >= max_items:
                break
    except Exception as e:
        print(f'    [{name}] {e}')
    return news


def fetch_cls(max_items=20):
    news = []
    try:
        d = _http_get_json(
            f'https://www.cls.cn/nodeapi/updateTelegraphList?app=CailianpressWeb&os=web&rn={max_items}&sv=8.4.6')
        for item in d.get('data', {}).get('roll_data', []):
            title = (item.get('title') or item.get('content', '')[:100]).strip()
            if not title:
                continue
            news.append({
                'title': title[:200],
                'link': f"https://www.cls.cn/detail/{item.get('id', '')}",
                'source': '财联社', 'desc': item.get('content', '')[:200],
            })
    except Exception as e:
        print(f'    [财联社] {e}')
    return news


def fuzzy_dedup(items, threshold=0.50):
    unique, seen = [], []
    for n in items:
        words = set(re.findall(r'\w{2,}', n['title'].lower()))
        if not words:
            continue
        dup = any(len(words & s) / max(len(words | s), 1) > threshold for s in seen)
        if not dup:
            unique.append(n)
            seen.append(words)
    return unique


def collect_all_news():
    news = {'macro': [], 'crypto': [], 'china': []}
    for name, url, cat, max_n in RSS_SOURCES:
        items = fetch_rss(name, url, max_n)
        for n in items:
            n['category'] = cat
        news[cat].extend(items)
        print(f'    {name}: {len(items)}')
        time.sleep(0.1)
    cls = fetch_cls(20)
    for n in cls:
        n['category'] = 'china'
    news['china'].extend(cls)
    print(f'    财联社: {len(cls)}')
    for cat in news:
        before = len(news[cat])
        news[cat] = fuzzy_dedup(news[cat])
        if before != len(news[cat]):
            print(f'    {cat}: {before}->{len(news[cat])} (去重)')
    return news


# ============================================================
# 数据上下文构建（给Claude分析用）
# ============================================================
def build_data_context(crypto, macro, ashare, news, calendar):
    """把所有采集数据组装成结构化文本，供Claude分析"""
    now = datetime.now(BJT)
    ctx = []
    ctx.append(f'=== 数据采集时间: {now.strftime("%Y-%m-%d %H:%M")} BJT ===\n')

    # 加密货币
    ctx.append('【加密货币市场】')
    if crypto.get('BTC_price'):
        ctx.append(f'BTC: ${crypto["BTC_price"]:,.2f} (24h {crypto.get("BTC_change",0):+.2f}%) '
                   f'高:{crypto.get("BTC_high",0):,.0f} 低:{crypto.get("BTC_low",0):,.0f} '
                   f'成交额:${crypto.get("BTC_vol",0)/1e8:.1f}亿')
    if crypto.get('ETH_price'):
        ctx.append(f'ETH: ${crypto["ETH_price"]:,.2f} (24h {crypto.get("ETH_change",0):+.2f}%)')
    if crypto.get('BTC_funding') is not None:
        ann = crypto['BTC_funding'] * 3 * 365
        ctx.append(f'BTC资金费率: {crypto["BTC_funding"]:+.4f}% (年化{ann:.0f}%)')
    if crypto.get('ETH_funding') is not None:
        ctx.append(f'ETH资金费率: {crypto["ETH_funding"]:+.4f}%')
    if crypto.get('BTC_ls_ratio'):
        ctx.append(f'BTC多空比: {crypto["BTC_ls_ratio"]:.2f}:1 ({crypto.get("BTC_ls_signal","")})')
    if crypto.get('BTC_oi'):
        ctx.append(f'BTC持仓量(OI): {crypto["BTC_oi"]:,.0f}张')
    if crypto.get('fng_value'):
        ctx.append(f'恐贪指数: {crypto["fng_value"]}/100 ({crypto["fng_class"]}) 前日:{crypto.get("fng_prev",0)}')
    chain_info = []
    if crypto.get('hashrate_ehs'):
        chain_info.append(f'算力:{crypto["hashrate_ehs"]}EH/s')
    if crypto.get('fee_fast'):
        chain_info.append(f'手续费:{crypto["fee_fast"]}/{crypto["fee_mid"]}/{crypto["fee_slow"]}sat/vB')
    if crypto.get('diff_progress'):
        chain_info.append(f'难度调整进度:{crypto["diff_progress"]}% 预计变化:{crypto.get("diff_est_change",0):+.1f}%')
    if chain_info:
        ctx.append(f'链上数据: {", ".join(chain_info)}')
    ctx.append('')

    # 传统市场/宏观
    ctx.append('【全球宏观】')
    for key, label in [('dxy', 'DXY美元指数'), ('gold', '黄金(USD)'), ('us10y', '10Y美债收益率(%)'), ('usdcny', 'USD/CNY')]:
        if macro.get(f'{key}_price'):
            ctx.append(f'{label}: {macro[f"{key}_price"]:.4f} ({macro.get(f"{key}_change",0):+.2f}%)')
    ctx.append('')

    # A股
    ctx.append('【A股市场】')
    for key, label in [('csi300', '沪深300'), ('shcomp', '上证综指'), ('chinext', '创业板指')]:
        if ashare.get(f'{key}_price'):
            ctx.append(f'{label}: {ashare[f"{key}_price"]:,.2f} ({ashare.get(f"{key}_change",0):+.2f}%)')
    if ashare.get('nb_total') is not None:
        nb = ashare['nb_total'] / 10000
        ctx.append(f'北向资金: {"净买入" if nb > 0 else "净卖出"} {abs(nb):.2f}亿')
    ctx.append('')

    # 新闻要闻
    cat_names = {'crypto': '加密货币', 'macro': '全球宏观', 'china': '中国/A股'}
    for cat in ['crypto', 'macro', 'china']:
        items = news.get(cat, [])
        if items:
            ctx.append(f'【{cat_names[cat]}要闻】')
            for n in items[:12]:
                ctx.append(f'- {n["title"]} ({n["source"]})')
            ctx.append('')

    # 经济日历
    if calendar:
        ctx.append('【今日经济日历】')
        for ev in calendar:
            ctx.append(f'- {ev["time_bjt"]} [{ev["country"]}] {ev["title"]} '
                       f'(影响:{ev["impact"]}, 预期:{ev.get("forecast","—")}, 前值:{ev.get("previous","—")})')
        ctx.append('')

    return '\n'.join(ctx)


# ============================================================
# Claude Sonnet 首席分析师
# ============================================================
ANALYST_SYSTEM_PROMPT = """你是国兴超链集团的首席分析师（Chief Analyst），每日为董事长产出机构级市场情报简报。

你的分析风格融合了：
- Ray Dalio的系统性宏观框架（流动性驱动一切）
- Arthur Hayes的加密宏观叙事（美元流动性→风险资产传导）
- Howard Marks的风险感知（先说什么可能出错）
- 李迅雷的中国洞察（政策信号解读）

输出规则：
1. 结论先行：每个板块第一句话就是判断
2. 量化有据：不说"涨了"，说"BTC涨3.2%至$67,400，突破20日均线"
3. 跨市场连接：通过流动性/美元/风险偏好传导链串联三个市场
4. 显式置信度：每个观点标注"高/中/低"置信度
5. 风险优先：先说什么可能出错，再说看好什么
6. 信号vs噪音：告诉董事长什么重要，过滤掉噪音
7. 可操作：每份简报必须回答"所以我该怎么做"
8. 用中文输出，专业术语可保留英文"""

ANALYST_USER_PROMPT = """基于以下实时市场数据，产出今日市场情报简报。

{data_context}

请按以下结构输出（markdown格式）：

## 执行摘要
（3句话：①市场定调 ②过去24h最关键事件 ③今日最大风险或机会）

## 市场快照
| 资产 | 价格 | 24h变动 | 信号 |
（包含BTC/ETH/沪深300/USD-CNY/DXY/10Y美债/黄金）

## 加密货币深度
（价格走势研判 + 衍生品信号解读 + 恐贪指数含义 + 链上数据 + 关键支撑/阻力位）

## A股市场
（指数走势 + 北向资金信号 + 政策风向判断）

## 全球宏观
（美元方向 + 利率环境 + 流动性判断 + 标注Risk-On或Risk-Off）

## 跨市场信号
（三个市场之间是否"打架"？哪些相关性出现异常？历史上类似什么时期？）

## 风险雷达
（列出2-4个风险点，每个标注🔴高/🟡中/🟢低风险等级）

## 可操作观点
（对BTC和A股各给出：方向 + 置信度 + 时间框架 + 关键价位）

## 今日关注
（从经济日历和新闻中筛选出今日最需要关注的2-3件事，标注北京时间）"""


def analyze_with_claude(data_context):
    """调用Claude Sonnet进行深度分析"""
    if not ANTHROPIC_API_KEY:
        print('  ANTHROPIC_API_KEY未设置，跳过分析')
        return None

    payload = {
        'model': ANTHROPIC_MODEL,
        'max_tokens': 4000,
        'system': ANALYST_SYSTEM_PROMPT,
        'messages': [
            {'role': 'user', 'content': ANALYST_USER_PROMPT.format(data_context=data_context)}
        ],
    }
    data = json.dumps(payload).encode('utf-8')
    req = Request('https://api.anthropic.com/v1/messages', data=data, headers={
        'x-api-key': ANTHROPIC_API_KEY,
        'anthropic-version': '2023-06-01',
        'content-type': 'application/json',
    })

    try:
        resp = json.loads(urlopen(req, timeout=120).read().decode())
        if resp.get('content'):
            analysis = resp['content'][0]['text']
            tokens_in = resp.get('usage', {}).get('input_tokens', 0)
            tokens_out = resp.get('usage', {}).get('output_tokens', 0)
            print(f'  Claude分析完成 (in:{tokens_in} out:{tokens_out} tokens)')
            return analysis
        else:
            print(f'  [Claude] 无内容返回: {resp}')
            return None
    except Exception as e:
        print(f'  [Claude] {e}')
        if hasattr(e, 'read'):
            print(f'  Response: {e.read().decode()[:300]}')
        return None


# ============================================================
# 简报组装（分析 + 原始数据 fallback）
# ============================================================
def build_fallback_data_section(crypto, macro, ashare, news, calendar):
    """当Claude分析失败时的纯数据fallback"""
    L = []
    L.append('> ⚠️ Claude分析暂不可用，以下为原始数据')
    L.append('')

    L.append('## 市场快照')
    L.append('| 资产 | 价格 | 24h变动 |')
    L.append('|:-----|-----:|-------:|')
    if crypto.get('BTC_price'):
        c = crypto.get('BTC_change', 0)
        L.append(f'| BTC | ${crypto["BTC_price"]:,.0f} | {c:+.2f}% |')
    if crypto.get('ETH_price'):
        c = crypto.get('ETH_change', 0)
        L.append(f'| ETH | ${crypto["ETH_price"]:,.0f} | {c:+.2f}% |')
    if ashare.get('csi300_price'):
        c = ashare.get('csi300_change', 0)
        L.append(f'| 沪深300 | {ashare["csi300_price"]:,.2f} | {c:+.2f}% |')
    if macro.get('dxy_price'):
        c = macro.get('dxy_change', 0)
        L.append(f'| DXY | {macro["dxy_price"]:.2f} | {c:+.2f}% |')
    if macro.get('gold_price'):
        c = macro.get('gold_change', 0)
        L.append(f'| 黄金 | ${macro["gold_price"]:,.2f} | {c:+.2f}% |')
    L.append('')

    cat_names = {'crypto': '加密货币', 'macro': '全球宏观', 'china': '中国/A股'}
    for cat in ['crypto', 'macro', 'china']:
        items = news.get(cat, [])
        if items:
            L.append(f'## {cat_names[cat]}要闻')
            for i, n in enumerate(items[:8], 1):
                L.append(f'{i}. {n["title"]} ({n["source"]})')
            L.append('')

    return '\n'.join(L)


def build_final_report(analysis, crypto, macro, ashare, news, calendar):
    """组装最终推送的简报"""
    now = datetime.now(BJT)
    total = sum(len(v) for v in news.values())
    src_ok = len([1 for name, _, _, _ in RSS_SOURCES if any(n['source'] == name for cat in news.values() for n in cat)])

    header = f'# 每日市场情报\n**{now.strftime("%Y-%m-%d")} · 首席分析师简报**\n'

    if analysis:
        body = analysis
    else:
        body = build_fallback_data_section(crypto, macro, ashare, news, calendar)

    footer = f'\n---\n*{src_ok}源/{total}条新闻 · Claude Sonnet分析 · Daily Intelligence v2.0*'

    # 新闻公司项目状态汇总（董事长每日可见）
    project_status = '''

---
## 新闻公司项目状态
| 项目 | 状态 | 说明 |
|------|------|------|
| 每日市场情报 v2.0 | 运行中 | 本条即是，每日08:00自动推送 |
| IEEE ICTA 2026 Keynote | 已交付 | 28页PPT+演讲稿，待董事长确认 |
'''

    return header + '\n' + body + footer + project_status


# ============================================================
# 推送 + 存档
# ============================================================
def push_serverchan(report):
    if not SERVERCHAN_KEY:
        print('  SERVERCHAN_KEY未设置')
        return False
    try:
        now = datetime.now(BJT)
        title = f'【首席分析师】每日市场情报 {now.strftime("%m-%d")}'
        data = json.dumps({'title': title, 'desp': report}).encode('utf-8')
        req = Request(f'https://sctapi.ftqq.com/{SERVERCHAN_KEY}.send',
                      data=data, headers={'Content-Type': 'application/json; charset=utf-8'})
        resp = json.loads(urlopen(req, timeout=30).read())
        ok = resp.get('code') == 0
        print(f'  Server酱: {"OK" if ok else f"FAIL {resp}"}')
        return ok
    except Exception as e:
        print(f'  [Server酱] {e}')
        return False


def archive_supabase(report, news_count):
    if not SUPABASE_KEY:
        return False
    try:
        now = datetime.now(BJT)
        row = {'date': now.strftime('%Y-%m-%d'), 'report': report[:50000], 'news_count': news_count}
        data = json.dumps(row).encode()
        req = Request(f'{SUPABASE_URL}/rest/v1/daily_intelligence', data=data, headers={
            'apikey': SUPABASE_KEY, 'Authorization': f'Bearer {SUPABASE_KEY}',
            'Content-Type': 'application/json', 'Prefer': 'return=minimal',
        }, method='POST')
        urlopen(req, timeout=15)
        print(f'  Supabase: OK')
        return True
    except Exception as e:
        print(f'  [Supabase] {e}')
        return False


# ============================================================
# 主流程
# ============================================================
def main():
    now = datetime.now(BJT)
    print(f'\n{"="*60}')
    print(f'  每日市场情报 v2.0 — 首席分析师(Claude Sonnet)')
    print(f'  {now.strftime("%Y-%m-%d %H:%M:%S")} BJT')
    print(f'{"="*60}')

    print('\n[1/6] 加密货币...')
    crypto = collect_crypto_data()

    print('\n[2/6] 传统市场...')
    macro = collect_macro_data()

    print('\n[3/6] A股...')
    ashare = collect_ashare_data()

    print('\n[4/6] 新闻...')
    news = collect_all_news()
    total = sum(len(v) for v in news.values())
    print(f'  合计: {total}条')

    print('\n[5/6] 经济日历...')
    calendar = collect_calendar()

    print('\n[6/6] Claude Sonnet 深度分析...')
    data_ctx = build_data_context(crypto, macro, ashare, news, calendar)
    analysis = analyze_with_claude(data_ctx)

    print('\n组装简报 + 推送...')
    report = build_final_report(analysis, crypto, macro, ashare, news, calendar)
    print(f'  简报: {len(report)}字')

    sc_ok = push_serverchan(report)
    sb_ok = archive_supabase(report, total)

    status = 'AI分析' if analysis else '数据fallback'
    print(f'\n{"="*60}')
    print(f'  完成 | {status} | Server酱:{"OK" if sc_ok else "FAIL"} | Supabase:{"OK" if sb_ok else "FAIL"} | {total}条新闻')
    print(f'{"="*60}\n')

    if not sc_ok:
        sys.exit(1)


if __name__ == '__main__':
    main()
