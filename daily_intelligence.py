#!/usr/bin/env python3
"""
每日市场情报系统 v1.2 — Daily Market Intelligence
数据采集 + 模板化简报 + Server酱推送
每日08:00 BJT 自动运行（GitHub Actions cron: '0 0 * * *' UTC）
覆盖: 全球宏观 | 加密货币 | A股市场
推送: Server酱(微信) + Supabase存档
深度分析: 在Claude Code session中按需进行（无额外API费用）

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
SERVERCHAN_KEY = os.environ.get('SERVERCHAN_KEY') or 'SCT314848TkLunKgpZEAAbT1YPYUIHrI4F'
SUPABASE_URL = os.environ.get('SUPABASE_URL') or 'https://dmdicqhkjefxethauypp.supabase.co'
SUPABASE_KEY = os.environ.get('SUPABASE_KEY') or \
    'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImRtZGljcWhramVmeGV0aGF1eXBwIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc2OTgxMTMyMiwiZXhwIjoyMDg1Mzg3MzIyfQ.hAbf2cC97-iLsmplti_S1HjnKS0h7nbs9plmkKqlMsc'

BJT = timezone(timedelta(hours=8))
UA = {'User-Agent': 'DailyIntelligence/1.2 (+https://chaoshpc.com)'}
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
# 模板化简报生成（无需LLM API）
# ============================================================
def _fmt_price(val, prefix='', suffix='', decimals=0):
    if val is None:
        return '—'
    if decimals == 0:
        return f'{prefix}{val:,.0f}{suffix}'
    return f'{prefix}{val:,.{decimals}f}{suffix}'


def _fmt_change(val):
    if val is None:
        return '—'
    arrow = '▲' if val > 0 else ('▼' if val < 0 else '—')
    return f'{arrow} {val:+.2f}%'


def build_report(crypto, macro, ashare, news, calendar):
    """用模板把采集到的数据组装成可读简报（markdown）"""
    now = datetime.now(BJT)
    L = []  # lines

    L.append(f'# 每日市场数据简报')
    L.append(f'**{now.strftime("%Y-%m-%d")} 08:00 BJT**')
    L.append('')
    L.append('> 数据自动采集，深度分析请在Claude Code session中进行')
    L.append('')
    L.append('---')

    # ===== 市场快照 =====
    L.append('')
    L.append('## 市场快照')
    L.append('')
    L.append('| 资产 | 价格 | 24h变动 |')
    L.append('|:-----|-----:|-------:|')

    if crypto.get('BTC_price'):
        L.append(f'| BTC | ${crypto["BTC_price"]:,.0f} | {_fmt_change(crypto.get("BTC_change"))} |')
    if crypto.get('ETH_price'):
        L.append(f'| ETH | ${crypto["ETH_price"]:,.0f} | {_fmt_change(crypto.get("ETH_change"))} |')
    if ashare.get('csi300_price'):
        L.append(f'| 沪深300 | {ashare["csi300_price"]:,.2f} | {_fmt_change(ashare.get("csi300_change"))} |')
    if macro.get('usdcny_price'):
        L.append(f'| USD/CNY | {macro["usdcny_price"]:.4f} | {_fmt_change(macro.get("usdcny_change"))} |')
    if macro.get('dxy_price'):
        L.append(f'| DXY | {macro["dxy_price"]:.2f} | {_fmt_change(macro.get("dxy_change"))} |')
    if macro.get('us10y_price'):
        L.append(f'| 10Y美债 | {macro["us10y_price"]:.2f}% | {_fmt_change(macro.get("us10y_change"))} |')
    if macro.get('gold_price'):
        L.append(f'| 黄金 | ${macro["gold_price"]:,.2f} | {_fmt_change(macro.get("gold_change"))} |')

    # ===== 加密货币详情 =====
    L.append('')
    L.append('---')
    L.append('')
    L.append('## 加密货币')
    L.append('')

    if crypto.get('BTC_price'):
        L.append(f'**BTC** ${crypto["BTC_price"]:,.0f} ({crypto.get("BTC_change",0):+.2f}%) '
                 f'| 24h: ${crypto.get("BTC_low",0):,.0f}~${crypto.get("BTC_high",0):,.0f} '
                 f'| 成交: ${crypto.get("BTC_vol",0)/1e8:.1f}亿')
    if crypto.get('ETH_price'):
        L.append(f'**ETH** ${crypto["ETH_price"]:,.0f} ({crypto.get("ETH_change",0):+.2f}%)')
    L.append('')

    derivs = []
    if crypto.get('BTC_funding') is not None:
        ann = crypto['BTC_funding'] * 3 * 365
        derivs.append(f'资金费率 {crypto["BTC_funding"]:+.4f}% (年化{ann:.0f}%)')
    if crypto.get('BTC_ls_ratio'):
        derivs.append(f'多空比 {crypto["BTC_ls_ratio"]:.2f}:1 ({crypto.get("BTC_ls_signal","")})')
    if crypto.get('BTC_oi'):
        derivs.append(f'OI {crypto["BTC_oi"]:,.0f}张')
    if derivs:
        L.append(f'**衍生品:** {" | ".join(derivs)}')
        L.append('')

    if crypto.get('fng_value'):
        fng = crypto['fng_value']
        bar = '█' * (fng // 5) + '░' * (20 - fng // 5)
        L.append(f'**恐贪指数:** {fng}/100 ({crypto["fng_class"]}) `{bar}` 前日:{crypto.get("fng_prev",0)}')
        L.append('')

    chain = []
    if crypto.get('hashrate_ehs'):
        chain.append(f'算力 {crypto["hashrate_ehs"]} EH/s')
    if crypto.get('fee_fast'):
        chain.append(f'手续费 {crypto["fee_fast"]}/{crypto["fee_mid"]}/{crypto["fee_slow"]}')
    if crypto.get('diff_progress'):
        chain.append(f'难度 {crypto["diff_progress"]}% ({crypto.get("diff_est_change",0):+.1f}%)')
    if chain:
        L.append(f'**链上:** {" | ".join(chain)}')
        L.append('')

    # ===== A股 =====
    L.append('---')
    L.append('')
    L.append('## A股市场')
    L.append('')

    for key, label in [('csi300', '沪深300'), ('shcomp', '上证'), ('chinext', '创业板')]:
        if ashare.get(f'{key}_price'):
            L.append(f'**{label}** {ashare[f"{key}_price"]:,.2f} ({ashare.get(f"{key}_change",0):+.2f}%)')
    L.append('')

    if ashare.get('nb_total') is not None:
        nb = ashare['nb_total'] / 10000
        direction = '净买入' if nb > 0 else '净卖出'
        L.append(f'**北向资金:** {direction} {abs(nb):.2f}亿')
        L.append('')

    # ===== 宏观 =====
    L.append('---')
    L.append('')
    L.append('## 全球宏观')
    L.append('')
    for key, label in [('dxy', 'DXY美元指数'), ('gold', '黄金'), ('us10y', '10Y美债'), ('usdcny', 'USD/CNY')]:
        if macro.get(f'{key}_price'):
            p = macro[f'{key}_price']
            c = macro.get(f'{key}_change', 0)
            if key == 'gold':
                L.append(f'**{label}:** ${p:,.2f} ({c:+.2f}%)')
            elif key == 'us10y':
                L.append(f'**{label}:** {p:.2f}% ({c:+.2f}%)')
            else:
                L.append(f'**{label}:** {p:.2f} ({c:+.2f}%)')
    L.append('')

    # ===== 要闻 =====
    cat_names = {'macro': '全球宏观', 'crypto': '加密货币', 'china': '中国/A股'}
    for cat in ['crypto', 'macro', 'china']:
        items = news.get(cat, [])
        if not items:
            continue
        L.append('---')
        L.append('')
        L.append(f'## {cat_names[cat]}要闻 ({len(items)}条)')
        L.append('')
        for i, n in enumerate(items[:10], 1):
            L.append(f'{i}. **{n["title"]}** ({n["source"]})')
        L.append('')

    # ===== 今日日历 =====
    if calendar:
        L.append('---')
        L.append('')
        L.append('## 今日经济日历')
        L.append('')
        for ev in calendar:
            icon = '🔴' if ev['impact'].lower() == 'high' else '🟡'
            L.append(f'- {ev["time_bjt"]} {icon} [{ev["country"]}] {ev["title"]} '
                    f'(预期:{ev.get("forecast","—")} 前值:{ev.get("previous","—")})')
        L.append('')

    # ===== 底部 =====
    L.append('---')
    L.append('')
    total = sum(len(v) for v in news.values())
    src_ok = len([1 for name, _, _, _ in RSS_SOURCES if any(n['source'] == name for cat in news.values() for n in cat)])
    L.append(f'*{src_ok}个源采集{total}条新闻 · Daily Intelligence v1.2*')
    L.append('')
    L.append('> 需要深度分析？打开「新闻公司-每日市场情报」session，发送"分析今天的市场"')

    return '\n'.join(L)


# ============================================================
# 推送 + 存档
# ============================================================
def push_serverchan(report):
    if not SERVERCHAN_KEY:
        print('  SERVERCHAN_KEY未设置')
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


def archive_supabase(report, news_count):
    """
    CREATE TABLE IF NOT EXISTS daily_intelligence (
        id BIGSERIAL PRIMARY KEY, date DATE NOT NULL,
        report TEXT NOT NULL, news_count INTEGER,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    """
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
    print(f'  每日市场情报 v1.2 — 数据采集+模板简报')
    print(f'  {now.strftime("%Y-%m-%d %H:%M:%S")} BJT')
    print(f'{"="*60}')

    print('\n[1/5] 加密货币...')
    crypto = collect_crypto_data()

    print('\n[2/5] 传统市场...')
    macro = collect_macro_data()

    print('\n[3/5] A股...')
    ashare = collect_ashare_data()

    print('\n[4/5] 新闻...')
    news = collect_all_news()
    total = sum(len(v) for v in news.values())
    print(f'  合计: {total}条')

    print('\n[5/5] 经济日历...')
    calendar = collect_calendar()

    print('\n生成简报 + 推送...')
    report = build_report(crypto, macro, ashare, news, calendar)
    print(f'  简报: {len(report)}字')

    sc_ok = push_serverchan(report)
    sb_ok = archive_supabase(report, total)

    print(f'\n{"="*60}')
    print(f'  完成 | Server酱:{"OK" if sc_ok else "FAIL"} | Supabase:{"OK" if sb_ok else "FAIL"} | {total}条新闻')
    print(f'{"="*60}\n')

    if not sc_ok:
        sys.exit(1)


if __name__ == '__main__':
    main()
