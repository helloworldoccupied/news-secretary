#!/usr/bin/env python3
"""
每日市场情报系统 v3.2 — Daily Market Intelligence
首席分析师（Chief Analyst）· Claude Sonnet 深度分析
每日08:00 BJT 自动运行（GitHub Actions cron: '0 0 * * *' UTC）

v3.2 更新（2026-03-01）：
- 投研级深度分析prompt重写：核心矛盾分析法+因果链推演+历史类比+共识vs反共识
- max_tokens 4000→6000，允许更深度的分析
- 新增BlockBeats(律动)快讯：链上大额转账、项目动态、行业快讯
- 步骤从9步增加到10步

v3.0 重大更新（2026-02-28）：
- 新闻源大换血：砍掉5个Google News通用搜索+36kr，改为精准金融搜索
- 三层新闻过滤：关键词相关性→模糊去重→只保留金融相关
- 新增衍生品数据：Binance跨交易所OI/资金费率/多空比
- 新增DeFi数据：DefiLlama TVL + 稳定币市值
- 新增全局数据：CoinGecko总市值/BTC市占率
- 算力图表：60天折线图(quickchart.io)替代丑陋ASCII柱状图
- 分析prompt重写：按事件分组，不逐条罗列，只分析投资相关
- 移除per-category新闻分析（节省API费用+避免垃圾新闻分析）
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
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0'}
MAX_AGE_HOURS = 48


# ============================================================
# 通用HTTP工具
# ============================================================
def _get(url, headers=None, timeout=12):
    """HTTP GET返回JSON"""
    hdrs = dict(UA)
    if headers:
        hdrs.update(headers)
    req = Request(url, headers=hdrs)
    return json.loads(urlopen(req, timeout=timeout).read().decode())


def _get_safe(url, label='', headers=None, timeout=12):
    """安全GET，失败返回None不抛异常"""
    try:
        return _get(url, headers=headers, timeout=timeout)
    except Exception as e:
        if label:
            print(f'  [{label}] {e}')
        return None


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
            return datetime.strptime(date_str, fmt).replace(tzinfo=timezone.utc)
        except Exception:
            pass
    return None


# ============================================================
# 数据采集：加密货币（OKX + Binance + Fear&Greed + mempool）
# ============================================================
def collect_crypto_data():
    data = {}

    # --- OKX 现货 ---
    for inst, key in [('BTC-USDT', 'BTC'), ('ETH-USDT', 'ETH')]:
        try:
            d = _get(f'https://www.okx.com/api/v5/market/ticker?instId={inst}')['data'][0]
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

    # --- OKX 衍生品 ---
    for inst, key in [('BTC-USDT-SWAP', 'BTC'), ('ETH-USDT-SWAP', 'ETH')]:
        try:
            d = _get(f'https://www.okx.com/api/v5/public/funding-rate?instId={inst}')['data'][0]
            data[f'{key}_okx_funding'] = round(float(d['fundingRate']) * 100, 4)
        except Exception as e:
            print(f'  [OKX {key} funding] {e}')
        try:
            d = _get(f'https://www.okx.com/api/v5/public/open-interest?instType=SWAP&instId={inst}')['data'][0]
            data[f'{key}_okx_oi'] = float(d.get('oi', 0))
        except Exception as e:
            print(f'  [OKX {key} OI] {e}')

    try:
        d = _get('https://www.okx.com/api/v5/rubik/stat/contracts/long-short-account-ratio?ccy=BTC&period=1D')
        if d.get('data'):
            data['BTC_okx_ls'] = float(d['data'][0][1])
    except Exception as e:
        print(f'  [OKX L/S] {e}')

    # --- Binance 衍生品（跨交易所对比）---
    for symbol, key in [('BTCUSDT', 'BTC'), ('ETHUSDT', 'ETH')]:
        try:
            d = _get(f'https://fapi.binance.com/fapi/v1/fundingRate?symbol={symbol}&limit=1')
            if d:
                data[f'{key}_bn_funding'] = round(float(d[0]['fundingRate']) * 100, 4)
        except Exception as e:
            print(f'  [Binance {key} funding] {e}')
        try:
            d = _get(f'https://fapi.binance.com/fapi/v1/openInterest?symbol={symbol}')
            data[f'{key}_bn_oi_usdt'] = float(d.get('openInterest', 0))
        except Exception as e:
            print(f'  [Binance {key} OI] {e}')

    try:
        d = _get('https://fapi.binance.com/futures/data/topLongShortAccountRatio?symbol=BTCUSDT&period=1d&limit=1')
        if d:
            data['BTC_bn_ls'] = round(float(d[0]['longShortRatio']), 2)
    except Exception as e:
        print(f'  [Binance L/S] {e}')

    # --- 恐贪指数（7天趋势）---
    try:
        d = _get('https://api.alternative.me/fng/?limit=7')
        if d.get('data'):
            cur = d['data'][0]
            val = int(cur['value'])
            cls_map = {"Extreme Fear": "极度恐惧", "Fear": "恐惧", "Neutral": "中性",
                       "Greed": "贪婪", "Extreme Greed": "极度贪婪"}
            data['fng_value'] = val
            data['fng_class'] = cls_map.get(cur['value_classification'], cur['value_classification'])
            # 7天趋势
            trend = [int(x['value']) for x in d['data']]
            data['fng_7d'] = trend  # [今天, 昨天, ..., 7天前]
            avg7 = sum(trend) / len(trend)
            data['fng_7d_avg'] = round(avg7, 1)
            data['fng_trend'] = '上升' if val > avg7 + 3 else ('下降' if val < avg7 - 3 else '持平')
    except Exception as e:
        print(f'  [FNG] {e}')

    # --- Mempool（BTC链上）---
    try:
        d = _get('https://mempool.space/api/v1/fees/recommended')
        data['fee_fast'] = d.get('fastestFee', 0)
        data['fee_mid'] = d.get('halfHourFee', 0)
        data['fee_slow'] = d.get('hourFee', 0)
    except Exception as e:
        print(f'  [Mempool fee] {e}')
    try:
        d = _get('https://mempool.space/api/v1/difficulty-adjustment')
        data['diff_progress'] = round(d.get('progressPercent', 0), 1)
        data['diff_est_change'] = round(d.get('difficultyChange', 0), 2)
    except Exception as e:
        print(f'  [Mempool diff] {e}')
    try:
        d = _get('https://mempool.space/api/v1/mining/hashrate/1w')
        if d.get('currentHashrate'):
            data['hashrate_ehs'] = round(d['currentHashrate'] / 1e18, 1)
    except Exception as e:
        print(f'  [Mempool hashrate] {e}')

    # --- CoinGecko 全局数据 ---
    try:
        d = _get('https://api.coingecko.com/api/v3/global')
        gd = d.get('data', {})
        data['total_mcap'] = gd.get('total_market_cap', {}).get('usd', 0)
        data['total_vol'] = gd.get('total_volume', {}).get('usd', 0)
        data['btc_dominance'] = round(gd.get('market_cap_percentage', {}).get('btc', 0), 1)
        data['eth_dominance'] = round(gd.get('market_cap_percentage', {}).get('eth', 0), 1)
        data['mcap_change_24h'] = round(gd.get('market_cap_change_percentage_24h_usd', 0), 2)
        print(f'  CoinGecko: 总市值${data["total_mcap"]/1e12:.2f}T BTC占比{data["btc_dominance"]}%')
    except Exception as e:
        print(f'  [CoinGecko] {e}')

    return data


# ============================================================
# 数据采集：DeFi（DefiLlama）
# ============================================================
def collect_defi_data():
    data = {}
    # 总TVL
    try:
        d = _get('https://api.llama.fi/v2/historicalChainTvl')
        if d and len(d) > 1:
            latest = d[-1]
            prev = d[-2]
            tvl = latest.get('tvl', 0)
            tvl_prev = prev.get('tvl', 0)
            change = (tvl - tvl_prev) / tvl_prev * 100 if tvl_prev else 0
            data['defi_tvl'] = tvl
            data['defi_tvl_change'] = round(change, 2)
            print(f'  DeFi TVL: ${tvl/1e9:.1f}B ({change:+.2f}%)')
    except Exception as e:
        print(f'  [DefiLlama TVL] {e}')

    # Top 5 协议
    try:
        d = _get('https://api.llama.fi/protocols')
        if d:
            # 过滤掉TVL为None的协议
            valid = [p for p in d if p.get('tvl') is not None and isinstance(p.get('tvl'), (int, float))]
            top5 = sorted(valid, key=lambda x: x.get('tvl', 0), reverse=True)[:5]
            data['defi_top5'] = [{'name': p['name'], 'tvl': p.get('tvl', 0),
                                  'change_1d': round(p.get('change_1d', 0) or 0, 2)}
                                 for p in top5]
    except Exception as e:
        print(f'  [DefiLlama Top5] {e}')

    # 稳定币
    try:
        d = _get('https://stablecoins.llama.fi/stablecoins?includePrices=true')
        stables = d.get('peggedAssets', [])
        total_stable_mcap = sum(s.get('circulating', {}).get('peggedUSD', 0) for s in stables)
        data['stable_mcap'] = total_stable_mcap
        # Top 3
        top3 = sorted(stables, key=lambda x: x.get('circulating', {}).get('peggedUSD', 0), reverse=True)[:3]
        data['stable_top3'] = [{'name': s['name'], 'mcap': s.get('circulating', {}).get('peggedUSD', 0)}
                               for s in top3]
        print(f'  稳定币总市值: ${total_stable_mcap/1e9:.1f}B')
    except Exception as e:
        print(f'  [DefiLlama Stables] {e}')

    return data


# ============================================================
# 数据采集：算力60天趋势 + quickchart.io折线图
# ============================================================
def collect_hashrate_chart():
    """从mempool.space获取60天算力历史，生成quickchart.io折线图URL"""
    try:
        d = _get('https://mempool.space/api/v1/mining/hashrate/3m', timeout=15)
        hashrates = d.get('hashrates', [])
        if not hashrates:
            return None

        # 取最近60天
        recent = hashrates[-60:]
        points = []
        for h in recent:
            dt = datetime.fromtimestamp(h['timestamp'], tz=BJT)
            ehs = h['avgHashrate'] / 1e18
            points.append({'date': dt.strftime('%m-%d'), 'ehs': round(ehs, 1)})

        if len(points) < 5:
            return None

        values = [p['ehs'] for p in points]
        v_first, v_last = values[0], values[-1]
        change = (v_last - v_first) / v_first * 100

        # 生成quickchart.io折线图
        # 每5天显示一个标签，避免拥挤
        labels = [p['date'] if i % 5 == 0 else '' for i, p in enumerate(points)]

        chart_cfg = {
            "type": "line",
            "data": {
                "labels": labels,
                "datasets": [{
                    "data": values,
                    "borderColor": "#2196F3",
                    "backgroundColor": "rgba(33,150,243,0.08)",
                    "fill": True,
                    "tension": 0.3,
                    "pointRadius": 0,
                    "borderWidth": 2
                }]
            },
            "options": {
                "plugins": {"legend": {"display": False},
                            "title": {"display": True, "text": f"BTC Hashrate 60D ({v_first:.0f}->{v_last:.0f} EH/s, {change:+.1f}%)",
                                      "font": {"size": 14}}},
                "scales": {
                    "y": {"title": {"display": True, "text": "EH/s"},
                           "grid": {"color": "rgba(0,0,0,0.05)"}},
                    "x": {"ticks": {"maxRotation": 45, "font": {"size": 10}},
                           "grid": {"display": False}}
                }
            }
        }

        # 尝试用POST API获取短URL
        chart_url = None
        try:
            payload = json.dumps({
                "chart": chart_cfg,
                "width": 600, "height": 280,
                "backgroundColor": "white",
                "format": "png"
            }).encode()
            req = Request('https://quickchart.io/chart/create', data=payload,
                          headers={'Content-Type': 'application/json'})
            resp = json.loads(urlopen(req, timeout=15).read())
            chart_url = resp.get('url', '')
            print(f'  算力图表: {chart_url[:60]}...')
        except Exception as e:
            print(f'  [quickchart POST] {e}')
            # Fallback: GET URL
            chart_json = json.dumps(chart_cfg, separators=(',', ':'))
            chart_url = f'https://quickchart.io/chart?c={url_quote(chart_json)}&w=600&h=280&bkg=white'

        summary = f'全网算力60日: {v_first:.0f} -> {v_last:.0f} EH/s ({change:+.1f}%)'
        print(f'  {summary}')

        return {'summary': summary, 'chart_url': chart_url, 'first': v_first, 'last': v_last, 'change': change}
    except Exception as e:
        print(f'  [Hashrate Chart] {e}')
        return None


# ============================================================
# 数据采集：传统市场（Yahoo Finance）
# ============================================================
def collect_macro_data():
    data = {}
    for key, symbol, label in [
        ('dxy', 'DX-Y.NYB', 'DXY美元指数'),
        ('gold', 'GC=F', '黄金'),
        ('us10y', '^TNX', '10Y美债'),
        ('usdcny', 'CNY=X', 'USD/CNY'),
    ]:
        try:
            url = f'https://query1.finance.yahoo.com/v8/finance/chart/{url_quote(symbol, safe="")}?range=5d&interval=1d'
            d = _get(url, timeout=10)
            meta = d['chart']['result'][0]['meta']
            price = meta.get('regularMarketPrice', 0)
            prev = meta.get('chartPreviousClose', meta.get('previousClose', 0))
            change = ((price - prev) / prev * 100) if prev else 0
            data[f'{key}_price'] = round(price, 4)
            data[f'{key}_change'] = round(change, 2)
            print(f'  {label}: {price:.2f} ({change:+.2f}%)')
        except Exception as e:
            print(f'  [Yahoo {label}] {e}')
    return data


# ============================================================
# 数据采集：A股市场（东方财富）
# ============================================================
def collect_ashare_data():
    data = {}
    now = datetime.now(BJT)
    is_trading = (now.weekday() < 5 and
                  ((now.hour == 9 and now.minute >= 30) or
                   (10 <= now.hour <= 11) or
                   (13 <= now.hour <= 14) or
                   (now.hour == 15 and now.minute == 0)))
    is_after_close = (now.weekday() < 5 and now.hour >= 15)
    data['ashare_note'] = '' if (is_trading or is_after_close) else '（昨收，A股未开盘）'
    if data['ashare_note']:
        print(f'  注意: 当前{now.strftime("%H:%M")} BJT，A股未开盘')

    for key, secid, label in [
        ('csi300', '1.000300', '沪深300'),
        ('shcomp', '1.000001', '上证综指'),
        ('chinext', '0.399006', '创业板指'),
    ]:
        try:
            url = f'https://push2.eastmoney.com/api/qt/stock/get?secid={secid}&fields=f43,f44,f45,f46,f170,f48'
            d = _get(url)
            info = d.get('data')
            if not info or info.get('f43') is None:
                continue
            price = info['f43'] / 100 if isinstance(info['f43'], int) else info['f43']
            change = info.get('f170', 0)
            change = change / 100 if isinstance(change, int) else change
            data[f'{key}_price'] = price
            data[f'{key}_change'] = change
            print(f'  {label}: {price:.2f} ({change:+.2f}%)')
        except Exception as e:
            print(f'  [东方财富 {label}] {e}')

    # 北向资金
    try:
        url = 'https://push2.eastmoney.com/api/qt/kamt.rtmin/get?fields1=f1,f2,f3,f4&fields2=f51,f52,f53,f54,f55,f56'
        d = _get(url)
        s2n = d.get('data', {}).get('s2n', [])
        if s2n and isinstance(s2n, list):
            for item in reversed(s2n):
                if isinstance(item, str) and ',' in item:
                    fields = item.split(',')
                    if len(fields) >= 4 and fields[3] != '-':
                        try:
                            data['nb_total'] = float(fields[3])
                            print(f'  北向资金: {data["nb_total"]/10000:.2f}亿')
                        except ValueError:
                            pass
                        break
    except Exception as e:
        print(f'  [北向资金] {e}')

    # 融资融券余额
    try:
        url = ('https://datacenter-web.eastmoney.com/api/data/v1/get?'
               'sortColumns=TRADE_DATE&sortTypes=-1&pageSize=2&pageNumber=1'
               '&reportName=RPTA_WEB_RZRQ_GGMX&columns=TRADE_DATE,RZYE,RQYE,RZRQYE')
        d = _get(url, timeout=8)
        result = d.get('result') or {}
        rows = result.get('data') or []
        if rows and len(rows) > 0:
            latest = rows[0]
            rzrqye = latest.get('RZRQYE')
            if rzrqye is not None:
                data['margin_balance'] = float(rzrqye)
                if len(rows) > 1:
                    prev_val = rows[1].get('RZRQYE')
                    if prev_val is not None:
                        data['margin_change'] = float(rzrqye) - float(prev_val)
                print(f'  融资融券: {data["margin_balance"]/1e8:.0f}亿')
    except Exception as e:
        print(f'  [融资融券] {e}')

    return data


# ============================================================
# 数据采集：经济日历（Forex Factory）
# ============================================================
def collect_calendar():
    events = []
    try:
        all_ev = _get('https://nfs.faireconomy.media/ff_calendar_thisweek.json')
        today = datetime.now(BJT).strftime('%Y-%m-%d')
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
# 数据采集：OKX关键事件（公告API，无需认证）
# ============================================================
OKX_ANN_TYPES = [
    ('announcements-new-listings', '新币上线'),
    ('announcements-delistings', '下架'),
    ('announcements-deposit-withdrawal-suspension-resumption', '网络升级/分叉'),
    ('announcements-jumpstart', '新项目首发'),
]


def collect_okx_events():
    """从OKX公告API获取最近48小时的关键事件"""
    events = []
    now_ms = int(time.time() * 1000)
    cutoff_ms = now_ms - MAX_AGE_HOURS * 3600 * 1000

    for ann_type, label in OKX_ANN_TYPES:
        try:
            url = f'https://www.okx.com/api/v5/support/announcements?annType={ann_type}&page=1'
            d = _get(url, timeout=10)
            if d.get('code') != '0':
                continue
            details = d.get('data', [{}])[0].get('details', [])
            for item in details:
                ptime = int(item.get('pTime', 0))
                if ptime < cutoff_ms:
                    continue
                title = item.get('title', '').strip()
                if not title:
                    continue
                events.append({
                    'title': title[:200],
                    'type': label,
                    'url': item.get('url', ''),
                    'time': datetime.fromtimestamp(ptime / 1000, tz=BJT).strftime('%m-%d %H:%M'),
                })
        except Exception as e:
            print(f'  [OKX {label}] {e}')

    # 按时间倒序
    events.sort(key=lambda x: x.get('time', ''), reverse=True)
    print(f'  OKX关键事件: {len(events)}条(48h)')
    return events


# ============================================================
# 数据采集：BlockBeats快讯（链上动态+项目资讯+行业快讯）
# ============================================================
def collect_blockbeats_flash():
    """从BlockBeats(律动) RSS获取最近24小时的加密行业快讯"""
    flashes = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

    try:
        url = 'https://api.theblockbeats.news/v2/rss/newsflash'
        req = Request(url, headers=UA)
        raw = urlopen(req, timeout=15).read()
        root = ET.fromstring(raw)

        for item in root.findall('.//item'):
            title = (item.findtext('title') or '').strip()
            if not title:
                continue

            pub_date = _parse_pub_date(item.findtext('pubDate'))
            if pub_date and pub_date < cutoff:
                continue

            desc = (item.findtext('description') or '').strip()
            # 清理HTML标签
            desc = re.sub(r'<[^>]+>', '', desc).strip()
            if len(desc) > 300:
                desc = desc[:300] + '...'

            time_str = pub_date.astimezone(BJT).strftime('%m-%d %H:%M') if pub_date else ''

            flashes.append({
                'title': title[:200],
                'desc': desc,
                'time': time_str,
                'link': (item.findtext('link') or '').strip(),
            })

        # 金融相关性过滤：只保留与投资/交易/市场相关的快讯
        finance_kw = re.compile(
            r'BTC|ETH|SOL|比特币|以太坊|USDT|USDC|稳定币|交易所|Coinbase|Binance|OKX|Bybit'
            r'|市值|清算|爆仓|鲸鱼|巨鲸|whale|转入|转出|抛售|增持|减持'
            r'|ETF|SEC|监管|合规|CFTC|美联储|Fed|降息|加息|利率'
            r'|TVL|DeFi|NFT|Layer|链上|Gas|矿工|算力|挖矿|减半'
            r'|融资|估值|IPO|上市|收购|并购|破产|清盘'
            r'|Trump|特朗普|关税|tariff|制裁|sanction'
            r'|涨|跌|突破|回调|暴跌|暴涨|新高|新低|创新|反弹',
            re.IGNORECASE
        )
        before = len(flashes)
        flashes = [f for f in flashes if finance_kw.search(f['title'] + f['desc'])]

        print(f'  BlockBeats快讯: {len(flashes)}条(过滤前{before},24h)')
    except Exception as e:
        print(f'  [BlockBeats] {e}')

    return flashes[:30]  # 最多30条


# ============================================================
# 新闻采集（v3.0 大换血）
# ============================================================

# 精准金融新闻源（砍掉所有通用Google News搜索）
RSS_SOURCES = [
    # === 加密货币（直接RSS，质量最高）===
    ('CoinDesk', 'https://www.coindesk.com/arc/outboundfeeds/rss/', 'crypto', 10),
    ('CoinTelegraph', 'https://cointelegraph.com/rss', 'crypto', 10),
    ('The Block', 'https://www.theblock.co/rss.xml', 'crypto', 8),
    ('Bitcoin Magazine', 'https://bitcoinmagazine.com/feed', 'crypto', 6),
    ('Decrypt', 'https://decrypt.co/feed', 'crypto', 8),
    ('DL News', 'https://www.dlnews.com/arc/outboundfeeds/rss/', 'crypto', 6),

    # === 宏观经济（精准短语搜索，双引号锁定）===
    ('Fed/Rates', 'https://news.google.com/rss/search?q=%22federal+reserve%22+OR+%22interest+rate+decision%22+OR+%22fed+minutes%22+OR+%22FOMC%22&hl=en-US&gl=US&ceid=US:en', 'macro', 8),
    ('Inflation/Jobs', 'https://news.google.com/rss/search?q=%22CPI+data%22+OR+%22inflation+rate%22+OR+%22nonfarm+payroll%22+OR+%22PCE+price%22+OR+%22jobs+report%22&hl=en-US&gl=US&ceid=US:en', 'macro', 6),
    ('Bond/Dollar', 'https://news.google.com/rss/search?q=%22treasury+yield%22+OR+%22dollar+index%22+OR+%22bond+market%22+OR+%22yield+curve%22&hl=en-US&gl=US&ceid=US:en', 'macro', 6),
    ('Trade/Tariff', 'https://news.google.com/rss/search?q=%22trade+tariff%22+OR+%22trade+war%22+OR+%22sanctions%22+OR+%22tariff+policy%22+when:7d&hl=en-US&gl=US&ceid=US:en', 'macro', 6),

    # === 中国/A股（精准搜索）===
    ('PBOC/China', 'https://news.google.com/rss/search?q=%22PBOC%22+OR+%22China+stimulus%22+OR+%22RRR+cut%22+OR+%22LPR+rate%22+OR+%22Chinese+economy%22+when:7d&hl=en-US&gl=US&ceid=US:en', 'china', 6),
    ('A-Shares', 'https://news.google.com/rss/search?q=%22A-shares%22+OR+%22Shanghai+Composite%22+OR+%22CSI+300%22+OR+%22northbound+capital%22+OR+%22China+stock%22&hl=en-US&gl=US&ceid=US:en', 'china', 6),
]

# 财联社金融关键词（过滤非金融新闻）
CLS_KEYWORDS = [
    '股', 'A股', '基金', '央行', '利率', '通胀', 'GDP', '货币', '债券', '汇率',
    '人民币', '北向', '融资', '降准', '降息', '比特币', '加密', '区块链', '数字货币',
    '原油', '黄金', '大宗', '期货', '市场', '投资', '金融', '证监', '银保监',
    '经济', '财政', '税', '外资', '美联储', '美元', '关税', '贸易', '制裁',
    '上市', '退市', '涨停', '跌停', '新股', '两融', '量化', '公募', '私募',
    '沪深', '创业板', '科创板', '港股', '美股', '日经', '恒生',
]

# 全局金融相关性关键词（用于过滤所有新闻源）
RELEVANCE_KEYWORDS = {
    'high': [
        # 加密货币核心
        'bitcoin', 'btc', 'ethereum', 'eth', 'crypto', 'stablecoin', 'usdt', 'usdc',
        'etf', 'defi', 'sec', 'binance', 'coinbase', 'solana', 'sol',
        'halving', 'mining', 'whale', 'regulation', 'cbdc',
        '比特币', '以太坊', '加密货币', '稳定币', '虚拟货币', '数字资产',
        # 宏观核心
        'federal reserve', 'fed', 'fomc', 'interest rate', 'inflation', 'cpi',
        'gdp', 'treasury', 'bond', 'yield', 'dollar', 'tariff', 'recession',
        '美联储', '降息', '加息', '通胀', '关税', '衰退',
        # A股核心
        'a-share', 'csi 300', 'pboc', 'northbound',
        'A股', '沪深', '北向', '央行', '降准', '人民币',
    ],
    'medium': [
        'blockchain', 'web3', 'nft', 'token', 'dex', 'lending', 'airdrop',
        'central bank', 'ecb', 'boj', 'stimulus', 'fiscal', 'employment',
        'trade war', 'sanctions', 'commodity', 'crude oil', 'gold price',
        '区块链', '港股', '美股', '期货', '原油', '黄金', '基金',
        '经济', '财政', '外资', '融资', '量化', '市场',
    ]
}


def fetch_rss(name, url, max_items=8):
    """获取RSS/Atom源"""
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
                pub_str = (item.findtext('atom:published', '', atom_ns) or
                           item.findtext('atom:updated', '', atom_ns) or '').strip()
            else:
                title = (item.findtext('title') or '').strip()
                pub_str = (item.findtext('pubDate') or
                           item.findtext('dc:date', '', dc_ns) or '').strip()
            if not title:
                continue
            dt = _parse_pub_date(pub_str)
            if dt and (now_utc - dt).total_seconds() > MAX_AGE_HOURS * 3600:
                continue
            news.append({'title': title[:200], 'source': name})
            if len(news) >= max_items:
                break
    except Exception as e:
        print(f'    [{name}] {e}')
    return news


def fetch_cls(max_items=20):
    """财联社电报，带金融关键词过滤"""
    news = []
    try:
        d = _get(f'https://www.cls.cn/nodeapi/updateTelegraphList?app=CailianpressWeb&os=web&rn={max_items * 2}&sv=8.4.6')
        for item in d.get('data', {}).get('roll_data', []):
            title = (item.get('title') or item.get('content', '')[:100]).strip()
            if not title:
                continue
            # 关键词过滤：只保留金融/市场相关
            if not any(kw in title for kw in CLS_KEYWORDS):
                continue
            news.append({'title': title[:200], 'source': '财联社'})
            if len(news) >= max_items:
                break
    except Exception as e:
        print(f'    [财联社] {e}')
    return news


def score_relevance(title):
    """计算新闻标题的金融相关性分数（0-10）"""
    title_lower = title.lower()
    score = 0
    for kw in RELEVANCE_KEYWORDS['high']:
        if kw.lower() in title_lower:
            score += 3
    for kw in RELEVANCE_KEYWORDS['medium']:
        if kw.lower() in title_lower:
            score += 1
    return min(score, 10)


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
    """采集+过滤新闻（三层过滤）"""
    news = {'macro': [], 'crypto': [], 'china': []}
    failed_sources = []

    # 采集RSS
    for name, url, cat, max_n in RSS_SOURCES:
        items = fetch_rss(name, url, max_n)
        if not items:
            failed_sources.append(name)
        for n in items:
            n['category'] = cat
        news[cat].extend(items)
        print(f'    {name}: {len(items)}')
        time.sleep(0.1)

    # 财联社（已内置关键词过滤）
    cls = fetch_cls(15)
    if not cls:
        failed_sources.append('财联社')
    for n in cls:
        n['category'] = 'china'
    news['china'].extend(cls)
    print(f'    财联社(filtered): {len(cls)}')

    # === 三层过滤 ===
    total_before = sum(len(v) for v in news.values() if isinstance(v, list))

    for cat in ['macro', 'crypto', 'china']:
        # Layer 1: 金融相关性过滤（score >= 1才保留）
        before_rel = len(news[cat])
        news[cat] = [n for n in news[cat] if score_relevance(n['title']) >= 1]
        after_rel = len(news[cat])
        if before_rel != after_rel:
            print(f'    {cat} 相关性过滤: {before_rel}->{after_rel}')

        # Layer 2: 模糊去重
        before_dup = len(news[cat])
        news[cat] = fuzzy_dedup(news[cat])
        if before_dup != len(news[cat]):
            print(f'    {cat} 去重: {before_dup}->{len(news[cat])}')

    total_after = sum(len(v) for v in news.values() if isinstance(v, list))
    total_sources = len(RSS_SOURCES) + 1
    ok_sources = total_sources - len(failed_sources)
    print(f'  过滤: {total_before}->{total_after}条 | 源: {ok_sources}/{total_sources}' +
          (f' 失败: {", ".join(failed_sources)}' if failed_sources else ''))

    news['_health'] = {'ok': ok_sources, 'total': total_sources, 'failed': failed_sources}
    return news


# ============================================================
# 数据上下文构建（给Claude的完整市场数据包）
# ============================================================
def build_data_context(crypto, macro, ashare, defi, news, calendar, okx_events=None, bb_flash=None):
    now = datetime.now(BJT)
    ctx = [f'=== 市场数据快照 {now.strftime("%Y-%m-%d %H:%M")} BJT ===\n']

    # --- 加密货币 ---
    ctx.append('【加密货币】')
    if crypto.get('BTC_price'):
        ctx.append(f'BTC: ${crypto["BTC_price"]:,.2f} (24h {crypto.get("BTC_change",0):+.2f}%) '
                   f'高${crypto.get("BTC_high",0):,.0f} 低${crypto.get("BTC_low",0):,.0f} '
                   f'成交${crypto.get("BTC_vol",0)/1e8:.1f}亿')
    if crypto.get('ETH_price'):
        ctx.append(f'ETH: ${crypto["ETH_price"]:,.2f} (24h {crypto.get("ETH_change",0):+.2f}%)')

    # 衍生品（跨交易所对比）
    derivs = []
    if crypto.get('BTC_okx_funding') is not None:
        f_okx = crypto['BTC_okx_funding']
        f_bn = crypto.get('BTC_bn_funding', 'N/A')
        derivs.append(f'BTC资金费率: OKX {f_okx:+.4f}% / Binance {f_bn if isinstance(f_bn,str) else f"{f_bn:+.4f}%"}')
    if crypto.get('ETH_okx_funding') is not None:
        f_okx = crypto['ETH_okx_funding']
        f_bn = crypto.get('ETH_bn_funding', 'N/A')
        derivs.append(f'ETH资金费率: OKX {f_okx:+.4f}% / Binance {f_bn if isinstance(f_bn,str) else f"{f_bn:+.4f}%"}')
    if crypto.get('BTC_okx_oi'):
        ctx.append(f'BTC OI: OKX {crypto["BTC_okx_oi"]:,.0f}张' +
                   (f' / Binance {crypto["BTC_bn_oi_usdt"]:,.0f} USDT' if crypto.get('BTC_bn_oi_usdt') else ''))
    if crypto.get('BTC_okx_ls') or crypto.get('BTC_bn_ls'):
        parts = []
        if crypto.get('BTC_okx_ls'):
            parts.append(f'OKX {crypto["BTC_okx_ls"]:.2f}')
        if crypto.get('BTC_bn_ls'):
            parts.append(f'Binance {crypto["BTC_bn_ls"]:.2f}')
        ctx.append(f'BTC多空比: {" / ".join(parts)}')
    for line in derivs:
        ctx.append(line)

    if crypto.get('fng_value'):
        trend_str = ' '.join(str(v) for v in crypto.get('fng_7d', []))
        ctx.append(f'恐贪指数: {crypto["fng_value"]}/100 ({crypto["fng_class"]}) '
                   f'7日趋势({crypto.get("fng_trend","")}):[{trend_str}] 均值{crypto.get("fng_7d_avg",0)}')

    # 全局
    if crypto.get('total_mcap'):
        ctx.append(f'总市值: ${crypto["total_mcap"]/1e12:.2f}T ({crypto.get("mcap_change_24h",0):+.2f}%) '
                   f'BTC占比{crypto.get("btc_dominance",0)}% ETH占比{crypto.get("eth_dominance",0)}%')

    # 链上
    chain_parts = []
    if crypto.get('hashrate_ehs'):
        chain_parts.append(f'算力{crypto["hashrate_ehs"]}EH/s')
    if crypto.get('fee_fast'):
        chain_parts.append(f'手续费{crypto["fee_fast"]}/{crypto["fee_mid"]}/{crypto["fee_slow"]}sat/vB')
    if crypto.get('diff_progress'):
        chain_parts.append(f'难度调整{crypto["diff_progress"]}%(预计{crypto.get("diff_est_change",0):+.1f}%)')
    if chain_parts:
        ctx.append(f'BTC链上: {" | ".join(chain_parts)}')
    ctx.append('')

    # --- DeFi ---
    if defi.get('defi_tvl'):
        ctx.append('【DeFi】')
        ctx.append(f'总TVL: ${defi["defi_tvl"]/1e9:.1f}B ({defi.get("defi_tvl_change",0):+.2f}%)')
        if defi.get('defi_top5'):
            top5_str = ', '.join(f'{p["name"]}(${p["tvl"]/1e9:.1f}B,{p["change_1d"]:+.1f}%)' for p in defi['defi_top5'])
            ctx.append(f'Top5: {top5_str}')
        if defi.get('stable_mcap'):
            ctx.append(f'稳定币总市值: ${defi["stable_mcap"]/1e9:.1f}B')
            if defi.get('stable_top3'):
                s3 = ', '.join(f'{s["name"]}(${s["mcap"]/1e9:.1f}B)' for s in defi['stable_top3'])
                ctx.append(f'Top3: {s3}')
        ctx.append('')

    # --- 宏观 ---
    ctx.append('【全球宏观】')
    for key, label in [('dxy', 'DXY美元'), ('gold', '黄金$/oz'), ('us10y', '10Y美债%'), ('usdcny', 'USD/CNY')]:
        if macro.get(f'{key}_price'):
            ctx.append(f'{label}: {macro[f"{key}_price"]:.4f} ({macro.get(f"{key}_change",0):+.2f}%)')
    ctx.append('')

    # --- A股 ---
    note = ashare.get('ashare_note', '')
    ctx.append(f'【A股】{note}')
    for key, label in [('csi300', '沪深300'), ('shcomp', '上证'), ('chinext', '创业板')]:
        if ashare.get(f'{key}_price'):
            ctx.append(f'{label}: {ashare[f"{key}_price"]:,.2f} ({ashare.get(f"{key}_change",0):+.2f}%)')
    if ashare.get('nb_total') is not None:
        nb = ashare['nb_total'] / 10000
        ctx.append(f'北向资金: {"净买入" if nb > 0 else "净卖出"}{abs(nb):.2f}亿')
    if ashare.get('margin_balance'):
        ctx.append(f'融资融券: {ashare["margin_balance"]/1e8:.0f}亿' +
                   (f' (日变{ashare["margin_change"]/1e8:+.1f}亿)' if ashare.get('margin_change') else ''))
    ctx.append('')

    # --- 新闻（仅标题列表，已过滤）---
    cat_names = {'crypto': '加密货币', 'macro': '全球宏观', 'china': '中国/A股'}
    for cat in ['crypto', 'macro', 'china']:
        items = news.get(cat, [])
        if items:
            ctx.append(f'【{cat_names[cat]}要闻({len(items)}条)】')
            for n in items[:15]:
                ctx.append(f'- {n["title"]} ({n["source"]})')
            ctx.append('')

    # --- OKX关键事件 ---
    if okx_events:
        ctx.append(f'【OKX关键事件(48h内{len(okx_events)}条)】')
        for ev in okx_events:
            ctx.append(f'- [{ev["type"]}] {ev["title"]} ({ev["time"]})')
        ctx.append('')

    # --- BlockBeats快讯（链上动态+行业快讯）---
    if bb_flash:
        ctx.append(f'【链上动态与行业快讯({len(bb_flash)}条,BlockBeats)】')
        for f in bb_flash:
            line = f'- {f["title"]}'
            if f.get('time'):
                line += f' ({f["time"]})'
            ctx.append(line)
        ctx.append('')

    # --- 经济日历 ---
    if calendar:
        ctx.append('【今日经济日历】')
        for ev in calendar:
            ctx.append(f'- {ev["time_bjt"]} [{ev["country"]}] {ev["title"]} '
                       f'({ev["impact"]}, 预期:{ev.get("forecast","—")}, 前值:{ev.get("previous","—")})')
        ctx.append('')

    return '\n'.join(ctx)


# ============================================================
# Claude Sonnet 首席分析师（v3.2 投研级深度分析prompt）
# ============================================================
ANALYST_SYSTEM_PROMPT = """你是国兴超链集团的首席分析师，为董事长产出机构级投研报告。

你不是新闻播报员。你是Ray Dalio + Arthur Hayes + Howard Marks + 李迅雷的合体。
你的工作不是"告诉董事长发生了什么"——他自己会看新闻。
你的工作是告诉他"这意味着什么"、"因果链是什么"、"历史上类似情况怎样"、"该怎么做"。

董事长持仓：BTC为主的加密资产 + A股。

## 分析方法论（必须严格执行）

### 1. 核心矛盾分析法
每天市场只有1-2个核心矛盾。找到它，所有分析围绕它展开。
例："当前核心矛盾是美元流动性收缩 vs 加密市场减半叙事，前者压制后者"。
不要面面俱到什么都说一点。

### 2. 因果链推演（必须展示推理过程）
每个重要判断必须展示完整因果链：
事件 → 传导机制 → 一阶影响 → 二阶影响 → 对持仓的具体影响
例：
- "伊朗局势升级 → 油价飙升预期 → 通胀预期上修 → 美联储降息概率从68%降至45% → 美元走强 → BTC面临$82K支撑测试"
不能只说"地缘紧张利空风险资产"这种废话。

### 3. 历史类比（必须给出）
每个核心判断至少一个历史类比：
- "上一次恐贪指数连续5天低于25是2024年8月5日日元套利平仓，BTC从$49K反弹至$64K耗时23天"
- "上一次OKX-Binance资金费率出现这种分歧是2025年3月，随后出现15%的修正"
没有完美类比也要给最接近的，标注相似度。

### 4. 共识vs反共识
明确说出："当前市场共识是X，我认为共识[正确/有偏差]，因为Y。如果共识错了，可能发生Z。"

### 5. 量化到具体数字
- 不说"可能下跌" → 说"跌破$82,000(当前距离3.2%)概率55%，若破位目标$78,500(-7.4%)"
- 不说"北向资金流出" → 说"北向净卖出32亿，连续3日流出累计87亿，接近2024年9月触发反弹的-120亿阈值"
- 不说"资金费率偏低" → 说"BTC 8h费率0.001%，年化0.9%，低于30日均值0.8个标准差，市场杠杆收缩"

### 6. 信号矛盾必须标注
当不同信号指向相反方向时，必须明确标注⚡冲突：
"⚡信号冲突：恐贪指数25(极度恐惧，历史上是买入信号) vs 资金费率转负(空头占优)。冲突时的经验法则：费率>情绪，短期看空，但情绪极端后的反转通常在3-7天内到来。"

## 铁律
1. 不说"建议关注"——要说"建议做/不做什么"
2. 不说"可能"——要给概率和条件："如果X发生(概率60%)，则Y；如果X不发生，则Z"
3. 不说"谨慎观望"——要说"在$X建立Y%仓位"或"当前不动，等到Z信号出现再入场"
4. 与投资决策无关的新闻直接忽略
5. 中文输出"""

ANALYST_USER_PROMPT = """基于以下实时市场数据和新闻，产出投研级深度分析报告。

{data_context}

## 排版要求（必须严格遵守）
- 用##作为板块大标题（手机上字体够大）
- **禁止使用表格**（手机上表格会挤成一团），改用列表或加粗文字
- 每个板块之间空一行
- 关键数字必须**加粗**（如**$84,200**、**+3.2%**、**概率60%**）
- 每段不超过4行，长段落必须拆成多个短段
- 用emoji标注重要程度：🔴紧急 🟡注意 🟢正常

## 输出结构（markdown，不要用表格）：

## 🎯 今日核心矛盾

（一句话定义今天市场的核心矛盾，**加粗关键词**，所有后续分析围绕它展开）

---

## 📊 市场全景

逐个列出，每个资产一行，格式：
- **BTC** **$XX,XXX** (24h **+X.X%**) — 一句研判（如"测试$85K阻力，突破概率40%"）
- **ETH** **$X,XXX** (24h **+X.X%**) — 一句研判
- **沪深300** **X,XXX** (24h **+X.X%**) — 一句研判
- **DXY** **XXX.XX** (24h **+X.X%**) — 一句研判
- **黄金** **$X,XXX** — 一句研判
- **10Y美债** **X.XX%** — 一句研判

---

## 🔗 加密货币深度

**📖 主线叙事**

当前加密市场主线是什么？用2-3句话讲清楚故事线。

**📐 价格结构**

BTC/ETH关键价位，支撑/阻力位，**必须给具体数字和概率**。

**📉 衍生品信号**

资金费率+OI+多空比三个指标**组合起来**在说什么？跨交易所差异意味着什么？不要分别列数据。

**⛓️ 链上与DeFi**

TVL/稳定币/链上数据有没有异常？因果解释。

**📚 历史类比**

当前最像历史上哪个阶段？相似度？当时后续走势？

---

## 🏛️ 宏观传导链

不要分开说宏观和A股。用一条因果链串起来：
**全球流动性 → 美元 → 利率 → 风险偏好 → 加密&A股**

北向资金/融资融券变化是结果，分析背后的原因。

---

## ⚡ 关键事件（只挑2-3个）

从新闻/公告/快讯中只挑**真正影响投资决策**的事件。每个事件：

**事件1：XXXXX**
- 发生了什么（一句话）
- 传导机制（为什么重要）
- 历史类比（上次类似事件后市场怎么走）
- 对持仓的影响

**事件2：XXXXX**
- （同上格式）

与投资无关的新闻一律不提。

---

## 🛡️ 风险清单

每个风险用这个格式（不要用表格）：

🔴/🟡/🟢 **风险名称**
- 触发条件：XXX
- 影响：XXX
- 对冲：XXX

---

## 💰 操作方案

**BTC**
- 方向：XX | 置信度：XX | 时间框架：XX
- 入场：**$XX,XXX**（+确认信号）
- 止损：**$XX,XXX** / 止盈：**$XX,XXX**
- Plan B：如果判断错了→XXX

**A股**
- 方向：XX | 置信度：XX
- 关注板块：XXX
- 关键观察：XXX

---

## 📅 今日盯盘

每个事件格式：
- **HH:MM** XXX事件 — 如果结果是X则Y，如果是Z则W"""


def analyze_with_claude(data_context, max_retries=2):
    """调用Claude Sonnet统一分析"""
    if not ANTHROPIC_API_KEY:
        print('  ANTHROPIC_API_KEY未设置')
        return None

    payload = {
        'model': ANTHROPIC_MODEL,
        'max_tokens': 6000,
        'system': ANALYST_SYSTEM_PROMPT,
        'messages': [
            {'role': 'user', 'content': ANALYST_USER_PROMPT.format(data_context=data_context)}
        ],
    }
    raw_data = json.dumps(payload).encode('utf-8')

    for attempt in range(1, max_retries + 1):
        try:
            req = Request('https://api.anthropic.com/v1/messages', data=raw_data, headers={
                'x-api-key': ANTHROPIC_API_KEY,
                'anthropic-version': '2023-06-01',
                'content-type': 'application/json',
            })
            resp = json.loads(urlopen(req, timeout=180).read().decode())
            if resp.get('content'):
                analysis = resp['content'][0]['text']
                tokens = resp.get('usage', {})
                print(f'  Claude分析完成 (attempt {attempt}, in:{tokens.get("input_tokens",0)} out:{tokens.get("output_tokens",0)})')
                return analysis
            else:
                print(f'  [Claude] attempt {attempt} 无内容: {resp}')
        except Exception as e:
            print(f'  [Claude] attempt {attempt}: {e}')
            if hasattr(e, 'read'):
                try:
                    print(f'  Response: {e.read().decode()[:300]}')
                except Exception:
                    pass
            if attempt < max_retries:
                time.sleep(10)

    print('  [Claude] 所有重试失败')
    return None


# ============================================================
# 报告组装
# ============================================================
def build_fallback(crypto, macro, ashare, defi, news, calendar):
    """Claude失败时的纯数据fallback"""
    L = ['> Claude分析暂不可用，以下为原始数据\n']
    L.append('## 市场快照')
    L.append('| 资产 | 价格 | 24h |')
    L.append('|------|------|-----|')
    if crypto.get('BTC_price'):
        L.append(f'| BTC | ${crypto["BTC_price"]:,.0f} | {crypto.get("BTC_change",0):+.2f}% |')
    if crypto.get('ETH_price'):
        L.append(f'| ETH | ${crypto["ETH_price"]:,.0f} | {crypto.get("ETH_change",0):+.2f}% |')
    if ashare.get('csi300_price'):
        L.append(f'| 沪深300 | {ashare["csi300_price"]:,.2f} | {ashare.get("csi300_change",0):+.2f}% |')
    if macro.get('dxy_price'):
        L.append(f'| DXY | {macro["dxy_price"]:.2f} | {macro.get("dxy_change",0):+.2f}% |')
    if macro.get('gold_price'):
        L.append(f'| 黄金 | ${macro["gold_price"]:,.2f} | {macro.get("gold_change",0):+.2f}% |')
    L.append('')
    if defi.get('defi_tvl'):
        L.append(f'**DeFi TVL**: ${defi["defi_tvl"]/1e9:.1f}B | **稳定币**: ${defi.get("stable_mcap",0)/1e9:.1f}B')
    L.append('')
    cat_names = {'crypto': '加密货币', 'macro': '宏观', 'china': 'A股/中国'}
    for cat in ['crypto', 'macro', 'china']:
        items = news.get(cat, [])
        if items:
            L.append(f'### {cat_names[cat]}要闻')
            for i, n in enumerate(items[:8], 1):
                L.append(f'{i}. {n["title"]} ({n["source"]})')
            L.append('')
    return '\n'.join(L)


def build_final_report(analysis, crypto, macro, ashare, defi, news, calendar, hr_chart=None):
    """组装最终推送"""
    now = datetime.now(BJT)
    total = sum(len(v) for v in news.values() if isinstance(v, list))
    health = news.get('_health', {})

    header = f'# 每日市场情报\n**{now.strftime("%Y-%m-%d")} · 首席分析师简报 v3.2**\n'
    body = analysis if analysis else build_fallback(crypto, macro, ashare, defi, news, calendar)

    # 算力折线图
    chart_section = ''
    if hr_chart and hr_chart.get('chart_url'):
        chart_section = (f'\n\n## 全网算力60日走势\n'
                         f'![BTC Hashrate 60D]({hr_chart["chart_url"]})\n'
                         f'*{hr_chart["summary"]}*\n')

    # 源健康
    health_note = ''
    failed = health.get('failed', [])
    if failed:
        health_note = f'\n> {len(failed)}个源离线: {", ".join(failed)}\n'

    footer = (f'\n---\n'
              f'*{health.get("ok",0)}源 · {total}条新闻(过滤后) · Claude Sonnet · v3.2*\n'
              f'*数据: OKX(行情+公告)/Binance/CoinGecko/DefiLlama/BlockBeats/mempool/Yahoo/东方财富*')

    return header + '\n' + body + chart_section + health_note + footer


# ============================================================
# 推送 + 存档
# ============================================================
def push_serverchan(report):
    if not SERVERCHAN_KEY:
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
    print(f'  每日市场情报 v3.2 — 首席分析师(Claude Sonnet)')
    print(f'  {now.strftime("%Y-%m-%d %H:%M:%S")} BJT')
    print(f'{"="*60}')

    print('\n[1/10] 加密货币(OKX+Binance+CoinGecko)...')
    crypto = collect_crypto_data()

    print('\n[2/10] DeFi(DefiLlama)...')
    defi = collect_defi_data()

    print('\n[3/10] 算力60日图表...')
    hr_chart = collect_hashrate_chart()

    print('\n[4/10] 传统市场(Yahoo)...')
    macro = collect_macro_data()

    print('\n[5/10] A股(东方财富)...')
    ashare = collect_ashare_data()

    print('\n[6/10] 新闻(过滤采集)...')
    news = collect_all_news()
    total = sum(len(v) for v in news.values() if isinstance(v, list))
    print(f'  合计(过滤后): {total}条')

    print('\n[7/10] 经济日历...')
    calendar = collect_calendar()

    print('\n[8/10] OKX关键事件...')
    okx_events = collect_okx_events()

    print('\n[9/10] BlockBeats快讯(链上动态+行业)...')
    bb_flash = collect_blockbeats_flash()

    print('\n[10/10] Claude Sonnet 统一深度分析...')
    data_ctx = build_data_context(crypto, macro, ashare, defi, news, calendar, okx_events=okx_events, bb_flash=bb_flash)
    analysis = analyze_with_claude(data_ctx)

    print('\n组装 + 推送...')
    report = build_final_report(analysis, crypto, macro, ashare, defi, news, calendar, hr_chart)
    print(f'  简报: {len(report)}字')

    sc_ok = push_serverchan(report)
    sb_ok = archive_supabase(report, total)

    status = 'AI分析' if analysis else '数据fallback'
    print(f'\n{"="*60}')
    print(f'  完成 | {status} | Server酱:{"OK" if sc_ok else "FAIL"} | Supabase:{"OK" if sb_ok else "FAIL"} | {total}条')
    print(f'{"="*60}\n')

    if not sc_ok:
        sys.exit(1)


if __name__ == '__main__':
    main()
