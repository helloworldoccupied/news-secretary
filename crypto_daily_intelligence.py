#!/usr/bin/env python3
"""
加密货币投研日报 v2.0 — Crypto Daily Intelligence (Mining-Focused)
专注BTC/ETH深度投研，矿场经营者视角

v2.0 改动（2026-03-06 董事会决议+董事长调整）：
  - 只关注BTC和ETH，删除所有山寨币
  - 新增新闻分级系统（RED/YELLOW/GREEN + T1/T2/T3来源可信度）
  - 分析视角从"$50亿基金CIO"改为"BTC矿场董事长首席分析师"
  - 报告结构：市场快照→核心矛盾→矿工经济学→BTC深度→ETH→宏观→逐条新闻分析→DeFi→风险
  - 不限篇幅（笔记本/iPad阅读），可使用表格
  - 策略建议围绕矿场经营（持币/卖出/扩算力/电费），不涉及OKX自动化交易
  - 快照和深度合为一次推送

数据管线（20+数据源，BTC/ETH聚焦）：
  1. 市场总览：CoinGecko 全局数据 + BTC/ETH行情
  2. 链上基本面：Blockchain.info（Puell Multiple、NVT Ratio）
  3. 挖矿与难度：mempool.space + Blockchain.info
  4. 衍生品-资金费率：Binance + OKX + Bybit 三所对比（BTC/ETH）
  5. 衍生品-持仓与多空：OI + Long/Short Ratio + Taker Volume
  6. 期权市场：Deribit（Put/Call Ratio、DVOL、Max Pain、总OI）
  7. DeFi生态：DefiLlama TVL + DEX成交量 + 稳定币
  8. 宏观关联：Yahoo Finance DXY/黄金/美债/标普
  9. 情绪指标：Fear & Greed Index + CoinGecko Trending
  10. 新闻快讯：6源聚合 + 自动分级（RED/YELLOW/GREEN + T1/T2/T3）

分析：Claude Sonnet via Anthropic API（矿场视角+核心矛盾+因果链+历史类比）
推送：Server酱（微信推送，唯一通道）
"""
import sys
import os
import io
import json
import time
import re
import math
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from urllib.parse import quote as url_quote

# Windows UTF-8 兼容 — 移到 __main__ 入口，避免被import时重复包装导致I/O closed
# （由 generate_preview.py 通过 PYTHONIOENCODING=utf-8 环境变量处理编码）

# ============================================================
# 配置
# ============================================================
# LLM分析引擎：Claude Sonnet via Anthropic API（矿场经营者视角）
# 备选：DeepSeek（自动fallback）
SERVERCHAN_KEY = os.environ.get('SERVERCHAN_KEY', '')
SUPABASE_URL = os.environ.get('SUPABASE_URL', '')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY', '')

UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36'}
BJT = timezone(timedelta(hours=8))
TODAY_BJT = datetime.now(BJT).strftime('%Y-%m-%d')

def safe_float(val, default=0.0):
    """安全转float，处理空字符串/None"""
    if val is None or val == '':
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default

def safe_get(url, timeout=20, headers=None, retries=2):
    """安全HTTP GET，带重试"""
    hdrs = dict(UA)
    if headers:
        hdrs.update(headers)
    for attempt in range(retries + 1):
        try:
            req = Request(url, headers=hdrs)
            raw = urlopen(req, timeout=timeout).read()
            return json.loads(raw)
        except Exception as e:
            if attempt == retries:
                print(f'  [FAIL] {url[:80]}... {e}')
                return None
            time.sleep(2)
    return None

def safe_post(url, data, timeout=20, headers=None):
    """安全HTTP POST"""
    hdrs = dict(UA)
    hdrs['Content-Type'] = 'application/json'
    if headers:
        hdrs.update(headers)
    try:
        body = json.dumps(data).encode('utf-8')
        req = Request(url, data=body, headers=hdrs, method='POST')
        raw = urlopen(req, timeout=timeout).read()
        return json.loads(raw)
    except Exception as e:
        print(f'  [FAIL POST] {url[:80]}... {e}')
        return None


# ============================================================
# 数据采集函数
# ============================================================

def collect_market_overview():
    """Step 1: 市场总览 — CoinGecko全局 + 主要币种"""
    print('[1/10] 市场总览...')
    result = {'global': None, 'prices': {}, 'trending': []}

    # 全局数据
    g = safe_get('https://api.coingecko.com/api/v3/global')
    if g and 'data' in g:
        d = g['data']
        result['global'] = {
            'total_market_cap_usd': d.get('total_market_cap', {}).get('usd', 0),
            'total_volume_24h': d.get('total_volume', {}).get('usd', 0),
            'btc_dominance': d.get('market_cap_percentage', {}).get('btc', 0),
            'eth_dominance': d.get('market_cap_percentage', {}).get('eth', 0),
            'active_cryptocurrencies': d.get('active_cryptocurrencies', 0),
            'market_cap_change_24h': d.get('market_cap_change_percentage_24h_usd', 0),
        }

    time.sleep(1.5)  # CoinGecko rate limit

    # 主要币种行情
    coins = 'bitcoin,ethereum'
    p = safe_get(f'https://api.coingecko.com/api/v3/simple/price?ids={coins}'
                 f'&vs_currencies=usd&include_market_cap=true&include_24hr_vol=true'
                 f'&include_24hr_change=true&include_last_updated_at=true')
    if p:
        result['prices'] = p

    time.sleep(1.5)

    # CoinPaprika补充ATH等数据
    cp = safe_get('https://api.coinpaprika.com/v1/tickers/btc-bitcoin')
    if cp:
        q = cp.get('quotes', {}).get('USD', {})
        result['btc_extra'] = {
            'ath': q.get('ath_price', 0),
            'pct_from_ath': q.get('percent_from_price_ath', 0),
            'change_7d': q.get('percent_change_7d', 0),
            'change_30d': q.get('percent_change_30d', 0),
        }

    # Trending coins
    time.sleep(1.5)
    tr = safe_get('https://api.coingecko.com/api/v3/search/trending')
    if tr and 'coins' in tr:
        for c in tr['coins'][:10]:
            item = c.get('item', {})
            result['trending'].append({
                'name': item.get('name', ''),
                'symbol': item.get('symbol', ''),
                'market_cap_rank': item.get('market_cap_rank', 0),
            })

    return result


def collect_onchain_fundamentals():
    """Step 2: 链上基本面 — Blockchain.info + 计算Puell/NVT"""
    print('[2/10] 链上基本面...')
    result = {'stats': None, 'puell_multiple': None, 'nvt_ratio': None,
              'hash_rate_history': [], 'miners_revenue_history': []}

    # 全网统计
    stats = safe_get('https://api.blockchain.info/stats')
    if stats:
        result['stats'] = {
            'hash_rate': stats.get('hash_rate', 0),  # TH/s
            'difficulty': stats.get('difficulty', 0),
            'n_blocks_total': stats.get('n_blocks_total', 0),
            'n_tx_24h': stats.get('n_tx', 0),
            'total_btc_sent_24h': stats.get('total_btc_sent', 0) / 1e8,
            'market_price_usd': stats.get('market_price_usd', 0),
            'miners_revenue_usd': stats.get('miners_revenue_usd', 0),
            'estimated_btc_sent_24h': stats.get('estimated_btc_sent', 0) / 1e8,
            'n_blocks_mined_24h': stats.get('n_blocks_mined', 0),
        }

    # Puell Multiple = 当日矿工收入 / 365天MA矿工收入
    mr = safe_get('https://api.blockchain.info/charts/miners-revenue?timespan=365days&format=json&sampled=true')
    if mr and 'values' in mr:
        vals = [v['y'] for v in mr['values'] if v.get('y', 0) > 0]
        if vals:
            avg_365 = sum(vals) / len(vals)
            latest = vals[-1]
            result['puell_multiple'] = round(latest / avg_365, 4) if avg_365 > 0 else None
            result['miners_revenue_today'] = latest
            result['miners_revenue_365avg'] = round(avg_365)
            # 最近30天趋势
            result['miners_revenue_history'] = vals[-30:]

    # NVT Ratio = Market Cap / Daily TX Volume
    mc = safe_get('https://api.blockchain.info/charts/market-cap?timespan=7days&format=json')
    tv = safe_get('https://api.blockchain.info/charts/estimated-transaction-volume-usd?timespan=7days&format=json')
    if mc and tv and 'values' in mc and 'values' in tv:
        mc_latest = mc['values'][-1]['y'] if mc['values'] else 0
        tv_latest = tv['values'][-1]['y'] if tv['values'] else 0
        if tv_latest > 0:
            result['nvt_ratio'] = round(mc_latest / tv_latest, 1)
            result['nvt_market_cap'] = mc_latest
            result['nvt_tx_volume'] = tv_latest

    # 活跃地址
    aa = safe_get('https://api.blockchain.info/charts/n-unique-addresses?timespan=30days&format=json')
    if aa and 'values' in aa:
        vals = [v['y'] for v in aa['values']]
        if vals:
            result['active_addresses_today'] = vals[-1]
            result['active_addresses_7d_avg'] = round(sum(vals[-7:]) / min(7, len(vals[-7:])))
            result['active_addresses_30d_avg'] = round(sum(vals) / len(vals))

    # 哈希率趋势（60天）
    hr = safe_get('https://api.blockchain.info/charts/hash-rate?timespan=60days&format=json&sampled=true')
    if hr and 'values' in hr:
        result['hash_rate_history'] = [{'date': v['x'], 'value': v['y']} for v in hr['values']]

    return result


def collect_mining_difficulty():
    """Step 3: 挖矿与难度调整 — mempool.space + blockchain.info"""
    print('[3/10] 挖矿与难度...')
    result = {}

    # 难度调整预测
    da = safe_get('https://mempool.space/api/v1/difficulty-adjustment')
    if da:
        result['difficulty_adjustment'] = {
            'progress_pct': round(da.get('progressPercent', 0), 1),
            'estimated_change_pct': round(da.get('difficultyChange', 0), 2),
            'remaining_blocks': da.get('remainingBlocks', 0),
            'estimated_retarget_date': da.get('estimatedRetargetDate', 0),
        }

    # 全网算力历史趋势（40天，对BTC矿工收益至关重要）
    # mempool.space提供3个月hashrate API
    hr_data = safe_get('https://mempool.space/api/v1/mining/hashrate/3m')
    if hr_data and hr_data.get('hashrates'):
        hashrates = hr_data['hashrates']
        # 取最近40天的每日数据
        recent = hashrates[-40:] if len(hashrates) >= 40 else hashrates
        if recent:
            current_hr = recent[-1].get('avgHashrate', 0) / 1e18  # 转EH/s
            oldest_hr = recent[0].get('avgHashrate', 0) / 1e18
            change_40d = ((current_hr - oldest_hr) / oldest_hr * 100) if oldest_hr > 0 else 0
            # 7天均值
            last7 = recent[-7:] if len(recent) >= 7 else recent
            avg7d_hr = sum(r.get('avgHashrate', 0) for r in last7) / len(last7) / 1e18
            result['hashrate_trend'] = {
                'current_eh': round(current_hr, 1),
                'avg_7d_eh': round(avg7d_hr, 1),
                'change_40d_pct': round(change_40d, 1),
                'data_points': len(recent),
                'trend': 'RISING' if change_40d > 3 else ('FALLING' if change_40d < -3 else 'STABLE'),
            }
            # 保存每日数据点供图表使用
            daily_points = []
            for pt in recent:
                ts = pt.get('timestamp', 0)
                hr_eh = pt.get('avgHashrate', 0) / 1e18
                date_str_pt = datetime.fromtimestamp(ts, tz=BJT).strftime('%m-%d') if ts else ''
                daily_points.append({'date': date_str_pt, 'hashrate_eh': round(hr_eh, 1)})
            result['hashrate_daily'] = daily_points
        # 当前难度
        if hr_data.get('currentDifficulty'):
            result['current_difficulty'] = hr_data['currentDifficulty']

    # 矿工出块收入（blockchain.info，估算日均收入）
    miner_rev = safe_get('https://api.blockchain.info/charts/miners-revenue?timespan=30days&format=json')
    if miner_rev and miner_rev.get('values'):
        vals = miner_rev['values']
        if vals:
            latest = vals[-1].get('y', 0)
            avg30 = sum(v.get('y', 0) for v in vals) / len(vals) if vals else 0
            result['miner_revenue'] = {
                'latest_usd': round(latest),
                'avg_30d_usd': round(avg30),
                'trend': 'UP' if latest > avg30 * 1.05 else ('DOWN' if latest < avg30 * 0.95 else 'FLAT'),
            }

    # Mempool状态
    mp = safe_get('https://mempool.space/api/mempool')
    if mp:
        result['mempool'] = {
            'count': mp.get('count', 0),
            'vsize': mp.get('vsize', 0),
            'total_fee': mp.get('total_fee', 0) / 1e8,  # BTC
        }

    # 最近区块费率
    fees = safe_get('https://mempool.space/api/v1/fees/recommended')
    if fees:
        result['fees'] = {
            'fastest': fees.get('fastestFee', 0),
            'half_hour': fees.get('halfHourFee', 0),
            'hour': fees.get('hourFee', 0),
            'economy': fees.get('economyFee', 0),
        }

    return result


def collect_derivatives_funding():
    """Step 4: 衍生品-资金费率三所对比"""
    print('[4/10] 衍生品-资金费率...')
    result = {'binance': {}, 'okx': {}, 'bybit': {}}
    top_coins = ['BTC', 'ETH']

    # Binance — 全量资金费率
    bn = safe_get('https://fapi.binance.com/fapi/v1/premiumIndex')
    if bn:
        bn_map = {}
        for item in bn:
            sym = item.get('symbol', '')
            rate = safe_float(item.get('lastFundingRate'))
            bn_map[sym] = rate
        # 提取Top coins
        for coin in top_coins:
            sym = f'{coin}USDT'
            if sym in bn_map:
                result['binance'][coin] = bn_map[sym]
        # 全市场统计
        all_rates = [v for v in bn_map.values() if v != 0]
        if all_rates:
            result['binance_stats'] = {
                'total_pairs': len(all_rates),
                'avg_rate': sum(all_rates) / len(all_rates),
                'median_rate': sorted(all_rates)[len(all_rates)//2],
                'positive_pct': len([r for r in all_rates if r > 0]) / len(all_rates) * 100,
                'max_rate_symbol': max(bn_map, key=bn_map.get),
                'max_rate': max(all_rates),
                'min_rate_symbol': min(bn_map, key=bn_map.get),
                'min_rate': min(all_rates),
            }

    # OKX — 主要币种资金费率
    for coin in top_coins:
        okx = safe_get(f'https://www.okx.com/api/v5/public/funding-rate?instId={coin}-USDT-SWAP')
        if okx and okx.get('data'):
            d = okx['data'][0]
            result['okx'][coin] = {
                'current': safe_float(d.get('fundingRate')),
                'next': safe_float(d.get('nextFundingRate')),
            }
        time.sleep(0.15)

    # Bybit — 主要币种
    bybit = safe_get('https://api.bybit.com/v5/market/tickers?category=linear')
    if bybit and bybit.get('result', {}).get('list'):
        for item in bybit['result']['list']:
            sym = item.get('symbol', '')
            for coin in top_coins:
                if sym == f'{coin}USDT':
                    result['bybit'][coin] = {
                        'funding_rate': safe_float(item.get('fundingRate')),
                        'open_interest': safe_float(item.get('openInterest')),
                        'volume_24h': safe_float(item.get('volume24h')),
                    }

    return result


def collect_derivatives_oi_ls():
    """Step 5: 衍生品-持仓与多空比"""
    print('[5/10] 持仓与多空比...')
    result = {}

    # Binance BTC OI
    oi = safe_get('https://fapi.binance.com/fapi/v1/openInterest?symbol=BTCUSDT')
    if oi:
        result['btc_oi_binance'] = safe_float(oi.get('openInterest'))

    # Binance 全局多空比
    ls = safe_get('https://fapi.binance.com/futures/data/globalLongShortAccountRatio?symbol=BTCUSDT&period=1h&limit=12')
    if ls:
        result['btc_ls_history'] = [
            {'time': item['timestamp'], 'long': safe_float(item.get('longAccount')),
             'short': safe_float(item.get('shortAccount')), 'ratio': safe_float(item.get('longShortRatio'))}
            for item in ls
        ]

    # Binance Taker买卖比
    taker = safe_get('https://fapi.binance.com/futures/data/takerlongshortRatio?symbol=BTCUSDT&period=1h&limit=12')
    if taker:
        result['btc_taker_history'] = [
            {'time': item['timestamp'], 'buy_vol': safe_float(item.get('buyVol')),
             'sell_vol': safe_float(item.get('sellVol')), 'ratio': safe_float(item.get('buySellRatio'))}
            for item in taker
        ]

    # ETH OI + L/S
    oi_eth = safe_get('https://fapi.binance.com/fapi/v1/openInterest?symbol=ETHUSDT')
    if oi_eth:
        result['eth_oi_binance'] = safe_float(oi_eth.get('openInterest'))

    ls_eth = safe_get('https://fapi.binance.com/futures/data/globalLongShortAccountRatio?symbol=ETHUSDT&period=1h&limit=3')
    if ls_eth:
        latest = ls_eth[0]
        result['eth_ls_latest'] = {'long': safe_float(latest.get('longAccount')), 'short': safe_float(latest.get('shortAccount')),
                                   'ratio': safe_float(latest.get('longShortRatio'))}

    # OKX BTC多空比
    okx_ls = safe_get('https://www.okx.com/api/v5/rubik/stat/contracts/long-short-account-ratio?ccy=BTC&period=1H')
    if okx_ls and okx_ls.get('data'):
        # 最近3条
        result['okx_btc_ls'] = [
            {'time': item[0], 'ratio': safe_float(item[1])} for item in okx_ls['data'][:3]
        ]

    # Bybit BTC多空比
    bybit_ls = safe_get('https://api.bybit.com/v5/market/account-ratio?category=linear&symbol=BTCUSDT&period=1h&limit=3')
    if bybit_ls and bybit_ls.get('result', {}).get('list'):
        result['bybit_btc_ls'] = [
            {'time': item['timestamp'], 'buy': safe_float(item.get('buyRatio')), 'sell': safe_float(item.get('sellRatio'))}
            for item in bybit_ls['result']['list']
        ]

    return result


def collect_options_market():
    """Step 6: 期权市场 — Deribit"""
    print('[6/10] 期权市场...')
    result = {}

    # BTC期权全量
    opts = safe_get('https://www.deribit.com/api/v2/public/get_book_summary_by_currency?currency=BTC&kind=option')
    if opts and opts.get('result'):
        items = opts['result']
        total_oi = sum(item.get('open_interest', 0) for item in items)
        total_vol = sum(item.get('volume', 0) for item in items)

        # Put/Call分离
        put_oi = sum(item.get('open_interest', 0) for item in items if item.get('instrument_name', '').endswith('-P'))
        call_oi = sum(item.get('open_interest', 0) for item in items if item.get('instrument_name', '').endswith('-C'))
        pc_ratio = round(put_oi / call_oi, 3) if call_oi > 0 else 0

        result['btc_options'] = {
            'total_oi_btc': round(total_oi, 1),
            'total_volume_24h_btc': round(total_vol, 1),
            'put_oi': round(put_oi, 1),
            'call_oi': round(call_oi, 1),
            'put_call_ratio': pc_ratio,
            'total_instruments': len(items),
        }

        # 计算Max Pain（最近到期日）
        # 按到期日分组
        expiry_map = {}
        for item in items:
            name = item.get('instrument_name', '')
            parts = name.split('-')
            if len(parts) >= 4:
                expiry = parts[1]
                strike = int(parts[2]) if parts[2].isdigit() else 0
                oi = item.get('open_interest', 0)
                is_put = parts[3] == 'P'
                if expiry not in expiry_map:
                    expiry_map[expiry] = []
                expiry_map[expiry].append({'strike': strike, 'oi': oi, 'is_put': is_put})

        # 找最近到期日
        if expiry_map:
            # Sort expiry dates
            sorted_expiries = sorted(expiry_map.keys())
            nearest = sorted_expiries[0] if sorted_expiries else None
            if nearest and expiry_map[nearest]:
                strikes_data = expiry_map[nearest]
                all_strikes = sorted(set(s['strike'] for s in strikes_data if s['strike'] > 0))
                if all_strikes:
                    # Max Pain = strike where total pain (loss to option holders) is maximum for writers
                    # = strike where total intrinsic value of all options is minimum
                    min_pain = float('inf')
                    max_pain_strike = 0
                    for test_strike in all_strikes:
                        total_pain = 0
                        for s in strikes_data:
                            if s['is_put']:
                                pain = max(s['strike'] - test_strike, 0) * s['oi']
                            else:
                                pain = max(test_strike - s['strike'], 0) * s['oi']
                            total_pain += pain
                        if total_pain < min_pain:
                            min_pain = total_pain
                            max_pain_strike = test_strike
                    result['max_pain'] = {
                        'nearest_expiry': nearest,
                        'strike': max_pain_strike,
                        'total_oi_at_expiry': sum(s['oi'] for s in strikes_data),
                    }

    # DVOL（隐含波动率指数）
    now_ms = int(time.time() * 1000)
    start_ms = now_ms - 7 * 86400 * 1000
    dvol = safe_get(f'https://www.deribit.com/api/v2/public/get_volatility_index_data?currency=BTC&resolution=3600&start_timestamp={start_ms}&end_timestamp={now_ms}')
    if dvol and dvol.get('result', {}).get('data'):
        data = dvol['result']['data']
        if data:
            latest = data[-1]
            result['dvol'] = {
                'current': round(latest[1], 2) if len(latest) > 1 else 0,  # close
                'high_7d': round(max(d[2] for d in data if len(d) > 2), 2),
                'low_7d': round(min(d[3] for d in data if len(d) > 3), 2),
            }

    # 历史波动率
    hv = safe_get('https://www.deribit.com/api/v2/public/get_historical_volatility?currency=BTC')
    if hv and hv.get('result'):
        vals = hv['result']
        if vals:
            result['historical_vol'] = round(vals[-1][1], 2) if len(vals[-1]) > 1 else 0

    # ETH期权
    eth_opts = safe_get('https://www.deribit.com/api/v2/public/get_book_summary_by_currency?currency=ETH&kind=option')
    if eth_opts and eth_opts.get('result'):
        items = eth_opts['result']
        put_oi = sum(item.get('open_interest', 0) for item in items if item.get('instrument_name', '').endswith('-P'))
        call_oi = sum(item.get('open_interest', 0) for item in items if item.get('instrument_name', '').endswith('-C'))
        result['eth_options'] = {
            'total_oi': round(sum(item.get('open_interest', 0) for item in items), 1),
            'put_call_ratio': round(put_oi / call_oi, 3) if call_oi > 0 else 0,
        }

    return result


def collect_defi():
    """Step 7: DeFi生态 — DefiLlama"""
    print('[7/10] DeFi生态...')
    result = {}

    # 总TVL
    tvl = safe_get('https://api.llama.fi/v2/historicalChainTvl')
    if tvl:
        # 最近30天
        recent = tvl[-30:] if len(tvl) > 30 else tvl
        if recent:
            result['tvl_current'] = recent[-1].get('tvl', 0)
            result['tvl_7d_ago'] = recent[-7].get('tvl', 0) if len(recent) >= 7 else 0
            result['tvl_30d_ago'] = recent[0].get('tvl', 0)
            if result['tvl_7d_ago'] > 0:
                result['tvl_7d_change_pct'] = round((result['tvl_current'] - result['tvl_7d_ago']) / result['tvl_7d_ago'] * 100, 2)

    # 各链TVL
    chains = safe_get('https://api.llama.fi/v2/chains')
    if chains:
        # Top 10 by TVL
        sorted_chains = sorted(chains, key=lambda x: x.get('tvl', 0), reverse=True)[:10]
        result['top_chains'] = [
            {'name': c.get('name', ''), 'tvl': c.get('tvl', 0)} for c in sorted_chains
        ]

    # DEX成交量
    dex = safe_get('https://api.llama.fi/overview/dexs?excludeTotalDataChart=true&excludeTotalDataChartBreakdown=true&dataType=dailyVolume')
    if dex:
        result['dex_total_volume'] = dex.get('totalDataChart', [[0, 0]])[-1][1] if dex.get('totalDataChart') else 0
        result['dex_change_1d'] = dex.get('change_1d', 0)
        # Top DEXes
        protocols = dex.get('protocols', [])
        sorted_dex = sorted(protocols, key=lambda x: x.get('dailyVolume', 0) or 0, reverse=True)[:5]
        result['top_dexes'] = [
            {'name': d.get('name', ''), 'volume': d.get('dailyVolume', 0) or 0,
             'change_1d': d.get('change_1d', 0) or 0}
            for d in sorted_dex
        ]

    # 稳定币
    stables = safe_get('https://stablecoins.llama.fi/stablecoins?includePrices=true')
    if stables and stables.get('peggedAssets'):
        assets = stables['peggedAssets']
        top = sorted(assets, key=lambda x: x.get('circulating', {}).get('peggedUSD', 0) or 0, reverse=True)[:5]
        result['stablecoins'] = []
        for s in top:
            circ = s.get('circulating', {}).get('peggedUSD', 0) or 0
            result['stablecoins'].append({
                'name': s.get('name', ''),
                'symbol': s.get('symbol', ''),
                'circulating': circ,
            })
        result['total_stablecoin_mcap'] = sum(
            s.get('circulating', {}).get('peggedUSD', 0) or 0 for s in assets
        )

    # Derivatives DEX volume
    derivs = safe_get('https://api.llama.fi/overview/derivatives?excludeTotalDataChart=true&excludeTotalDataChartBreakdown=true')
    if derivs:
        result['derivatives_dex_volume'] = derivs.get('totalDataChart', [[0, 0]])[-1][1] if derivs.get('totalDataChart') else 0
        protocols = derivs.get('protocols', [])
        sorted_d = sorted(protocols, key=lambda x: x.get('dailyVolume', 0) or 0, reverse=True)[:3]
        result['top_deriv_dexes'] = [
            {'name': d.get('name', ''), 'volume': d.get('dailyVolume', 0) or 0}
            for d in sorted_d
        ]

    return result


def collect_macro():
    """Step 8: 宏观关联 — Yahoo Finance"""
    print('[8/10] 宏观关联...')
    result = {}
    symbols = {
        'DXY': 'DX-Y.NYB',
        'Gold': 'GC=F',
        'SP500': '%5EGSPC',
        'Nasdaq': '%5EIXIC',
        'US10Y': '%5ETNX',
        'BTC_Yahoo': 'BTC-USD',
    }

    for name, sym in symbols.items():
        data = safe_get(f'https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&range=30d')
        if data and data.get('chart', {}).get('result'):
            r = data['chart']['result'][0]
            meta = r.get('meta', {})
            closes = r.get('indicators', {}).get('quote', [{}])[0].get('close', [])
            closes = [c for c in closes if c is not None]
            if closes:
                current = closes[-1]
                prev = closes[-2] if len(closes) > 1 else current
                change_1d = (current - prev) / prev * 100 if prev != 0 else 0
                # 30天变化
                first = closes[0] if closes else current
                change_30d = (current - first) / first * 100 if first != 0 else 0
                result[name] = {
                    'price': round(current, 2),
                    'change_1d': round(change_1d, 2),
                    'change_30d': round(change_30d, 2),
                    'high_30d': round(max(closes), 2),
                    'low_30d': round(min(closes), 2),
                }

                # BTC与宏观资产的简单30天相关性
                if name == 'BTC_Yahoo':
                    result['btc_closes_30d'] = closes

        time.sleep(0.3)

    # 计算BTC与其他资产的简化相关性
    btc_closes = result.get('btc_closes_30d', [])
    if btc_closes and len(btc_closes) > 5:
        # 简化：用价格变动方向的一致性作为相关性代理
        for name in ['SP500', 'Gold', 'DXY']:
            if name in result:
                # 通过Yahoo Finance拿到的closes长度可能不同，跳过精确相关性计算
                pass

    if 'btc_closes_30d' in result:
        del result['btc_closes_30d']

    return result


def collect_sentiment():
    """Step 9: 情绪指标 — Fear & Greed + Santiment"""
    print('[9/10] 情绪指标...')
    result = {}

    # Fear & Greed Index
    fng = safe_get('https://api.alternative.me/fng/?limit=30&format=json')
    if fng and fng.get('data'):
        data = fng['data']
        result['fear_greed'] = {
            'value': int(data[0].get('value', 0)),
            'classification': data[0].get('value_classification', ''),
            'yesterday': int(data[1].get('value', 0)) if len(data) > 1 else 0,
            'last_week': int(data[6].get('value', 0)) if len(data) > 6 else 0,
            'last_month': int(data[29].get('value', 0)) if len(data) > 29 else 0,
        }
        # 30天趋势
        result['fng_trend'] = [int(d.get('value', 0)) for d in data]

    # Santiment — 活跃地址（免费实时）
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime('%Y-%m-%dT00:00:00Z')
    today = datetime.now(timezone.utc).strftime('%Y-%m-%dT00:00:00Z')
    query = f'{{"query": "{{ getMetric(metric: \\"active_addresses_24h\\") {{ timeseriesData(slug: \\"bitcoin\\", from: \\"{yesterday}\\", to: \\"{today}\\", interval: \\"1d\\") {{ datetime value }} }} }}"}}'
    sant = safe_post('https://api.santiment.net/graphql', json.loads(query))
    if sant and sant.get('data', {}).get('getMetric', {}).get('timeseriesData'):
        ts = sant['data']['getMetric']['timeseriesData']
        if ts:
            result['santiment_active_addresses'] = int(ts[-1].get('value', 0))

    return result


# ============================================================
# 历史数据采集（供ECharts图表使用）
# ============================================================

def collect_historical_charts():
    """采集历史趋势数据，供ECharts渲染时序图表"""
    print('\n[图表数据] 采集历史趋势...')
    result = {}

    # 1. 90天难度调整历史（mempool.space）
    da_hist = safe_get('https://mempool.space/api/v1/mining/difficulty-adjustments/90', timeout=15)
    if da_hist and isinstance(da_hist, list) and len(da_hist) > 0:
        points = []
        for adj in da_hist[:30]:  # 最近30次调整
            ts = adj.get('time', 0)
            diff_change = adj.get('difficultyChange', 0)
            difficulty = adj.get('difficulty', 0)
            date_str = datetime.fromtimestamp(ts, tz=BJT).strftime('%m-%d') if ts else ''
            points.append({
                'date': date_str,
                'change_pct': round(diff_change, 2),
                'difficulty_t': round(difficulty / 1e12, 2) if difficulty else 0,
            })
        points.reverse()  # 时间正序
        result['difficulty_history'] = points
        print(f'  [难度调整] {len(points)}个数据点')
    else:
        # fallback: 尝试不带参数的API
        da_hist2 = safe_get('https://mempool.space/api/v1/mining/difficulty-adjustments', timeout=15)
        if da_hist2 and isinstance(da_hist2, list):
            points = []
            for adj in da_hist2[:20]:
                ts = adj.get('time', 0)
                diff_change = adj.get('difficultyChange', 0)
                difficulty = adj.get('difficulty', 0)
                date_str = datetime.fromtimestamp(ts, tz=BJT).strftime('%m-%d') if ts else ''
                points.append({
                    'date': date_str,
                    'change_pct': round(diff_change, 2),
                    'difficulty_t': round(difficulty / 1e12, 2) if difficulty else 0,
                })
            points.reverse()
            result['difficulty_history'] = points
            print(f'  [难度调整fallback] {len(points)}个数据点')
        else:
            print('  [难度调整] 数据获取失败')

    time.sleep(1)

    # 2. 40天BTC价格趋势（CoinGecko）
    btc_chart = safe_get('https://api.coingecko.com/api/v3/coins/bitcoin/market_chart?vs_currency=usd&days=40&interval=daily', timeout=15)
    if btc_chart and btc_chart.get('prices'):
        points = []
        for p in btc_chart['prices']:
            ts_ms = p[0]
            price = p[1]
            date_str = datetime.fromtimestamp(ts_ms / 1000, tz=BJT).strftime('%m-%d')
            points.append({'date': date_str, 'price': round(price, 0)})
        result['btc_price_history'] = points
        print(f'  [BTC价格] {len(points)}个数据点')
    else:
        print('  [BTC价格] 数据获取失败')

    time.sleep(1.5)  # CoinGecko rate limit

    # 3. 30天矿工收入趋势（Blockchain.info）
    rev_chart = safe_get('https://api.blockchain.info/charts/miners-revenue?timespan=30days&format=json&sampled=true', timeout=15)
    if rev_chart and rev_chart.get('values'):
        points = []
        for v in rev_chart['values']:
            ts = v.get('x', 0)
            revenue = v.get('y', 0)
            date_str = datetime.fromtimestamp(ts, tz=BJT).strftime('%m-%d') if ts else ''
            points.append({'date': date_str, 'revenue_usd': round(revenue, 0)})
        result['miner_revenue_history'] = points
        print(f'  [矿工收入] {len(points)}个数据点')
    else:
        print('  [矿工收入] 数据获取失败')

    return result


def collect_news():
    """Step 10: 新闻快讯 — 6大数据源聚合
    1. BlockBeats 快讯（中文，链上动态+项目资讯）
    2. BlockBeats 深度文章（中文，项目深度分析）
    3. CryptoCompare 聚合新闻（英文，50+源聚合，项目动态）
    4. CoinDesk RSS（英文，主流加密媒体）
    5. CoinTelegraph RSS（英文，主流加密媒体）
    6. OKX 公告（中文，上币/活动/项目资讯——董事长特别要求）
    """
    print('[10/10] 新闻快讯（6源聚合）...')
    all_news = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    seen_titles = set()  # 去重

    FINANCE_KW = re.compile(
        r'BTC|ETH|SOL|比特币|以太坊|Bitcoin|Ethereum|Solana|Layer.?2|DeFi|NFT|DEX|CEX|'
        r'稳定币|stablecoin|USDT|USDC|矿工|挖矿|hash.?rate|'
        r'SEC|CFTC|监管|regulation|ETF|清算|liquidat|爆仓|'
        r'融资|投资|fund|invest|IPO|估值|valuation|收购|acqui|'
        r'Fed|美联储|利率|CPI|GDP|非农|PMI|降息|加息|'
        r'Binance|OKX|Coinbase|Bybit|Bitfinex|Kraken|'
        r'Uniswap|Aave|Lido|MakerDAO|Compound|Curve|'
        r'钱包|wallet|链上|on.?chain|Gas|MEV|'
        r'牛市|熊市|bull|bear|多头|空头|long|short|'
        r'上线|listing|delist|空投|airdrop|主网|mainnet|测试网|testnet|'
        r'升级|upgrade|分叉|fork|合并|merge|burn|销毁|'
        r'partnership|合作|生态|ecosystem|grant|黑客|hack|漏洞|'
        r'Telegram|TON|SUI|APT|ARB|OP|MATIC|DOGE|SHIB|PEPE|'
        r'RWA|PayFi|AI|Meme|GameFi|SocialFi|Restaking|LRT',
        re.IGNORECASE
    )

    def _add_news(title, desc, source, ts=None):
        """去重添加新闻"""
        if not title:
            return
        # 标题去重（忽略标点和空格）
        key = re.sub(r'[\s\W]+', '', title.lower())[:50]
        if key in seen_titles:
            return
        seen_titles.add(key)
        all_news.append({'title': title.strip(), 'desc': (desc or '')[:200].strip(), 'source': source, 'ts': ts})

    def _parse_rss(url, source_name, apply_filter=True):
        """通用RSS解析"""
        count = 0
        try:
            req = Request(url, headers=UA)
            raw = urlopen(req, timeout=15).read()
            root = ET.fromstring(raw)
            for item in root.findall('.//item'):
                title = (item.findtext('title') or '').strip()
                desc = (item.findtext('description') or '').strip()
                pub = item.findtext('pubDate') or ''
                if not title:
                    continue
                # 时间过滤
                ts = None
                try:
                    dt = parsedate_to_datetime(pub)
                    if dt < cutoff:
                        continue
                    ts = dt.timestamp()
                except:
                    pass
                # 金融相关性过滤（可选）
                if apply_filter:
                    text = f'{title} {desc}'
                    if not FINANCE_KW.search(text):
                        continue
                # 清理HTML标签
                desc_clean = re.sub(r'<[^>]+>', '', desc)
                _add_news(title, desc_clean, source_name, ts)
                count += 1
        except Exception as e:
            print(f'  [{source_name}] {e}')
        return count

    # === 数据源 1: BlockBeats 快讯 ===
    n1 = _parse_rss('https://api.theblockbeats.news/v2/rss/newsflash', 'BlockBeats快讯')
    print(f'  [BlockBeats快讯] {n1}条')

    # === 数据源 2: BlockBeats 深度文章 ===
    n2 = _parse_rss('https://api.theblockbeats.news/v2/rss/article', 'BlockBeats深度')
    print(f'  [BlockBeats深度] {n2}条')

    # === 数据源 3: CryptoCompare 聚合新闻（JSON API，50+源聚合） ===
    n3 = 0
    try:
        cc_url = 'https://min-api.cryptocompare.com/data/v2/news/?lang=EN&sortOrder=latest'
        cc_data = safe_get(cc_url, timeout=15)
        if cc_data and cc_data.get('Data'):
            for article in cc_data['Data']:
                title = article.get('title', '').strip()
                body = article.get('body', '')[:200].strip()
                pub_ts = article.get('published_on', 0)
                source_name = article.get('source_info', {}).get('name', 'CryptoCompare')
                if pub_ts and pub_ts < cutoff.timestamp():
                    continue
                text = f'{title} {body}'
                if not FINANCE_KW.search(text):
                    continue
                _add_news(title, body, f'CC/{source_name}', pub_ts)
                n3 += 1
    except Exception as e:
        print(f'  [CryptoCompare] {e}')
    print(f'  [CryptoCompare] {n3}条')

    # === 数据源 4: CoinDesk RSS ===
    n4 = _parse_rss('https://www.coindesk.com/arc/outboundfeeds/rss/?outputType=xml', 'CoinDesk', apply_filter=False)
    print(f'  [CoinDesk] {n4}条')

    # === 数据源 5: CoinTelegraph RSS ===
    n5 = _parse_rss('https://cointelegraph.com/rss', 'CoinTelegraph', apply_filter=False)
    print(f'  [CoinTelegraph] {n5}条')

    # === 数据源 6: OKX公告（董事长特别要求的项目资讯） ===
    n6 = 0
    try:
        # OKX公告API — 新币上线、活动、项目动态
        okx_url = 'https://www.okx.com/api/v5/support/announcements?page=1'
        okx_data = safe_get(okx_url, timeout=15)
        if okx_data and okx_data.get('data'):
            for ann in okx_data['data']:
                title = ann.get('title', '').strip()
                # OKX API可能返回pTime（毫秒时间戳）
                p_time = ann.get('pTime', '') or ann.get('publishTime', '')
                ts = None
                if p_time:
                    try:
                        ts_ms = int(p_time)
                        ts = ts_ms / 1000 if ts_ms > 1e12 else float(ts_ms)
                        if ts < cutoff.timestamp():
                            continue
                    except:
                        pass
                _add_news(title, '', 'OKX公告', ts)
                n6 += 1
    except Exception as e:
        print(f'  [OKX公告] {e}')
    # OKX公告备选：爬取公告页面（如API不可用）
    if n6 == 0:
        try:
            okx_url2 = 'https://www.okx.com/api/v5/public/announcements?page=1'
            okx_data2 = safe_get(okx_url2, timeout=10)
            if okx_data2 and okx_data2.get('data'):
                for ann in okx_data2['data']:
                    title = ann.get('title', '').strip()
                    _add_news(title, '', 'OKX公告')
                    n6 += 1
        except:
            pass
    print(f'  [OKX公告] {n6}条')

    # === 汇总与排序 ===
    # 按时间戳倒序（最新的在前），无时间戳的排最后
    all_news.sort(key=lambda x: x.get('ts') or 0, reverse=True)
    total = len(all_news)
    print(f'  [汇总] 共{total}条新闻（去重后），取前60条')

    return all_news[:60]


# ============================================================
# 新闻分级系统（Python代码分级，无需LLM）
# ============================================================

# 来源可信度分级
SOURCE_TIER = {
    'CoinDesk': 'T1', 'CoinTelegraph': 'T1', 'BlockBeats深度': 'T1',
    'BlockBeats快讯': 'T2', 'OKX公告': 'T2',
    # CryptoCompare子源默认T3
}

# 重要性分级关键词
RED_KEYWORDS = re.compile(
    r'SEC|ETF|ban|禁止|hack|被黑|halving|减半|all.?time.?high|历史新高|'
    r'approved|批准|crash|崩盘|regulation|监管|Fed|美联储|降息|加息|'
    r'清算|liquidat|爆仓|关停|shutdown|破产|bankrupt|'
    r'Tether|USDT脱锚|稳定币危机|央行|CBDC|'
    r'Mt\.?Gox|Silk.?Road|制裁|sanctions',
    re.IGNORECASE
)

YELLOW_KEYWORDS = re.compile(
    r'mining|矿|hashrate|算力|difficulty|难度|'
    r'institutional|机构|MicroStrategy|BlackRock|Grayscale|Fidelity|'
    r'funding|融资|IPO|上市|收购|acqui|merger|'
    r'upgrade|升级|fork|分叉|mainnet|主网|'
    r'whale|巨鲸|大额|转账|ETH|Ethereum|'
    r'staking|质押|DeFi|TVL|稳定币|stablecoin',
    re.IGNORECASE
)


def classify_news(news_list):
    """对新闻列表进行重要性分级和来源可信度标注

    Returns: 原始列表，每条新闻增加 level (RED/YELLOW/GREEN) 和 tier (T1/T2/T3) 字段
    """
    for item in news_list:
        text = f"{item.get('title', '')} {item.get('desc', '')}"
        source = item.get('source', '')

        # 来源可信度
        tier = SOURCE_TIER.get(source, 'T3')
        # CryptoCompare子源检查
        if source.startswith('CC/'):
            sub = source[3:]
            tier = SOURCE_TIER.get(sub, 'T3')
        item['tier'] = tier

        # 重要性分级
        if RED_KEYWORDS.search(text):
            item['level'] = 'RED'
        elif YELLOW_KEYWORDS.search(text):
            item['level'] = 'YELLOW'
        else:
            item['level'] = 'GREEN'

    return news_list


# ============================================================
# Claude分析
# ============================================================

CRYPTO_ANALYST_SYSTEM = """你是一位专门服务BTC矿场董事长的首席加密货币分析师。

## 董事长背景
- 经营大型BTC ASIC矿场（F2Pool 26+子账户，多地机房）
- 同时持有ETH仓位
- 关心：BTC价格对挖矿利润的影响、算力/难度对产出的影响、矿工经营周期、能源成本盈亏平衡
- 阅读设备：笔记本电脑或iPad，不限篇幅

## 时间规范（最高优先级）
- 所有时间引用必须使用**北京时间（BJT/UTC+8）**
- "今日"、"昨日"、"本周"均以北京时间为基准
- 数据中提供的采集时间就是报告基准时间
- 不要用UTC时间，不要用"过去24小时"这种模糊说法，要用"北京时间3月6日08:00的数据显示..."
- 价格和涨跌幅要与采集时间点一致，不要自行推断其他时间点的价格

## 你的分析方法论

### 核心矛盾法
每天的市场只有1-2个真正的核心矛盾。找到它们，围绕它们展开所有分析。
例如："链上数据显示长期持有者在加速出货，但ETF资金持续流入——核心矛盾是机构接盘速度能否消化老筹码抛压"

### 因果链推演（必须做）
事件 → 传导机制 → 一阶效应 → 二阶效应 → 对矿场经营的影响
不要只说"X发生了"，要推演"X发生了 → 因为Y机制 → 导致Z → 对矿场意味着..."

### 历史类比（必须给出）
当前市场形态让你想到历史上哪个阶段？给出具体日期、具体数据对比、当时的后续走势。
例如："当前Puell Multiple 0.68接近2023年1月的0.65水平，当时BTC在$16,500筑底，随后6个月涨至$31,000（+88%），矿工收入回升至日均$2500万"

### 矿工经济学解读（核心竞争力，最重要）
- Puell Multiple：<0.5极度低估（矿工投降区域），0.5-1.0低估，1.0-4.0正常，>4.0过热（矿工收入远超历史均值）
- 全网算力趋势：算力↑→竞争加剧→单位产出↓→小矿工关机→难度下调→大矿工受益
- 难度调整周期：每2016个区块（约14天），影响每TH/s的BTC产出
- 矿工收入 = 区块奖励(3.125 BTC/块) + 交易费。Mempool拥堵时交易费可达区块奖励20%+
- 盈亏平衡分析：电费0.35元/度，S19 XP效率21.5 J/TH → 关机价约$XX,XXX
- NVT Ratio：<50网络被低估，50-120正常，>120过热
- 活跃地址趋势：与价格背离时是强信号

### 衍生品市场解读（领先指标）
- 资金费率：三所对比找分歧，全市场正费率占比反映整体偏多/偏空
- 多空比变化方向比绝对值更重要
- OI变化 + 价格方向：OI增+价涨=新多开仓（强），OI减+价涨=空头平仓（弱）
- 期权市场：Put/Call >1 = 对冲需求增加，DVOL上升 = 市场预期波动加大
- Max Pain：大到期日前价格有向Max Pain回归的引力

### 宏观关联（必须分析）
- DXY与BTC通常负相关，DXY走强压制风险资产
- 美债收益率上升 = 无风险回报上升 = 资金从加密流出
- 黄金与BTC的关联度近年上升，"数字黄金"叙事验证
- 稳定币总市值增减 = 加密市场资金池涨缩

## 禁止用词（最高优先级）
以下词汇绝对禁止出现在报告中：
暴涨、暴跌、飙升、狂跌、震撼、惊人、强势、弱势、博弈、剧烈、疯狂、恐慌性、
史诗级、创纪录、里程碑式、颠覆性、革命性、划时代
禁止使用主观置信度表述："中等置信度看涨"、"高概率上涨"、"大概率下跌"
替代方式——用数据说话：
错误："中等置信度看涨BTC"
正确："基于NVT 48（低于50阈值）+ Puell 0.72（低估区间）+ 资金费率三所均为正，BTC当前处于历史低估区间，形态类似2023年1月（当时$16,500，6个月后+88%）"
所有判断必须有数据支撑和历史类比，不说空话。

## 铁律
1. 不说"建议关注"、"值得关注" — 要说"应该做什么"
2. 不说"可能上涨也可能下跌" — 要给方向判断，用数据和历史类比支撑
3. 不说"谨慎观望" — 要说在什么条件下做什么
4. 每个判断必须有：数据依据 + 历史类比（具体日期和价格） + 传导逻辑
5. 信号冲突时用⚡显式标注，分析哪个信号更可靠
6. 风险提示必须具体：不是"注意风险"，而是"如果BTC跌破$XX,XXX，矿场关机价将被触及"
7. 数据必须量化到具体数字，不用"大幅"、"显著"等模糊词
8. 策略建议围绕矿场经营：持币还是卖出挖矿产出？是否该扩算力/买新矿机？电费策略？
9. 每个历史引用必须包含：具体日期 + 具体数据点 + 当时的后续走势
10. 客观描述数据变化，不要用夸张修辞。例如："40天算力从760 EH/s上升至1188 EH/s（+56.3%）"而非"40天算力暴涨+56.3%"

## 输出格式要求（笔记本电脑/iPad大屏幕阅读）
- 用 ## 大标题（不要用###）
- 关键数字全部**加粗**
- 不限段落长度和篇幅，深度分析优先
- 段落间用空行分隔
- 正负面emoji：🔴负面 🟡中性 🟢正面 ⚡冲突
- 可以使用表格（大屏幕显示正常）
- 分隔线 --- 分开大板块"""

CRYPTO_ANALYST_USER = """请基于以下实时数据，撰写今日加密货币投研日报。

要求：
1. 先给出紧凑一行式市场快照（最关键数据一目了然）
2. 找到今日1-2个核心矛盾，围绕矿场经营视角展开分析
3. 深度分析，不是新闻摘要——每个数据点都要解读"对矿场意味着什么"
4. 所有判断给出因果链和历史类比
5. 新闻逐条深度分析（80-150字因果链），不是简单列表
6. 策略建议围绕矿场经营（持币/卖出/扩算力/电费），不涉及自动化交易

## 报告结构

**第一部分：市场快照**（紧凑一行式，放最前面，一屏看完关键数据）
格式如下（每项一行，数据紧凑）：
- BTC: $XX,XXX | 24h +X.X% | 24h区间 $XX,XXX-$XX,XXX | 24h成交额 $XXB
- ETH: $X,XXX | 24h +X.X%
- 恐贪指数: XX (状态) | BTC市占率: XX.X% | 总市值: $X.XXT
- 全网算力: XXX EH/s | 难度调整进度: XX% (预估+X.X%) | 每TH/s日收入: $X.XX
- BTC资金费率: Binance X.XXXX% / OKX X.XXXX% / Bybit X.XXXX%
- Mempool: XX,XXX笔未确认 | Gas: 快速XX sat/vB | Puell: X.XX

**第二部分：核心矛盾与判断**
- 今日1-2个核心矛盾
- 方向判断 + 置信度 + 逻辑链
- 对矿场经营的具体建议：
  - 挖矿产出的BTC应该持有还是卖出？
  - 是否适合扩算力/购买新矿机？
  - 电费策略建议（满负荷/降负荷/关机）
  - ETH持仓策略

**第三部分：矿工经济学**（⚠️ 最重要章节，矿场董事长核心关注）
- 全网算力当前值 vs 7日均值 vs 40天趋势方向（RISING/STABLE/FALLING）
- 算力变化对单位算力BTC产出的影响（算力↑→产出↓→收益承压）
- 下次难度调整预估幅度及对矿工的影响
- 矿工日收入 vs 30天均值，矿工是否在抛售BTC
- Puell Multiple当前位置及其含义（矿工投降/正常/过热）
- Mempool拥堵情况和交易费收入对矿工收入的贡献
- 矿工行为分析：链上数据是否显示矿工在抛售？
- 对矿场经营的具体影响分析

**第四部分：BTC深度分析**
- 链上数据（NVT Ratio、活跃地址趋势、与价格背离信号）
- 衍生品（三所资金费率对比找分歧、全市场费率分布、OI+多空比组合解读、Taker买卖比）
- 期权（Put/Call变化、DVOL vs 历史波动率、Max Pain引力）

**第五部分：ETH分析**（简洁版，作为第二大持仓）
- ETH价格/涨跌幅
- ETH衍生品（费率、期权情绪）
- ETH/BTC相对强弱及含义

**第六部分：宏观环境**
- DXY走势及对BTC的压制/利好
- 美债收益率变化
- 黄金 vs BTC走势对比（"数字黄金"叙事）
- 美股与加密的联动/脱钩

**第七部分：行业动态深度分析**（⚠️ 最重要的深度章节，绝对不能写成简评）
- 从新闻数据中选取最重要的10-15条（RED级全部入选，YELLOW级择优）
- 每条新闻必须按以下5步结构深度分析（总字数不少于150字，越详细越好，不限上限）：

格式：
[T1/T2/T3] 来源名 | 🔴/🟡/🟢 重要性级别
**标题**

① **事件概述**：1-2句话说清楚发生了什么
② **历史先例**：引用一个具体的历史类似事件（必须包含具体日期、具体价格/数据、当时的后续走势）。例如："类似2024年1月SEC批准BTC现货ETF（BTC从$46,000涨至$73,000，+58%）"
③ **因果传导链**：事件 → 传导机制 → 一阶效应 → 二阶效应。例如："CleanSpark出售97%产出 → 矿工抛压增加 → 短期BTC供给增加 → 但这反映矿工需要覆盖运营成本，非恐慌性抛售"
④ **对BTC价格的影响判断**：方向（利好/利空/中性）+ 时间窗口（短期/中期/长期）+ 影响量级
⑤ **对矿场经营的影响**：对算力、难度、电费成本、挖矿收益的具体影响

禁止写少于100字的简评。每条新闻都是一篇微型研究报告。
- 分3类整理：①监管与政策 ②项目与技术进展 ③市场事件

**第八部分：DeFi与稳定币**（简洁版）
- TVL变化方向（资金流入/流出信号）
- 稳定币市值变化（加密市场资金池）
- DEX成交量变化

**第九部分：风险矩阵**
- Top 3风险 + 对矿场的具体影响 + 对冲方案
- Top 3机会 + 入场条件
- **反向观点**（必写）：提出至少一个与你主结论相反的情景，分析在什么条件下你的主判断会被证伪，以及该情景发生的概率和应对方案。这不是"风险提示"，而是严肃的反向论证。

--- 以下是今日实时数据 ---

{data_context}"""


def call_llm_analysis(data_context):
    """调用LLM深度分析（Claude Sonnet直连Anthropic API，备选DeepSeek）"""
    from llm_engine import call_llm
    print('\n调用LLM深度分析（Claude Sonnet → DeepSeek fallback）...')
    user_msg = CRYPTO_ANALYST_USER.replace('{data_context}', data_context)
    return call_llm(
        system_prompt=CRYPTO_ANALYST_SYSTEM,
        user_prompt=user_msg,
        model='sonnet',
        fallback='deepseek',
        max_tokens=12000,
        timeout=240,
    )


# ============================================================
# 数据格式化
# ============================================================

def format_data_context(market, onchain, mining, funding, oi_ls, options, defi, macro, sentiment, news):
    """将所有数据格式化为Claude的输入"""
    sections = []

    # 时间基准 — 明确告知Claude当前北京时间
    now_bjt = datetime.now(BJT)
    s = f'## 时间基准\n'
    s += f'当前北京时间: {now_bjt.strftime("%Y-%m-%d %H:%M")} (BJT/UTC+8)\n'
    s += f'以下所有数据的采集时间均为此刻。所有分析中的时间引用必须使用北京时间。\n'
    s += f'"今日"指的是北京时间{now_bjt.strftime("%Y-%m-%d")}，"昨日"指的是北京时间{(now_bjt - timedelta(days=1)).strftime("%Y-%m-%d")}。\n'
    sections.append(s)

    # 市场总览
    s = '## 市场总览\n'
    if market.get('global'):
        g = market['global']
        s += f"总市值: ${g['total_market_cap_usd']/1e12:.2f}T (24h变化: {g['market_cap_change_24h']:+.2f}%)\n"
        s += f"24h成交量: ${g['total_volume_24h']/1e9:.1f}B\n"
        s += f"BTC市占率: {g['btc_dominance']:.1f}%  ETH市占率: {g['eth_dominance']:.1f}%\n"
    if market.get('prices'):
        s += '\nBTC/ETH行情:\n'
        for coin_id in ['bitcoin', 'ethereum']:
            d = market['prices'].get(coin_id, {})
            if not d:
                continue
            name = 'BTC' if coin_id == 'bitcoin' else 'ETH'
            price = d.get('usd', 0)
            change = d.get('usd_24h_change', 0) or 0
            mcap = d.get('usd_market_cap', 0) or 0
            vol = d.get('usd_24h_vol', 0) or 0
            s += f"  {name}: ${price:,.2f} ({change:+.1f}%) MCap ${mcap/1e9:.1f}B 24h量 ${vol/1e9:.1f}B\n"
    if market.get('btc_extra'):
        e = market['btc_extra']
        s += f"\nBTC ATH: ${e['ath']:,.0f} (距ATH {e['pct_from_ath']:.1f}%)\n"
        s += f"BTC 7d: {e['change_7d']:+.1f}%  30d: {e['change_30d']:+.1f}%\n"
    if market.get('trending'):
        s += '\nCoinGecko热搜Top5: ' + ', '.join(f"{t['symbol']}(#{t['market_cap_rank']})" for t in market['trending'][:5]) + '\n'
    sections.append(s)

    # 链上基本面
    s = '## 链上基本面\n'
    if onchain.get('puell_multiple') is not None:
        pm = onchain['puell_multiple']
        s += f"Puell Multiple: {pm:.4f}"
        if pm < 0.5: s += ' (极度低估区间，历史底部信号)'
        elif pm < 1.0: s += ' (低估区间)'
        elif pm < 4.0: s += ' (正常区间)'
        else: s += ' (过热区间)'
        s += f"\n  今日矿工收入: ${onchain.get('miners_revenue_today', 0):,.0f}  365天均值: ${onchain.get('miners_revenue_365avg', 0):,.0f}\n"
    if onchain.get('nvt_ratio') is not None:
        nvt = onchain['nvt_ratio']
        s += f"NVT Ratio: {nvt:.1f}"
        if nvt < 50: s += ' (网络使用活跃，链上价值被低估)'
        elif nvt < 120: s += ' (正常区间)'
        else: s += ' (投机成分高，链上使用不足)'
        s += f"\n  市值: ${onchain.get('nvt_market_cap', 0)/1e12:.2f}T  日交易量: ${onchain.get('nvt_tx_volume', 0)/1e9:.1f}B\n"
    if onchain.get('active_addresses_today'):
        aa = onchain['active_addresses_today']
        avg7 = onchain.get('active_addresses_7d_avg', 0)
        avg30 = onchain.get('active_addresses_30d_avg', 0)
        s += f"活跃地址: {aa:,} (7d均值: {avg7:,}  30d均值: {avg30:,})\n"
        if aa > avg30 * 1.1: s += '  ↑ 高于30日均值10%+，链上活跃度上升\n'
        elif aa < avg30 * 0.9: s += '  ↓ 低于30日均值10%+，链上活跃度下降\n'
    if onchain.get('stats'):
        st = onchain['stats']
        s += f"24h交易数: {st['n_tx_24h']:,}  24h区块数: {st['n_blocks_mined_24h']}\n"
        s += f"算力: {st['hash_rate']/1e6:.0f} EH/s  难度: {st['difficulty']/1e12:.2f}T\n"
    sections.append(s)

    # 挖矿与难度（对BTC矿工至关重要）
    s = '## 挖矿经济学（⚠️ 矿工核心关注）\n'
    if mining.get('hashrate_trend'):
        hr = mining['hashrate_trend']
        s += f"**全网算力**: {hr['current_eh']} EH/s (7d均值: {hr['avg_7d_eh']} EH/s)\n"
        s += f"**40天算力变化**: {hr['change_40d_pct']:+.1f}% ({hr['trend']})\n"
        if hr['trend'] == 'RISING':
            s += "  ↑ 算力持续上升，矿工竞争加剧，单位算力BTC产出下降\n"
        elif hr['trend'] == 'FALLING':
            s += "  ↓ 算力下降，部分矿工关机，存活矿工产出增加\n"
    if mining.get('current_difficulty'):
        diff = mining['current_difficulty']
        s += f"**当前难度**: {diff/1e12:.2f} T\n"
    if mining.get('difficulty_adjustment'):
        da = mining['difficulty_adjustment']
        s += f"**难度调整进度**: {da['progress_pct']}%  预估下次变化: {da['estimated_change_pct']:+.2f}%\n"
        s += f"  剩余区块: {da['remaining_blocks']}\n"
        if da['estimated_change_pct'] > 5:
            s += "  ⚠️ 预计大幅上调，矿工收益将下降\n"
        elif da['estimated_change_pct'] < -5:
            s += "  ✅ 预计大幅下调，矿工收益将改善\n"
    if mining.get('miner_revenue'):
        mr = mining['miner_revenue']
        s += f"**矿工日收入**: ${mr['latest_usd']:,} (30d均值: ${mr['avg_30d_usd']:,}, {mr['trend']})\n"
    if mining.get('mempool'):
        mp = mining['mempool']
        s += f"Mempool: {mp['count']:,}笔未确认  费用池: {mp['total_fee']:.4f} BTC\n"
    if mining.get('fees'):
        f = mining['fees']
        s += f"推荐费率: 快速{f['fastest']} sat/vB  半小时{f['half_hour']}  经济{f['economy']}\n"
    sections.append(s)

    # 衍生品-资金费率
    s = '## 衍生品-资金费率（三所对比）\n'
    for coin in ['BTC', 'ETH']:
        bn = funding.get('binance', {}).get(coin)
        okx_d = funding.get('okx', {}).get(coin, {})
        okx_r = okx_d.get('current') if isinstance(okx_d, dict) else None
        bybit_d = funding.get('bybit', {}).get(coin, {})
        bybit_r = bybit_d.get('funding_rate') if isinstance(bybit_d, dict) else None
        rates = []
        parts = [f"  {coin}:"]
        if bn is not None:
            parts.append(f"Binance {bn*100:.4f}%")
            rates.append(bn)
        if okx_r is not None:
            parts.append(f"OKX {okx_r*100:.4f}%")
            rates.append(okx_r)
        if bybit_r is not None:
            parts.append(f"Bybit {bybit_r*100:.4f}%")
            rates.append(bybit_r)
        if rates:
            spread = (max(rates) - min(rates)) * 100
            parts.append(f"[价差{spread:.4f}%]")
        s += ' | '.join(parts) + '\n'
    if funding.get('binance_stats'):
        bs = funding['binance_stats']
        s += f"\nBinance全市场({bs['total_pairs']}对):\n"
        s += f"  均值: {bs['avg_rate']*100:.4f}%  中位数: {bs['median_rate']*100:.4f}%\n"
        s += f"  正费率占比: {bs['positive_pct']:.0f}%\n"
        s += f"  最高: {bs['max_rate_symbol']} {bs['max_rate']*100:.4f}%\n"
        s += f"  最低: {bs['min_rate_symbol']} {bs['min_rate']*100:.4f}%\n"
    sections.append(s)

    # 衍生品-OI与多空
    s = '## 衍生品-持仓与多空比\n'
    if oi_ls.get('btc_oi_binance'):
        s += f"BTC OI (Binance): {oi_ls['btc_oi_binance']:,.0f} BTC\n"
    if oi_ls.get('eth_oi_binance'):
        s += f"ETH OI (Binance): {oi_ls['eth_oi_binance']:,.0f} ETH\n"
    if oi_ls.get('btc_ls_history'):
        latest = oi_ls['btc_ls_history'][0]
        s += f"BTC多空比 (Binance): 多{latest['long']*100:.1f}% / 空{latest['short']*100:.1f}% = {latest['ratio']:.2f}\n"
        # 12小时趋势
        if len(oi_ls['btc_ls_history']) >= 6:
            first = oi_ls['btc_ls_history'][-1]
            ratio_change = latest['ratio'] - first['ratio']
            s += f"  12h趋势: {'多头增加' if ratio_change > 0 else '空头增加'} (变化{ratio_change:+.3f})\n"
    if oi_ls.get('btc_taker_history'):
        latest = oi_ls['btc_taker_history'][0]
        s += f"BTC Taker买卖比: {latest['ratio']:.3f} (买{latest['buy_vol']:.0f} / 卖{latest['sell_vol']:.0f})\n"
    if oi_ls.get('okx_btc_ls'):
        latest = oi_ls['okx_btc_ls'][0]
        s += f"BTC多空比 (OKX): {latest['ratio']:.2f}\n"
    if oi_ls.get('bybit_btc_ls'):
        latest = oi_ls['bybit_btc_ls'][0]
        s += f"BTC多空比 (Bybit): 多{latest['buy']*100:.1f}% / 空{latest['sell']*100:.1f}%\n"
    if oi_ls.get('eth_ls_latest'):
        el = oi_ls['eth_ls_latest']
        s += f"ETH多空比 (Binance): 多{el['long']*100:.1f}% / 空{el['short']*100:.1f}% = {el['ratio']:.2f}\n"
    sections.append(s)

    # 期权
    s = '## 期权市场 (Deribit)\n'
    if options.get('btc_options'):
        bo = options['btc_options']
        s += f"BTC期权总OI: {bo['total_oi_btc']:,.0f} BTC ({bo['total_instruments']}个合约)\n"
        s += f"24h成交量: {bo['total_volume_24h_btc']:,.0f} BTC\n"
        s += f"Put/Call OI Ratio: {bo['put_call_ratio']:.3f}"
        if bo['put_call_ratio'] > 1: s += ' (偏空/对冲需求高)'
        elif bo['put_call_ratio'] < 0.7: s += ' (偏多/看涨情绪)'
        else: s += ' (中性偏多)'
        s += '\n'
    if options.get('max_pain'):
        mp = options['max_pain']
        s += f"最近到期日Max Pain: ${mp['strike']:,} (到期日{mp['nearest_expiry']}, OI {mp['total_oi_at_expiry']:,.0f} BTC)\n"
    if options.get('dvol'):
        dv = options['dvol']
        hv = options.get('historical_vol', 0)
        s += f"DVOL(隐含波动率): {dv['current']}% (7d区间: {dv['low_7d']}-{dv['high_7d']}%)\n"
        if hv:
            s += f"历史波动率: {hv}%\n"
            diff = dv['current'] - hv
            s += f"IV-HV价差: {diff:+.2f}%"
            if diff > 5: s += ' (市场预期波动加大)'
            elif diff < -5: s += ' (波动率被低估，可能有突破)'
            s += '\n'
    if options.get('eth_options'):
        eo = options['eth_options']
        s += f"ETH期权OI: {eo['total_oi']:,.0f} ETH  Put/Call: {eo['put_call_ratio']:.3f}\n"
    sections.append(s)

    # DeFi
    s = '## DeFi生态\n'
    if defi.get('tvl_current'):
        s += f"总TVL: ${defi['tvl_current']/1e9:.1f}B"
        if defi.get('tvl_7d_change_pct'):
            s += f" (7d变化: {defi['tvl_7d_change_pct']:+.2f}%)"
        s += '\n'
    if defi.get('top_chains'):
        s += '各链TVL Top5:\n'
        for c in defi['top_chains'][:5]:
            s += f"  {c['name']}: ${c['tvl']/1e9:.2f}B\n"
    if defi.get('dex_total_volume'):
        s += f"\nDEX 24h成交量: ${defi['dex_total_volume']/1e9:.2f}B"
        if defi.get('dex_change_1d'):
            s += f" (日变化: {defi['dex_change_1d']:+.1f}%)"
        s += '\n'
    if defi.get('top_dexes'):
        for d in defi['top_dexes'][:3]:
            s += f"  {d['name']}: ${d['volume']/1e9:.2f}B ({d['change_1d']:+.1f}%)\n"
    if defi.get('total_stablecoin_mcap'):
        s += f"\n稳定币总市值: ${defi['total_stablecoin_mcap']/1e9:.1f}B\n"
    if defi.get('stablecoins'):
        for sc in defi['stablecoins']:
            s += f"  {sc['symbol']}: ${sc['circulating']/1e9:.1f}B\n"
    if defi.get('derivatives_dex_volume'):
        s += f"\n链上衍生品DEX 24h: ${defi['derivatives_dex_volume']/1e9:.2f}B\n"
    sections.append(s)

    # 宏观
    s = '## 宏观关联\n'
    for name, label in [('DXY', '美元指数'), ('US10Y', '美国10年期国债收益率'), ('Gold', '黄金'), ('SP500', '标普500'), ('Nasdaq', '纳斯达克')]:
        if macro.get(name):
            m = macro[name]
            s += f"{label}: {m['price']}"
            if name == 'US10Y':
                s += f"% (日变化{m['change_1d']:+.2f}% 30d变化{m['change_30d']:+.2f}%)\n"
            else:
                s += f" (日{m['change_1d']:+.2f}% 30d{m['change_30d']:+.2f}%  30d区间{m['low_30d']}-{m['high_30d']})\n"
    sections.append(s)

    # 情绪
    s = '## 情绪指标\n'
    if sentiment.get('fear_greed'):
        fg = sentiment['fear_greed']
        s += f"Fear & Greed: {fg['value']} ({fg['classification']})\n"
        s += f"  昨天: {fg['yesterday']}  上周: {fg['last_week']}  上月: {fg['last_month']}\n"
        trend = sentiment.get('fng_trend', [])
        if trend:
            avg = sum(trend) / len(trend)
            s += f"  30天均值: {avg:.0f}  趋势方向: {'上升' if trend[0] > avg else '下降'}\n"
    if sentiment.get('santiment_active_addresses'):
        s += f"Santiment活跃地址: {sentiment['santiment_active_addresses']:,}\n"
    sections.append(s)

    # 新闻（6源聚合，带分级标签，RED优先排序）
    s = '## 最近24h重要新闻（6源聚合，已分级）\n'
    if news:
        # 按重要性排序：RED > YELLOW > GREEN
        level_order = {'RED': 0, 'YELLOW': 1, 'GREEN': 2}
        sorted_news = sorted(news[:60], key=lambda n: level_order.get(n.get('level', 'GREEN'), 2))
        level_emoji = {'RED': '🔴', 'YELLOW': '🟡', 'GREEN': '🟢'}
        red_count = sum(1 for n in sorted_news if n.get('level') == 'RED')
        yellow_count = sum(1 for n in sorted_news if n.get('level') == 'YELLOW')
        green_count = sum(1 for n in sorted_news if n.get('level') == 'GREEN')
        s += f'分级统计: 🔴RED {red_count}条 | 🟡YELLOW {yellow_count}条 | 🟢GREEN {green_count}条\n\n'
        for idx, n in enumerate(sorted_news, 1):
            level = n.get('level', 'GREEN')
            tier = n.get('tier', 'T3')
            emoji = level_emoji.get(level, '🟢')
            source = n.get('source', '未知')
            s += f"{idx}. [{tier}][{emoji}{level}] {source} | {n['title']}\n"
            if n.get('desc'):
                s += f"   {n['desc'][:150]}\n"
    else:
        s += '无重要新闻\n'
    sections.append(s)

    return '\n'.join(sections)


# ============================================================
# 预览HTML生成（含ECharts交互图表）
# ============================================================
PREVIEW_URL = 'https://helloworldoccupied.github.io/news-secretary/'


def generate_preview_html(report_text, market, onchain, mining, funding, options, defi, macro, sentiment, historical=None):
    """生成图文一体化HTML预览 — 图表嵌入对应文字章节中间，不分离"""

    # ===== 提取图表数据 =====
    chart_data = {}

    btc = market.get('prices', {}).get('bitcoin', {})
    if btc:
        chart_data['btc_price'] = btc.get('usd', 0)
        chart_data['btc_change_24h'] = btc.get('usd_24h_change', 0)
    eth = market.get('prices', {}).get('ethereum', {})
    if eth:
        chart_data['eth_price'] = eth.get('usd', 0)
        chart_data['eth_change_24h'] = eth.get('usd_24h_change', 0)

    top_coins = market.get('prices', {})
    coin_changes = {}
    for coin_id, info in top_coins.items():
        if isinstance(info, dict) and info.get('usd_24h_change') is not None:
            name = coin_id.upper()[:5]
            coin_changes[name] = round(float(info.get('usd_24h_change', 0)), 2)
    chart_data['coin_changes'] = dict(sorted(coin_changes.items(), key=lambda x: abs(x[1]), reverse=True)[:10])

    fg = sentiment.get('fear_greed', {})
    if fg:
        chart_data['fear_greed_value'] = int(fg.get('value', 50))
        chart_data['fear_greed_label'] = fg.get('classification', 'Neutral')

    for k in ['DXY', 'Gold', 'US10Y', 'SPX', 'Nasdaq']:
        macro_item = macro.get(k, {})
        if macro_item:
            chart_data[f'macro_{k.lower()}'] = macro_item.get('price', 0)
            chart_data[f'macro_{k.lower()}_change'] = macro_item.get('change_pct', macro_item.get('change_1d', 0))

    # 40天算力+每TH/s收益数据（矿工经济学图表）
    chart_data['hashrate_daily'] = mining.get('hashrate_daily', [])
    chart_data['btc_price_usd'] = chart_data.get('btc_price', 0)

    # 历史趋势数据（3个新图表）
    if historical:
        chart_data['difficulty_history'] = historical.get('difficulty_history', [])
        chart_data['btc_price_history'] = historical.get('btc_price_history', [])
        chart_data['miner_revenue_history'] = historical.get('miner_revenue_history', [])

    # ===== 生成ECharts JS =====
    charts_js = _build_charts_js(chart_data)

    # ===== 按##章节拆分，图表嵌入对应位置 =====
    body_html = _build_interleaved_html(report_text, chart_data)

    # ===== 组装完整HTML =====
    now_bjt = datetime.now(BJT).strftime('%Y-%m-%d %H:%M BJT')
    btc_price = chart_data.get('btc_price', 0)
    fg_val = chart_data.get('fear_greed_value', '?')
    fg_lbl = chart_data.get('fear_greed_label', '')

    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>加密投研日报 v2.0 {TODAY_BJT}</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif; background: #0d1117; color: #e6edf3; line-height: 1.7; }}
.header {{ background: linear-gradient(135deg, #1a1f36 0%, #0d1117 100%); border-bottom: 2px solid #f7931a; padding: 20px; text-align: center; }}
.header h1 {{ font-size: 24px; color: #f7931a; margin-bottom: 8px; }}
.header .meta {{ font-size: 14px; color: #8b949e; }}
.header .price-banner {{ margin-top: 12px; font-size: 18px; }}
.header .price-banner .btc {{ color: #f7931a; font-weight: bold; font-size: 28px; }}
.content {{ max-width: 1100px; margin: 0 auto; padding: 24px 40px; font-size: 16px; }}
.content h2 {{ font-size: 22px; color: #58a6ff; margin: 32px 0 14px; border-left: 4px solid #58a6ff; padding-left: 14px; }}
.content h3 {{ font-size: 18px; color: #d2a8ff; margin: 22px 0 10px; }}
.content h4 {{ font-size: 16px; color: #79c0ff; margin: 16px 0 8px; }}
.content p {{ margin: 10px 0; color: #c9d1d9; line-height: 1.8; }}
.content ul {{ margin: 10px 0 10px 24px; }}
.content li {{ margin: 6px 0; color: #c9d1d9; line-height: 1.8; }}
.content strong {{ color: #f0f6fc; }}
.content hr {{ border: none; border-top: 1px solid #30363d; margin: 24px 0; }}
.content table {{ border-collapse: collapse; width: 100%; margin: 12px 0; font-size: 14px; }}
.content th, .content td {{ border: 1px solid #30363d; padding: 8px 12px; text-align: left; }}
.content th {{ background: #161b22; color: #58a6ff; font-weight: 600; }}
.content td {{ color: #c9d1d9; }}
.inline-chart {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 16px; margin: 20px 0; }}
.inline-chart .chart-label {{ font-size: 14px; color: #8b949e; margin-bottom: 8px; text-align: center; }}
.chart-row {{ display: flex; flex-wrap: wrap; gap: 16px; }}
.chart-half {{ flex: 1; min-width: 300px; }}
.chart-gauge {{ width: 100%; height: 220px; }}
.chart-bar {{ width: 100%; height: 280px; }}
.footer {{ text-align: center; padding: 24px; color: #484f58; font-size: 13px; border-top: 1px solid #30363d; margin-top: 40px; }}
</style>
</head>
<body>
<div class="header">
  <h1>🪙 加密货币投研日报</h1>
  <div class="meta">{now_bjt} | Claude Sonnet 矿场视角深度分析 | BTC/ETH | 20+ 数据源</div>
  <div class="price-banner">
    BTC <span class="btc" id="live-btc-price">${btc_price:,.0f}</span>
    <span id="live-price-tag" style="font-size:12px;color:#484f58;margin-left:4px;">(报告生成时)</span>
    &nbsp;&nbsp; Fear &amp; Greed: <span style="color:{'#c62828' if fg_val != '?' and int(fg_val) < 25 else '#ef6c00' if fg_val != '?' and int(fg_val) < 45 else '#fdd835' if fg_val != '?' and int(fg_val) < 55 else '#66bb6a' if fg_val != '?' and int(fg_val) < 75 else '#2e7d32'}">{fg_val} ({fg_lbl})</span>
  </div>
</div>

<div class="content">
{body_html}
</div>

<div class="footer">
  情报部门 | Claude Sonnet 首席分析师 | {now_bjt}<br>
  数据源: CoinGecko / Blockchain.info / mempool.space / Binance / OKX / Bybit / Deribit / DefiLlama / Yahoo Finance
</div>

<script>
{charts_js}
window.addEventListener('resize', function() {{
  document.querySelectorAll('[id^="chart-"]').forEach(function(el) {{
    var c = echarts.getInstanceByDom(el);
    if (c) c.resize();
  }});
}});
// 实时BTC价格（页面加载时从CoinGecko拉取）
(function() {{
  fetch('https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd')
    .then(function(r) {{ return r.json(); }})
    .then(function(d) {{
      if (d && d.bitcoin && d.bitcoin.usd) {{
        var p = d.bitcoin.usd;
        var el = document.getElementById('live-btc-price');
        var tag = document.getElementById('live-price-tag');
        if (el) el.textContent = '$' + p.toLocaleString('en-US', {{maximumFractionDigits:0}});
        if (tag) {{ tag.textContent = '(实时)'; tag.style.color = '#2e7d32'; }}
      }}
    }}).catch(function() {{}});
}})();
</script>
</body>
</html>'''

    preview_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'preview.html')
    with open(preview_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f'  预览HTML已保存: {preview_path} ({len(html)} 字符)')
    return preview_path


# ============================================================
# 图表与文字章节关键词匹配（决定哪个图嵌在哪个章节后面）
# ============================================================
CHART_SECTION_MAP = {
    'market_overview': {
        'keywords': ['市场', 'market', 'btc', 'eth', '行情', '价格', '涨跌', '全景', '概览', '快照', '总览', '核心矛盾'],
        'data_check': lambda d: d.get('coin_changes') or d.get('fear_greed_value'),
        'html': '''<div class="inline-chart" aria-label="市场概览图表">
  <div class="chart-row">
    <div class="chart-half"><div class="chart-label">恐贪指数</div><div id="chart-fear-greed" class="chart-gauge"></div></div>
    <div class="chart-half"><div class="chart-label">24h 主要资产涨跌幅 (%)</div><div id="chart-assets" class="chart-bar"></div></div>
  </div>
</div>''',
    },
    'hashrate': {
        'keywords': ['矿工', '算力', 'hashrate', 'mining', '挖矿', '矿场', '矿工经济'],
        'data_check': lambda d: len(d.get('hashrate_daily', [])) > 5,
        'html': '''<div class="inline-chart" aria-label="算力与收益走势">
  <div class="chart-label">40天全网算力 (EH/s) 与每TH/s日收益 (¥)</div>
  <div id="chart-hashrate" style="width:100%;height:300px;"></div>
</div>''',
    },
    'difficulty_history': {
        'keywords': ['难度', 'difficulty', '调整', 'adjustment'],
        'data_check': lambda d: len(d.get('difficulty_history', [])) > 3,
        'html': '''<div class="inline-chart" aria-label="难度调整历史">
  <div class="chart-label">近期难度调整历史 (变化% + 绝对值T)</div>
  <div id="chart-difficulty" style="width:100%;height:300px;"></div>
</div>''',
    },
    'btc_price_trend': {
        'keywords': ['btc', 'bitcoin', '价格', 'price', '深度分析', '链上'],
        'data_check': lambda d: len(d.get('btc_price_history', [])) > 5,
        'html': '''<div class="inline-chart" aria-label="BTC价格走势">
  <div class="chart-label">40天BTC价格走势 (USD)</div>
  <div id="chart-btc-price" style="width:100%;height:300px;"></div>
</div>''',
    },
    'miner_revenue': {
        'keywords': ['矿工收入', 'miner revenue', 'puell', '收入趋势'],
        'data_check': lambda d: len(d.get('miner_revenue_history', [])) > 3,
        'html': '''<div class="inline-chart" aria-label="矿工收入趋势">
  <div class="chart-label">30天矿工日收入趋势 (USD)</div>
  <div id="chart-miner-revenue" style="width:100%;height:300px;"></div>
</div>''',
    },
}


def _build_interleaved_html(report_text, chart_data):
    """将分析报告按章节拆分，在对应章节后插入图表，实现图文一体化"""
    sections = re.split(r'^(## .+)$', report_text, flags=re.MULTILINE)

    result_parts = []
    charts_used = set()

    for i, part in enumerate(sections):
        part = part.strip()
        if not part:
            continue

        part_html = _md_to_html(part)
        result_parts.append(part_html)

        if part.startswith('## '):
            for chart_key, chart_info in CHART_SECTION_MAP.items():
                if chart_key in charts_used:
                    continue
                # 数据验证：对应数据为空则跳过该图表
                data_ok = chart_info.get('data_check', lambda d: True)(chart_data)
                if not data_ok:
                    print(f'  [CHART] {chart_key}: skipped (no data)')
                    charts_used.add(chart_key)  # 标记为已处理，不再匹配
                    continue
                if any(kw in part.lower() for kw in chart_info['keywords']):
                    charts_used.add(chart_key)
                    result_parts.append(f'<!--CHART:{chart_key}-->')
                    print(f'  [CHART] {chart_key}: matched → "{part.strip()[:40]}"')
                    break

    # 后处理：将<!--CHART:xxx-->替换为实际图表HTML
    # 但需要调整位置——chart标记在标题后面，应该在内容后面
    final_parts = []
    pending_chart = None
    for part in result_parts:
        if part.startswith('<!--CHART:'):
            chart_key = part.replace('<!--CHART:', '').replace('-->', '')
            pending_chart = chart_key
        else:
            final_parts.append(part)
            if pending_chart:
                chart_html = CHART_SECTION_MAP[pending_chart]['html']
                final_parts.append(chart_html)
                pending_chart = None

    # 如果有图表一直没匹配到任何章节，追加到末尾
    unused = set(CHART_SECTION_MAP.keys()) - charts_used
    if unused:
        final_parts.append('<div class="inline-chart"><div class="chart-row">')
        for chart_key in unused:
            final_parts.append(CHART_SECTION_MAP[chart_key]['html'])
        final_parts.append('</div></div>')

    return '\n'.join(final_parts)


def _build_charts_js(data):
    """生成ECharts图表JavaScript"""
    js = []

    # 1. 恐贪指数仪表盘
    fg_val = data.get('fear_greed_value', 50)
    fg_label = data.get('fear_greed_label', 'Neutral')
    js.append(f'''
var fgChart = echarts.init(document.getElementById('chart-fear-greed'));
fgChart.setOption({{
  series: [{{
    type: 'gauge', startAngle: 180, endAngle: 0, min: 0, max: 100, splitNumber: 4,
    pointer: {{ show: true, length: '60%', width: 6 }},
    axisLine: {{ lineStyle: {{ width: 20,
      color: [[0.25, '#c62828'], [0.45, '#ef6c00'], [0.55, '#fdd835'], [0.75, '#66bb6a'], [1, '#2e7d32']]
    }} }},
    axisTick: {{ show: false }}, splitLine: {{ show: false }}, axisLabel: {{ show: false }},
    detail: {{ fontSize: 28, fontWeight: 'bold', offsetCenter: [0, '30%'],
      formatter: function(v) {{ return v + '\\n{fg_label}'; }}, color: '#e6edf3'
    }},
    data: [{{ value: {fg_val} }}]
  }}]
}});''')

    # 2. 资产涨跌幅柱状图
    coin_changes = data.get('coin_changes', {})
    assets = list(coin_changes.keys())
    changes = list(coin_changes.values())
    # 加入宏观资产
    for key, label in [('dxy', 'DXY'), ('gold', 'Gold'), ('spx', 'S&P500')]:
        chg = data.get(f'macro_{key}_change', 0)
        if chg:
            assets.append(label)
            changes.append(round(float(chg), 2))

    if assets:
        colors = ['#2e7d32' if c >= 0 else '#c62828' for c in changes]
        js.append(f'''
var assetChart = echarts.init(document.getElementById('chart-assets'));
assetChart.setOption({{
  tooltip: {{ trigger: 'axis', formatter: '{{b}}: {{c}}%' }},
  xAxis: {{ type: 'category', data: {json.dumps(assets)}, axisLabel: {{ fontSize: 11, rotate: 30, color: '#8b949e' }} }},
  yAxis: {{ type: 'value', axisLabel: {{ formatter: '{{value}}%', color: '#8b949e' }}, splitLine: {{ lineStyle: {{ color: '#21262d' }} }} }},
  series: [{{
    type: 'bar', data: {json.dumps(changes)},
    itemStyle: {{ color: function(p) {{ return {json.dumps(colors)}[p.dataIndex]; }} }},
    label: {{ show: true, position: 'top', formatter: '{{c}}%', fontSize: 10, color: '#8b949e' }}
  }}],
  grid: {{ left: 50, right: 20, top: 20, bottom: 60 }}
}});''')

    # 3. 40天算力 + 每TH/s日收益双轴折线图
    hr_daily = data.get('hashrate_daily', [])
    btc_usd = data.get('btc_price_usd', 0)
    if hr_daily and len(hr_daily) > 5 and btc_usd:
        dates = [p['date'] for p in hr_daily]
        hashrates = [p['hashrate_eh'] for p in hr_daily]
        # 每TH/s日收益(¥) = (3.125 BTC × 144 blocks / 网络总TH) × BTC价格CNY
        # 网络总TH = EH/s × 1e6, CNY ≈ USD × 7.2
        btc_cny = btc_usd * 7.2
        revenues = []
        for p in hr_daily:
            hr_th = p['hashrate_eh'] * 1e6  # EH→TH
            if hr_th > 0:
                daily_btc_per_th = (3.125 * 144) / hr_th
                rev_cny = round(daily_btc_per_th * btc_cny, 2)
            else:
                rev_cny = 0
            revenues.append(rev_cny)
        js.append(f'''
var hrChart = echarts.init(document.getElementById('chart-hashrate'));
hrChart.setOption({{
  tooltip: {{ trigger: 'axis', axisPointer: {{ type: 'cross' }} }},
  legend: {{ data: ['算力 (EH/s)', '每TH/s日收益 (¥)'], textStyle: {{ color: '#8b949e', fontSize: 11 }}, top: 5 }},
  xAxis: {{ type: 'category', data: {json.dumps(dates)}, axisLabel: {{ fontSize: 10, color: '#8b949e', rotate: 30 }} }},
  yAxis: [
    {{ type: 'value', name: 'EH/s', nameTextStyle: {{ color: '#58a6ff', fontSize: 11 }},
      axisLabel: {{ color: '#8b949e' }}, splitLine: {{ lineStyle: {{ color: '#21262d' }} }} }},
    {{ type: 'value', name: '¥/TH/s/天', nameTextStyle: {{ color: '#f7931a', fontSize: 11 }},
      axisLabel: {{ color: '#8b949e', formatter: '¥{{value}}' }}, splitLine: {{ show: false }} }}
  ],
  series: [
    {{ name: '算力 (EH/s)', type: 'line', data: {json.dumps(hashrates)},
      lineStyle: {{ color: '#58a6ff', width: 2 }}, itemStyle: {{ color: '#58a6ff' }},
      smooth: true, symbol: 'none', areaStyle: {{ color: 'rgba(88,166,255,0.1)' }} }},
    {{ name: '每TH/s日收益 (¥)', type: 'line', yAxisIndex: 1, data: {json.dumps(revenues)},
      lineStyle: {{ color: '#f7931a', width: 2 }}, itemStyle: {{ color: '#f7931a' }},
      smooth: true, symbol: 'none' }}
  ],
  grid: {{ left: 60, right: 70, top: 40, bottom: 50 }}
}});''')

    # 4. 难度调整历史（柱状图+折线图双轴）
    diff_hist = data.get('difficulty_history', [])
    if diff_hist and len(diff_hist) > 3:
        d_dates = [p['date'] for p in diff_hist]
        d_changes = [p['change_pct'] for p in diff_hist]
        d_values = [p['difficulty_t'] for p in diff_hist]
        d_colors = ['#2e7d32' if c >= 0 else '#c62828' for c in d_changes]
        js.append(f'''
var diffChart = echarts.init(document.getElementById('chart-difficulty'));
diffChart.setOption({{
  tooltip: {{ trigger: 'axis', axisPointer: {{ type: 'cross' }} }},
  legend: {{ data: ['调整幅度 (%)', '难度 (T)'], textStyle: {{ color: '#8b949e', fontSize: 11 }}, top: 5 }},
  xAxis: {{ type: 'category', data: {json.dumps(d_dates)}, axisLabel: {{ fontSize: 10, color: '#8b949e', rotate: 30 }} }},
  yAxis: [
    {{ type: 'value', name: '调整%', nameTextStyle: {{ color: '#58a6ff', fontSize: 11 }},
      axisLabel: {{ color: '#8b949e', formatter: '{{value}}%' }}, splitLine: {{ lineStyle: {{ color: '#21262d' }} }} }},
    {{ type: 'value', name: 'T', nameTextStyle: {{ color: '#f7931a', fontSize: 11 }},
      axisLabel: {{ color: '#8b949e' }}, splitLine: {{ show: false }} }}
  ],
  series: [
    {{ name: '调整幅度 (%)', type: 'bar', data: {json.dumps(d_changes)},
      itemStyle: {{ color: function(p) {{ return {json.dumps(d_colors)}[p.dataIndex]; }} }},
      label: {{ show: true, position: 'top', formatter: '{{c}}%', fontSize: 9, color: '#8b949e' }} }},
    {{ name: '难度 (T)', type: 'line', yAxisIndex: 1, data: {json.dumps(d_values)},
      lineStyle: {{ color: '#f7931a', width: 2 }}, itemStyle: {{ color: '#f7931a' }},
      smooth: true, symbol: 'circle', symbolSize: 6 }}
  ],
  grid: {{ left: 60, right: 60, top: 40, bottom: 50 }}
}});''')

    # 5. 40天BTC价格走势
    btc_hist = data.get('btc_price_history', [])
    if btc_hist and len(btc_hist) > 5:
        b_dates = [p['date'] for p in btc_hist]
        b_prices = [p['price'] for p in btc_hist]
        js.append(f'''
var btcPriceChart = echarts.init(document.getElementById('chart-btc-price'));
btcPriceChart.setOption({{
  tooltip: {{ trigger: 'axis', formatter: function(p) {{ return p[0].name + '<br/>$' + p[0].value.toLocaleString(); }} }},
  xAxis: {{ type: 'category', data: {json.dumps(b_dates)}, axisLabel: {{ fontSize: 10, color: '#8b949e', rotate: 30 }} }},
  yAxis: {{ type: 'value', axisLabel: {{ color: '#8b949e', formatter: function(v) {{ return '$' + (v/1000).toFixed(0) + 'k'; }} }},
    splitLine: {{ lineStyle: {{ color: '#21262d' }} }}, scale: true }},
  series: [{{
    type: 'line', data: {json.dumps(b_prices)},
    lineStyle: {{ color: '#f7931a', width: 2.5 }}, itemStyle: {{ color: '#f7931a' }},
    smooth: true, symbol: 'none',
    areaStyle: {{ color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
      {{ offset: 0, color: 'rgba(247,147,26,0.3)' }}, {{ offset: 1, color: 'rgba(247,147,26,0.02)' }}
    ]) }},
    markPoint: {{
      data: [{{ type: 'max', name: '最高' }}, {{ type: 'min', name: '最低' }}],
      label: {{ formatter: function(p) {{ return '$' + (p.value/1000).toFixed(1) + 'k'; }}, fontSize: 10 }}
    }}
  }}],
  grid: {{ left: 60, right: 20, top: 20, bottom: 50 }}
}});''')

    # 6. 30天矿工日收入趋势
    rev_hist = data.get('miner_revenue_history', [])
    if rev_hist and len(rev_hist) > 3:
        r_dates = [p['date'] for p in rev_hist]
        r_revenues = [p['revenue_usd'] for p in rev_hist]
        js.append(f'''
var revChart = echarts.init(document.getElementById('chart-miner-revenue'));
revChart.setOption({{
  tooltip: {{ trigger: 'axis', formatter: function(p) {{ return p[0].name + '<br/>$' + p[0].value.toLocaleString(); }} }},
  xAxis: {{ type: 'category', data: {json.dumps(r_dates)}, axisLabel: {{ fontSize: 10, color: '#8b949e', rotate: 30 }} }},
  yAxis: {{ type: 'value', axisLabel: {{ color: '#8b949e', formatter: function(v) {{ return '$' + (v/1e6).toFixed(1) + 'M'; }} }},
    splitLine: {{ lineStyle: {{ color: '#21262d' }} }} }},
  series: [{{
    type: 'line', data: {json.dumps(r_revenues)},
    lineStyle: {{ color: '#66bb6a', width: 2 }}, itemStyle: {{ color: '#66bb6a' }},
    smooth: true, symbol: 'none',
    areaStyle: {{ color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
      {{ offset: 0, color: 'rgba(102,187,106,0.3)' }}, {{ offset: 1, color: 'rgba(102,187,106,0.02)' }}
    ]) }}
  }}],
  grid: {{ left: 70, right: 20, top: 20, bottom: 50 }}
}});''')

    return '\n'.join(js)


def _md_to_html(text):
    """简易markdown→HTML（支持表格）"""
    text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    text = re.sub(r'^## (.+)$', r'<h2>\1</h2>', text, flags=re.MULTILINE)
    text = re.sub(r'^### (.+)$', r'<h3>\1</h3>', text, flags=re.MULTILINE)
    text = re.sub(r'^#### (.+)$', r'<h4>\1</h4>', text, flags=re.MULTILINE)
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'^- (.+)$', r'<li>\1</li>', text, flags=re.MULTILINE)
    text = re.sub(r'^(\d+)\. (.+)$', r'<li>\2</li>', text, flags=re.MULTILINE)
    text = re.sub(r'^---+$', '<hr>', text, flags=re.MULTILINE)
    paragraphs = text.split('\n\n')
    parts = []
    for p in paragraphs:
        p = p.strip()
        if not p:
            continue
        if p.startswith('<h') or p.startswith('<hr'):
            parts.append(p)
        elif '<li>' in p:
            parts.append(f'<ul>{p}</ul>')
        elif '|' in p and p.count('\n') >= 1:
            # Markdown表格解析
            lines = [l.strip() for l in p.split('\n') if l.strip() and not re.match(r'^[\s|:-]+$', l)]
            if len(lines) >= 1:
                rows = []
                for idx, line in enumerate(lines):
                    cells = [c.strip() for c in line.strip('|').split('|')]
                    tag = 'th' if idx == 0 else 'td'
                    row_html = ''.join(f'<{tag}>{c}</{tag}>' for c in cells)
                    rows.append(f'<tr>{row_html}</tr>')
                parts.append(f'<table>{"".join(rows)}</table>')
            else:
                parts.append(f'<p>{p.replace(chr(10), "<br>")}</p>')
        else:
            parts.append(f'<p>{p.replace(chr(10), "<br>")}</p>')
    return '\n'.join(parts)


# ============================================================
# 推送
# ============================================================

def split_and_push(analysis_text, date_str):
    """将分析报告推送（Server酱）— 完整图文版链接 + 文字摘要"""
    from notify import push_serverchan_report, push_serverchan_status

    if not analysis_text:
        push_serverchan_status('加密投研日报', '失败', 'Claude分析未返回结果')
        return

    # Server酱推送 — 图文一体化版本链接 + 完整文字正文
    header = (
        f'\n\n'
        f'## 📊 [点击查看图文版报告（含交互图表）]({PREVIEW_URL})\n\n'
        f'> 恐贪指数 · 涨跌图 · 算力+收益 · 难度调整 · BTC价格走势 · 矿工收入 — 6张交互图表嵌在分析文字中\n\n'
        f'---\n\n'
    )
    enriched_text = header + analysis_text

    push_serverchan_report(f'【加密情报】{date_str} 投研日报', enriched_text)

    push_serverchan_status('加密投研日报', '成功', f'{date_str} 报告已推送，{len(analysis_text)}字，图文一体化版本')


def save_to_supabase(date_str, analysis_text, data_summary):
    """存档到Supabase — 复用daily_intelligence表，title字段标记为crypto类型"""
    try:
        row = {
            'date': date_str,
            'title': f'[Crypto] {date_str} 加密货币投研日报',
            'content': analysis_text[:50000] if analysis_text else '',
            'raw_data': json.dumps(data_summary, ensure_ascii=False, default=str)[:50000],
            'created_at': datetime.now(timezone.utc).isoformat(),
        }
        body = json.dumps(row).encode('utf-8')
        req = Request(
            f'{SUPABASE_URL}/rest/v1/daily_intelligence',
            data=body,
            headers={
                'apikey': SUPABASE_KEY,
                'Authorization': f'Bearer {SUPABASE_KEY}',
                'Content-Type': 'application/json',
                'Prefer': 'return=minimal',
            },
            method='POST'
        )
        urlopen(req, timeout=15)
        print('  Supabase存档成功')
    except Exception as e:
        print(f'  Supabase存档失败（不影响推送）: {e}')


# ============================================================
# 主流程
# ============================================================

def main():
    print(f'=== 加密货币投研日报 v2.1 (Mining-Focused, 6-Charts) ===')
    print(f'日期: {TODAY_BJT}')
    print(f'时间: {datetime.now(BJT).strftime("%H:%M:%S")} BJT\n')

    # Step 1-10: 数据采集
    market = collect_market_overview()
    onchain = collect_onchain_fundamentals()
    mining = collect_mining_difficulty()
    funding = collect_derivatives_funding()
    oi_ls = collect_derivatives_oi_ls()
    options = collect_options_market()
    defi = collect_defi()
    macro = collect_macro()
    sentiment = collect_sentiment()
    news = collect_news()

    # 历史趋势数据（供ECharts图表）
    historical = collect_historical_charts()

    # 新闻分级（RED/YELLOW/GREEN + T1/T2/T3）
    print('\n新闻分级...')
    news = classify_news(news)
    red = sum(1 for n in news if n.get('level') == 'RED')
    yellow = sum(1 for n in news if n.get('level') == 'YELLOW')
    green = sum(1 for n in news if n.get('level') == 'GREEN')
    print(f'  分级结果: 🔴RED {red} | 🟡YELLOW {yellow} | 🟢GREEN {green}')

    # 格式化数据
    print('\n格式化数据...')
    data_context = format_data_context(
        market, onchain, mining, funding, oi_ls, options, defi, macro, sentiment, news
    )

    # 打印数据长度
    print(f'  数据上下文: {len(data_context)} 字符')

    # LLM深度分析（DeepSeek via OpenRouter）
    analysis = call_llm_analysis(data_context)

    if analysis:
        print(f'\n分析报告: {len(analysis)} 字符')

        # 生成预览HTML（含ECharts交互图表）
        try:
            generate_preview_html(analysis, market, onchain, mining, funding, options, defi, macro, sentiment, historical=historical)
        except Exception as e:
            print(f'  ⚠️ 预览HTML生成失败（不影响推送）: {e}')

        # 多条Server酱推送（含图表预览链接）
        split_and_push(analysis, TODAY_BJT)

        # Supabase存档
        data_summary = {
            'market': market.get('global'),
            'btc_price': market.get('prices', {}).get('bitcoin', {}).get('usd'),
            'puell_multiple': onchain.get('puell_multiple'),
            'nvt_ratio': onchain.get('nvt_ratio'),
            'fear_greed': sentiment.get('fear_greed', {}).get('value'),
            'btc_funding_binance': funding.get('binance', {}).get('BTC'),
            'put_call_ratio': options.get('btc_options', {}).get('put_call_ratio'),
            'dvol': options.get('dvol', {}).get('current'),
            'tvl': defi.get('tvl_current'),
            'dxy': macro.get('DXY', {}).get('price'),
            'news_count': len(news),
        }
        save_to_supabase(TODAY_BJT, analysis, data_summary)
    else:
        from notify import push_serverchan_status
        push_serverchan_status('加密投研日报', '失败', f'{TODAY_BJT} LLM分析未返回结果，请检查OpenRouter API Key')

    print('\n=== 完成 ===')


if __name__ == '__main__':
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    main()
