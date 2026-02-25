#!/usr/bin/env python3
"""
每日市场情报系统 v1.1 — Daily Market Intelligence
首席分析师（Chief Analyst）
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
import traceback
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
# 配置（env优先，fallback为CLAUDE.md中的值供本地测试）
# ============================================================
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY') or \
    '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'
ANTHROPIC_MODEL = 'claude-sonnet-4-20250514'

SERVERCHAN_KEY = os.environ.get('SERVERCHAN_KEY') or 'SCT314848TkLunKgpZEAAbT1YPYUIHrI4F'

SUPABASE_URL = os.environ.get('SUPABASE_URL') or 'https://dmdicqhkjefxethauypp.supabase.co'
SUPABASE_KEY = os.environ.get('SUPABASE_KEY') or \
    'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImRtZGljcWhramVmeGV0aGF1eXBwIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc2OTgxMTMyMiwiZXhwIjoyMDg1Mzg3MzIyfQ.hAbf2cC97-iLsmplti_S1HjnKS0h7nbs9plmkKqlMsc'

BJT = timezone(timedelta(hours=8))
UA = {'User-Agent': 'DailyIntelligence/1.1 (+https://chaoshpc.com)'}
MAX_AGE_HOURS = 48


# ============================================================
# 通用HTTP工具
# ============================================================
def _http_get_json(url, headers=None, timeout=12):
    """HTTP GET -> JSON, 带默认UA"""
    hdrs = dict(UA)
    if headers:
        hdrs.update(headers)
    req = Request(url, headers=hdrs)
    resp = urlopen(req, timeout=timeout)
    return json.loads(resp.read().decode())


def _parse_pub_date(date_str):
    """解析RSS/Atom日期字段"""
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
    """采集加密货币全维度数据"""
    data = {}

    # BTC + ETH 价格
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

    # 资金费率
    for inst, key in [('BTC-USDT-SWAP', 'BTC'), ('ETH-USDT-SWAP', 'ETH')]:
        try:
            d = _http_get_json(f'https://www.okx.com/api/v5/public/funding-rate?instId={inst}')['data'][0]
            rate = float(d['fundingRate']) * 100
            data[f'{key}_funding'] = round(rate, 4)
            print(f'  {key} funding: {rate:+.4f}%')
        except Exception as e:
            print(f'  [OKX {key} funding] {e}')

    # 持仓量
    for inst, key in [('BTC-USDT-SWAP', 'BTC'), ('ETH-USDT-SWAP', 'ETH')]:
        try:
            d = _http_get_json(f'https://www.okx.com/api/v5/public/open-interest?instType=SWAP&instId={inst}')['data'][0]
            data[f'{key}_oi'] = float(d.get('oi', 0))
        except Exception as e:
            print(f'  [OKX {key} OI] {e}')

    # 多空比
    try:
        d = _http_get_json('https://www.okx.com/api/v5/rubik/stat/contracts/long-short-account-ratio?ccy=BTC&period=1D')
        if d.get('data'):
            ratio = float(d['data'][0][1])
            data['BTC_ls_ratio'] = ratio
            data['BTC_ls_signal'] = '多头拥挤' if ratio > 2 else ('空头拥挤' if ratio < 0.8 else '均衡')
            print(f'  BTC L/S: {ratio:.2f} ({data["BTC_ls_signal"]})')
    except Exception as e:
        print(f'  [OKX L/S] {e}')

    # 恐贪指数
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
            print(f'  FNG: {val} ({data["fng_class"]}), prev: {data["fng_prev"]}')
    except Exception as e:
        print(f'  [FNG] {e}')

    # mempool: 手续费 + 难度 + 算力
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
            print(f'  Hashrate: {data["hashrate_ehs"]} EH/s')
    except Exception as e:
        print(f'  [Mempool hashrate] {e}')

    return data


# ============================================================
# 数据采集：传统市场（Yahoo Finance — GitHub Actions美国IP可达）
# ============================================================
def _yahoo_quote(symbol, label):
    """Yahoo Finance v8 chart API"""
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
    """DXY, Gold, 10Y Treasury, USD/CNY"""
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
# 数据采集：A股市场（东方财富API — 更可靠）
# ============================================================
def _eastmoney_index(secid, label):
    """东方财富指数数据"""
    try:
        url = f'https://push2.eastmoney.com/api/qt/stock/get?secid={secid}&fields=f43,f44,f45,f46,f170,f48'
        d = _http_get_json(url)
        info = d.get('data')
        if not info or info.get('f43') is None:
            print(f'  [{label}] 无数据（非交易时段）')
            return None
        # 东方财富整数字段需要除以100
        price = info['f43'] / 100 if isinstance(info['f43'], int) else info['f43']
        change = info.get('f170', 0)
        change = change / 100 if isinstance(change, int) else change
        turnover = info.get('f48', 0)  # 成交额(元)
        print(f'  {label}: {price:.2f} ({change:+.2f}%)')
        return {'price': price, 'change': change, 'turnover': turnover}
    except Exception as e:
        print(f'  [东方财富 {label}] {e}')
        return None


def collect_ashare_data():
    """沪深300、上证综指、创业板指、北向资金"""
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

    # 北向资金
    try:
        url = 'https://push2.eastmoney.com/api/qt/kamt.rtmin/get?fields1=f1,f2,f3,f4&fields2=f51,f52,f53,f54,f55,f56'
        d = _http_get_json(url)
        s2n = d.get('data', {}).get('s2n', [])
        if s2n and isinstance(s2n, list):
            # 取最后一个有效数据点
            for item in reversed(s2n):
                if isinstance(item, str) and ',' in item:
                    fields = item.split(',')
                    if len(fields) >= 4 and fields[3] != '-':
                        try:
                            data['nb_total'] = float(fields[3])  # 北向合计(万元)
                            data['nb_hgt'] = float(fields[1]) if fields[1] != '-' else 0
                            data['nb_sgt'] = float(fields[2]) if fields[2] != '-' else 0
                            total_yi = data['nb_total'] / 10000  # 万元→亿元
                            print(f'  北向资金: {total_yi:.2f}亿')
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
    """获取今日高/中影响经济事件"""
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
            # 转北京时间
            try:
                dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                bjt_str = dt.astimezone(BJT).strftime('%H:%M')
            except Exception:
                bjt_str = '待定'
            events.append({
                'time_bjt': bjt_str,
                'country': ev.get('country', ''),
                'title': ev.get('title', ''),
                'impact': ev.get('impact', ''),
                'forecast': ev.get('forecast', ''),
                'previous': ev.get('previous', ''),
            })
        print(f'  今日事件: {len(events)}个 (高/中影响)')
    except Exception as e:
        print(f'  [经济日历] {e}')
    return events


# ============================================================
# 新闻采集
# ============================================================
RSS_SOURCES = [
    # --- 全球宏观 ---
    ('Reuters', 'https://news.google.com/rss/search?q=site:reuters.com+economy+OR+federal+reserve+OR+markets&hl=en-US&gl=US&ceid=US:en', 'macro', 10),
    ('Bloomberg', 'https://news.google.com/rss/search?q=site:bloomberg.com+economy+OR+markets+OR+fed+OR+treasury&hl=en-US&gl=US&ceid=US:en', 'macro', 8),
    ('WSJ', 'https://news.google.com/rss/search?q=site:wsj.com+economy+OR+markets+OR+federal+reserve&hl=en-US&gl=US&ceid=US:en', 'macro', 8),
    ('FT', 'https://news.google.com/rss/search?q=site:ft.com+economy+OR+markets+OR+central+bank&hl=en-US&gl=US&ceid=US:en', 'macro', 8),
    ('GNews Macro', 'https://news.google.com/rss/search?q=federal+reserve+OR+CPI+OR+tariff+OR+interest+rate+OR+inflation&hl=en-US&gl=US&ceid=US:en', 'macro', 10),
    # --- 加密货币 ---
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
    # --- 中国/A股 ---
    ('36氪', 'https://36kr.com/feed', 'china', 8),
    ('GNews China', 'https://news.google.com/rss/search?q=China+economy+OR+PBOC+OR+yuan+OR+A-shares+OR+stimulus&hl=en-US&gl=US&ceid=US:en', 'china', 8),
]


def fetch_rss(name, url, max_items=8):
    """通用RSS采集器（RSS 2.0 + Atom，48h日期过滤）"""
    news = []
    now_utc = datetime.now(timezone.utc)
    try:
        req = Request(url, headers=UA)
        raw = urlopen(req, timeout=10).read()
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
    """财联社电报API"""
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
                'source': '财联社',
                'desc': item.get('content', '')[:200],
            })
    except Exception as e:
        print(f'    [财联社] {e}')
    return news


def fuzzy_dedup(items, threshold=0.50):
    """模糊去重"""
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
    """采集全部新闻源，按类别分组去重"""
    news = {'macro': [], 'crypto': [], 'china': []}

    for name, url, cat, max_n in RSS_SOURCES:
        items = fetch_rss(name, url, max_n)
        for n in items:
            n['category'] = cat
        news[cat].extend(items)
        print(f'    {name}: {len(items)}')
        time.sleep(0.1)

    # 财联社
    cls = fetch_cls(20)
    for n in cls:
        n['category'] = 'china'
    news['china'].extend(cls)
    print(f'    财联社: {len(cls)}')

    # 各类别去重
    for cat in news:
        before = len(news[cat])
        news[cat] = fuzzy_dedup(news[cat])
        if before != len(news[cat]):
            print(f'    {cat}: {before}->{len(news[cat])} (去重)')

    return news


# ============================================================
# Claude Sonnet 分析引擎
# ============================================================
ANALYST_SYSTEM_PROMPT = """你是国兴超链集团的首席分析师（Chief Analyst），产出机构级每日市场情报简报。

## 分析风格（融合顶级分析师特质）
- Ray Dalio（Bridgewater）：系统性宏观框架，"经济机器"思维
- Arthur Hayes（Maelstrom）：传统宏观→加密价格传导链，美元流动性→BTC映射
- 李迅雷（中泰证券）：中国宏观洞察，结构性问题坦诚分析
- Howard Marks（Oaktree）：市场周期判断，风险优先思维
- Mary Meeker（Bond Capital）：海量数据提炼趋势

## 读者背景
董事长（陈超）——同时关注BTC ASIC服务器运营（26个F2Pool子账户）、GPU算力销售（chaoshpc.com）、A股量化策略、OKX套利。每天只看这一份简报。

## 核心原则
1. 结论先行 — 每个板块第一句话就是判断
2. 量化有据 — "BTC涨3.2%至$67,400"而非"BTC涨了"
3. 跨市场连接 — 通过流动性/美元/风险偏好传导链串联
4. 显式置信度 — 每个观点标注高/中/低+时间框架
5. 历史类比 — 锚定当前形势
6. 风险优先 — 先说可能出错的
7. 信号vs噪音 — 只说重要的
8. 可操作性 — 回答"所以我该怎么做"

## 输出格式（严格按以下markdown结构，直接输出内容，不要加```标记）

# 每日市场情报简报
**{日期} 08:00 BJT | 回顾过去24小时**

---

## 执行摘要

> **[Risk-On / Risk-Off / 转换中]**
> [过去24h最关键事件，一句话]
> [今日首要风险或机会，一句话]

---

## 市场快照

| 资产 | 价格 | 24h变动 | 信号 |
|:-----|-----:|-------:|:-----|
| BTC/USD | | | |
| ETH/USD | | | |
| 沪深300 | | | |
| USD/CNY | | | |
| DXY | | | |
| 10Y美债 | | | |
| 黄金 | | | |

---

## 全球宏观研判

[2-3段：流动性环境+央行动态+美元方向]

**定调：** Risk-On/Off | **置信度：** 高/中/低 | **时间框架：** X周

---

## 加密市场分析

**链上：** [算力、手续费、难度调整、交易所流向]
**衍生品：** [资金费率、持仓量变化、多空比、清算水位]
**情绪：** Fear & Greed X/100 ([分类])
**关键价位：** 支撑 $XX,XXX | 阻力 $XX,XXX

[1-2段综合分析+对矿场和持仓的建议]

**判断：** 看多/看空/中性 — [推理] | **置信度：** 高/中/低

---

## A股市场分析

**北向资金：** [金额方向趋势]
**行业轮动：** [领涨/领跌板块]
**政策风向：** [PBOC/证监会动态]

[1段分析]

**判断：** 看多/看空/中性 — [推理] | **置信度：** 高/中/低

---

## 跨市场信号

[哪些市场在"打架"？传导机制？历史类比？]

---

## 风险雷达

- **高风险：** [立即关注]
- **中风险：** [持续监控]
- **低风险：** [背景风险]

---

## 可操作观点

1. **[资产]** | [方向] | [时间框架] | 置信度[高/中/低] | [关键价位]
2. **[资产]** | [方向] | [时间框架] | 置信度[高/中/低] | [关键价位]
3. **[资产]** | [方向] | [时间框架] | 置信度[高/中/低] | [关键价位]

---

## 今日日历（北京时间）

[关键数据发布、央行讲话、财报]

---
*首席分析师 · 国兴超链集团 · Daily Intelligence v1.1*

## 规则
- 市场数据直接使用输入数据，不编造
- 缺失数据标注"数据暂缺"
- 今日日历如无数据则根据新闻推断
- 用中文，专业术语保留英文缩写"""


def build_data_context(crypto, macro, ashare, news, calendar):
    """组装所有数据为Claude输入上下文"""
    now = datetime.now(BJT)
    parts = [f'=== 数据采集时间: {now.strftime("%Y-%m-%d %H:%M")} BJT ===\n']

    # 加密货币
    parts.append('【加密货币 - OKX/mempool/alternative.me】')
    if crypto.get('BTC_price'):
        parts.append(f'  BTC: ${crypto["BTC_price"]:,.2f} ({crypto.get("BTC_change",0):+.2f}%) '
                     f'24h高低: ${crypto.get("BTC_high",0):,.0f}/${crypto.get("BTC_low",0):,.0f} '
                     f'成交: ${crypto.get("BTC_vol",0)/1e8:.1f}亿')
    if crypto.get('ETH_price'):
        parts.append(f'  ETH: ${crypto["ETH_price"]:,.2f} ({crypto.get("ETH_change",0):+.2f}%)')
    if crypto.get('BTC_funding') is not None:
        ann = crypto['BTC_funding'] * 3 * 365
        parts.append(f'  BTC永续资金费率: {crypto["BTC_funding"]:+.4f}% (年化{ann:.1f}%)')
    if crypto.get('ETH_funding') is not None:
        parts.append(f'  ETH永续资金费率: {crypto["ETH_funding"]:+.4f}%')
    if crypto.get('BTC_oi'):
        parts.append(f'  BTC合约持仓: {crypto["BTC_oi"]:,.0f}张')
    if crypto.get('BTC_ls_ratio'):
        parts.append(f'  BTC多空比: {crypto["BTC_ls_ratio"]:.2f}:1 ({crypto.get("BTC_ls_signal","")})')
    if crypto.get('fng_value'):
        parts.append(f'  恐贪指数: {crypto["fng_value"]}/100 ({crypto["fng_class"]}), 前日: {crypto.get("fng_prev",0)}')
    if crypto.get('fee_fast'):
        parts.append(f'  BTC手续费: {crypto["fee_fast"]}/{crypto["fee_mid"]}/{crypto["fee_slow"]} sat/vB (快/中/慢)')
    if crypto.get('diff_progress'):
        parts.append(f'  难度调整: 进度{crypto["diff_progress"]}%, 预计变化{crypto.get("diff_est_change",0):+.2f}%')
    if crypto.get('hashrate_ehs'):
        parts.append(f'  全网算力: {crypto["hashrate_ehs"]} EH/s')

    # 传统市场
    parts.append('\n【传统市场 - Yahoo Finance】')
    labels = [('dxy', 'DXY美元指数'), ('gold', '黄金(COMEX)'), ('us10y', '10Y美债收益率'), ('usdcny', 'USD/CNY')]
    for key, label in labels:
        if macro.get(f'{key}_price'):
            parts.append(f'  {label}: {macro[f"{key}_price"]} ({macro.get(f"{key}_change",0):+.2f}%)')
        else:
            parts.append(f'  {label}: 数据暂缺')

    # A股
    parts.append('\n【A股 - 东方财富】')
    for key, label in [('csi300', '沪深300'), ('shcomp', '上证综指'), ('chinext', '创业板指')]:
        if ashare.get(f'{key}_price'):
            parts.append(f'  {label}: {ashare[f"{key}_price"]:.2f} ({ashare.get(f"{key}_change",0):+.2f}%)')
        else:
            parts.append(f'  {label}: 数据暂缺（非交易时段）')
    if ashare.get('nb_total') is not None:
        nb = ashare['nb_total'] / 10000  # 万→亿
        direction = '净买入' if nb > 0 else '净卖出'
        parts.append(f'  北向资金: {direction}{abs(nb):.2f}亿')
    else:
        parts.append(f'  北向资金: 数据暂缺')

    # 新闻
    cat_names = {'macro': '全球宏观', 'crypto': '加密货币', 'china': '中国/A股'}
    for cat in ['macro', 'crypto', 'china']:
        items = news.get(cat, [])
        if items:
            parts.append(f'\n【新闻: {cat_names[cat]} ({len(items)}条)】')
            for i, n in enumerate(items[:20], 1):
                line = f'  {i}. [{n["source"]}] {n["title"]}'
                if n.get('desc'):
                    line += f' — {n["desc"][:150]}'
                parts.append(line)

    # 经济日历
    if calendar:
        parts.append(f'\n【今日经济日历 ({len(calendar)}个事件)】')
        for ev in calendar:
            icon = '!!!' if ev['impact'].lower() == 'high' else '!!'
            parts.append(f'  {ev["time_bjt"]} BJT {icon} [{ev["country"]}] {ev["title"]} '
                        f'(预期: {ev.get("forecast","N/A")}, 前值: {ev.get("previous","N/A")})')
    else:
        parts.append('\n【今日经济日历】\n  未获取到数据，请根据新闻推断')

    return '\n'.join(parts)


def call_claude(data_context):
    """调用Claude Sonnet生成情报简报"""
    if not ANTHROPIC_API_KEY:
        print('  [ERROR] ANTHROPIC_API_KEY未设置')
        return None

    now = datetime.now(BJT)
    user_msg = f'今天是{now.strftime("%Y-%m-%d")}。请基于以下数据产出今日每日市场情报简报：\n\n{data_context}'

    payload = json.dumps({
        'model': ANTHROPIC_MODEL,
        'system': ANALYST_SYSTEM_PROMPT,
        'messages': [{'role': 'user', 'content': user_msg}],
        'temperature': 0.3,
        'max_tokens': 4096,
    }).encode()

    req = Request('https://api.anthropic.com/v1/messages', data=payload, headers={
        'x-api-key': ANTHROPIC_API_KEY,
        'anthropic-version': '2023-06-01',
        'Content-Type': 'application/json',
    })

    print('  调用Claude Sonnet...')
    start = time.time()
    try:
        resp = json.loads(urlopen(req, timeout=180).read())
        elapsed = time.time() - start
        if resp.get('content'):
            report = resp['content'][0]['text']
            usage = resp.get('usage', {})
            print(f'  完成 ({elapsed:.1f}s, in={usage.get("input_tokens",0)}, out={usage.get("output_tokens",0)})')
            return report
        print(f'  异常响应: {json.dumps(resp, ensure_ascii=False)[:300]}')
        return None
    except HTTPError as e:
        body = e.read().decode()[:500] if hasattr(e, 'read') else ''
        print(f'  HTTP {e.code}: {body}')
        return None
    except Exception as e:
        print(f'  错误: {e}')
        traceback.print_exc()
        return None


# ============================================================
# 推送 + 存档
# ============================================================
def push_serverchan(report):
    """Server酱推送到董事长微信"""
    if not SERVERCHAN_KEY:
        print('  SERVERCHAN_KEY未设置，跳过')
        return False
    try:
        now = datetime.now(BJT)
        title = f'【新闻公司】每日市场情报 {now.strftime("%Y-%m-%d")}'
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


def archive_supabase(report, raw_context, news_count):
    """
    存档到Supabase daily_intelligence表。
    首次运行前需在Supabase SQL Editor执行:
    CREATE TABLE IF NOT EXISTS daily_intelligence (
        id BIGSERIAL PRIMARY KEY,
        date DATE NOT NULL,
        report TEXT NOT NULL,
        raw_data TEXT,
        news_count INTEGER,
        model TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    """
    if not SUPABASE_KEY:
        print('  SUPABASE_KEY未设置，跳过')
        return False
    try:
        now = datetime.now(BJT)
        row = {
            'date': now.strftime('%Y-%m-%d'),
            'report': report[:50000],
            'raw_data': raw_context[:50000],
            'news_count': news_count,
            'model': ANTHROPIC_MODEL,
        }
        data = json.dumps(row).encode()
        req = Request(f'{SUPABASE_URL}/rest/v1/daily_intelligence', data=data, headers={
            'apikey': SUPABASE_KEY,
            'Authorization': f'Bearer {SUPABASE_KEY}',
            'Content-Type': 'application/json',
            'Prefer': 'return=minimal',
        }, method='POST')
        urlopen(req, timeout=15)
        print(f'  Supabase: OK')
        return True
    except HTTPError as e:
        body = e.read().decode()[:300] if hasattr(e, 'read') else ''
        if e.code == 404 or '42P01' in body:
            print(f'  Supabase: 表不存在，请先创建daily_intelligence表（见代码注释SQL）')
        else:
            print(f'  Supabase: HTTP {e.code} {body}')
        return False
    except Exception as e:
        print(f'  [Supabase] {e}')
        return False


# ============================================================
# 主流程
# ============================================================
def main():
    now = datetime.now(BJT)
    print(f'\n{"="*60}')
    print(f'  每日市场情报系统 v1.1 — 首席分析师')
    print(f'  {now.strftime("%Y-%m-%d %H:%M:%S")} BJT | LLM: {ANTHROPIC_MODEL}')
    print(f'{"="*60}')

    # [1] 加密货币
    print('\n[1/6] 加密货币数据...')
    crypto = collect_crypto_data()

    # [2] 传统市场
    print('\n[2/6] 传统市场数据...')
    macro = collect_macro_data()

    # [3] A股
    print('\n[3/6] A股数据...')
    ashare = collect_ashare_data()

    # [4] 新闻
    print('\n[4/6] 新闻采集...')
    news = collect_all_news()
    total = sum(len(v) for v in news.values())
    print(f'  合计: {total}条')

    # [5] 经济日历
    print('\n[5/6] 经济日历...')
    calendar = collect_calendar()

    # [6] Claude分析 + 推送
    print('\n[6/6] Claude分析 + 推送...')
    context = build_data_context(crypto, macro, ashare, news, calendar)
    print(f'  数据上下文: {len(context)}字符')

    report = call_claude(context)
    if not report:
        print('  Claude失败，启用降级简报')
        report = (f'# 每日市场情报（降级模式）\n'
                  f'**{now.strftime("%Y-%m-%d")}** — AI分析引擎暂不可用\n\n'
                  f'---\n\n{context[:3000]}')

    sc_ok = push_serverchan(report)
    sb_ok = archive_supabase(report, context, total)

    print(f'\n{"="*60}')
    print(f'  完成 | Server酱: {"OK" if sc_ok else "FAIL"} | Supabase: {"OK" if sb_ok else "FAIL"}')
    print(f'  新闻{total}条 | 简报{len(report)}字')
    print(f'{"="*60}\n')

    if not sc_ok:
        sys.exit(1)


if __name__ == '__main__':
    main()
