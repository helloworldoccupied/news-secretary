#!/usr/bin/env python3
"""
加密货币投研日报 v1.0 — Crypto Daily Intelligence
专注虚拟货币深度投研分析，独立于A股情报

数据管线（20+数据源）：
  1. 市场总览：CoinGecko 全局数据 + 主要币种行情
  2. 链上基本面：Blockchain.info（Puell Multiple、NVT Ratio）
  3. 挖矿与难度：mempool.space + Blockchain.info
  4. 衍生品-资金费率：Binance + OKX + Bybit 三所对比
  5. 衍生品-持仓与多空：OI + Long/Short Ratio + Taker Volume
  6. 期权市场：Deribit（Put/Call Ratio、DVOL、Max Pain、总OI）
  7. DeFi生态：DefiLlama TVL + DEX成交量 + 稳定币
  8. 宏观关联：Yahoo Finance DXY/黄金/美债/标普
  9. 情绪指标：Fear & Greed Index + CoinGecko Trending
  10. 新闻快讯：BlockBeats RSS

分析：DeepSeek V3.2 via OpenRouter（核心矛盾+因果链+历史类比），备选Qwen 3.5 Plus
推送：Server酱（微信推送，唯一通道，飞书已废弃）
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
# LLM分析引擎：DeepSeek via OpenRouter（董事会2026-03-04选型决议）
# 备选：Qwen 3.5 Plus（自动fallback）
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
    coins = 'bitcoin,ethereum,solana,binancecoin,ripple,cardano,dogecoin,avalanche-2,chainlink,polkadot'
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
    top_coins = ['BTC', 'ETH', 'SOL', 'DOGE', 'XRP', 'ADA', 'AVAX', 'LINK', 'DOT', 'BNB']

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
    for coin in top_coins[:5]:  # Top 5 only to save rate limit
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


def collect_news():
    """Step 10: 新闻快讯 — BlockBeats RSS"""
    print('[10/10] 新闻快讯...')
    flashes = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

    FINANCE_KW = re.compile(
        r'BTC|ETH|SOL|比特币|以太坊|Bitcoin|Ethereum|Solana|Layer.?2|DeFi|NFT|DEX|CEX|'
        r'稳定币|stablecoin|USDT|USDC|矿工|挖矿|hash.?rate|'
        r'SEC|CFTC|监管|regulation|ETF|清算|liquidat|爆仓|'
        r'融资|投资|fund|invest|IPO|估值|valuation|收购|acqui|'
        r'Fed|美联储|利率|CPI|GDP|非农|PMI|降息|加息|'
        r'Binance|OKX|Coinbase|Bybit|Bitfinex|Kraken|'
        r'Uniswap|Aave|Lido|MakerDAO|Compound|Curve|'
        r'钱包|wallet|链上|on.?chain|Gas|MEV|'
        r'牛市|熊市|bull|bear|多头|空头|long|short',
        re.IGNORECASE
    )

    try:
        url = 'https://api.theblockbeats.news/v2/rss/newsflash'
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
            try:
                dt = parsedate_to_datetime(pub)
                if dt < cutoff:
                    continue
            except:
                pass
            # 金融相关性过滤
            text = f'{title} {desc}'
            if not FINANCE_KW.search(text):
                continue
            flashes.append({'title': title, 'desc': desc[:200]})
    except Exception as e:
        print(f'  [BlockBeats] {e}')

    return flashes[:40]


# ============================================================
# Claude分析
# ============================================================

CRYPTO_ANALYST_SYSTEM = """你是一位管理$50亿加密货币基金的首席投资官（CIO），每天向基金董事长提交投研日报。

## 时间规范（最高优先级）
- 所有时间引用必须使用**北京时间（BJT/UTC+8）**
- "今日"、"昨日"、"本周"均以北京时间为基准
- 数据中提供的采集时间就是报告基准时间
- 不要用UTC时间，不要用"过去24小时"这种模糊说法，要用"北京时间3月2日08:00的数据显示..."
- 价格和涨跌幅要与采集时间点一致，不要自行推断其他时间点的价格

## 你的分析方法论

### 核心矛盾法
每天的市场只有1-2个真正的核心矛盾。找到它们，围绕它们展开所有分析。
例如："链上数据显示长期持有者在加速出货，但ETF资金持续流入——核心矛盾是机构接盘速度能否消化老筹码抛压"

### 因果链推演（必须做）
事件 → 传导机制 → 一阶效应 → 二阶效应 → 对仓位的影响
不要只说"X发生了"，要推演"X发生了 → 因为Y机制 → 导致Z → 这意味着..."

### 历史类比（必须给出）
当前市场形态让你想到历史上哪个阶段？给出具体日期、具体数据对比、当时的后续走势。
例如："当前Puell Multiple 0.68接近2023年1月的0.65水平，当时BTC在$16,500筑底，随后6个月涨至$31,000（+88%）"

### 链上数据解读（核心竞争力）
- Puell Multiple：<0.5极度低估（历史底部区域），0.5-1.0低估，1.0-4.0正常，>4.0过热
- NVT Ratio：<50网络被低估（交易活跃度高），50-120正常，>120过热（投机超过使用）
- 活跃地址趋势：与价格背离时是强信号
- 矿工收入与成本：矿工投降往往是底部信号

### 衍生品市场解读（领先指标）
- 资金费率：三所对比找分歧，全市场正费率占比反映整体偏多/偏空
- 多空比变化方向比绝对值更重要：连续3小时多头增加 vs 突然反转
- OI变化 + 价格方向：OI增+价涨=新多开仓（强），OI减+价涨=空头平仓（弱）
- 期权市场：Put/Call >1 = 对冲需求增加（看跌保护），DVOL上升 = 市场预期波动加大
- Max Pain：大到期日前价格有向Max Pain回归的引力

### 宏观关联（必须分析）
- DXY与BTC通常负相关，DXY走强压制风险资产
- 美债收益率上升 = 无风险回报上升 = 资金从加密流出
- 黄金与BTC的关联度近年上升，作为"数字黄金"叙事的验证
- 稳定币总市值增减 = 加密市场资金池的涨缩

## 铁律
1. 不说"建议关注"、"值得关注" — 要说"应该做什么"
2. 不说"可能上涨也可能下跌" — 要给方向判断和概率
3. 不说"谨慎观望" — 要说在什么条件下做什么
4. 每个判断附带置信度（高/中/低）和逻辑链
5. 信号冲突时用⚡显式标注，分析哪个信号更可靠
6. 风险提示必须具体：不是"注意风险"，而是"如果X跌破Y，止损Z"
7. 数据必须量化到具体数字，不用"大幅"、"显著"等模糊词

## 输出格式要求（手机+电脑阅读）
- 用 ## 大标题（不要用###）
- 关键数字全部**加粗**
- 每段不超过4行
- 段落间用空行分隔
- 正负面emoji：🔴负面 🟡中性 🟢正面 ⚡冲突
- 不用表格（手机显示会乱）
- 分隔线 --- 分开大板块"""

CRYPTO_ANALYST_USER = """请基于以下实时数据，撰写今日加密货币投研日报。

要求：
1. 先找到今日1-2个核心矛盾，作为整篇报告的主线
2. 深度分析，不是新闻摘要——每个数据点都要解读"这意味着什么"
3. 所有判断给出因果链和历史类比
4. 最后给出明确的仓位建议（不是"建议关注"）

## 报告结构

**第一部分：核心矛盾与结论**（最重要，放最前面）
- 今日核心矛盾是什么？
- 你的判断是什么？（方向+置信度+逻辑）
- 具体仓位建议（BTC/ETH/山寨币各怎么操作）

**第二部分：市场全景**
- BTC/ETH/主要山寨涨跌
- 总市值变化、BTC市占率变化
- Fear & Greed变化趋势（不只是今天的数字，要看30天趋势方向）

**第三部分：矿工经济学（⚠️ 必写，读者拥有BTC矿场）**
- 全网算力当前值 vs 7日均值 vs 40天趋势方向（RISING/STABLE/FALLING）
- 算力变化对单位算力BTC产出的影响（算力↑→产出↓→收益承压）
- 下次难度调整预估幅度及对矿工的影响
- 矿工日收入 vs 30天均值，矿工是否在抛售BTC
- Puell Multiple当前位置及其含义（矿工投降/正常/过热）
- Mempool拥堵情况和交易费收入对矿工收入的贡献

**第四部分：链上深度分析**
- NVT Ratio解读（网络使用效率）
- 活跃地址趋势（是否与价格背离）
- Mempool费率（链上活跃度代理）

**第五部分：衍生品市场**
- 三所资金费率对比（Binance/OKX/Bybit），找分歧
- 全市场资金费率分布（正费率占比、中位数、极值）
- OI变化方向 + 多空比变化方向（组合解读）
- Taker买卖比（实际资金流向）

**第六部分：期权市场**
- Put/Call Ratio变化含义
- DVOL vs 历史波动率（隐含vs实际，谁高=市场预期波动加大/减小）
- 最近到期日Max Pain及其意义
- BTC vs ETH期权情绪差异

**第七部分：DeFi与稳定币**
- TVL变化方向（资金在流入还是流出）
- DEX成交量变化（链上交易活跃度）
- 稳定币市值变化（加密市场资金池）
- 链间TVL迁移（哪些链在吸引资金）

**第八部分：宏观环境**
- DXY走势及对加密的压制/利好
- 美债收益率变化
- 黄金vs BTC走势对比
- 美股与加密的联动/脱钩

**第九部分：新闻与事件**
- 按重要性排序，只挑真正影响市场的
- 每条新闻给出影响判断（利好/利空/中性 + 影响量级）

**第十部分：风险矩阵**
- Top 3风险事件 + 触发条件 + 对冲方案
- Top 3机会 + 入场条件 + 目标位

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
        max_tokens=8000,
        timeout=180,
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
        s += '\n主要币种:\n'
        for coin_id, d in market['prices'].items():
            name = coin_id.replace('-2', '').upper()[:6]
            price = d.get('usd', 0)
            change = d.get('usd_24h_change', 0) or 0
            mcap = d.get('usd_market_cap', 0) or 0
            s += f"  {name}: ${price:,.2f} ({change:+.1f}%) MCap ${mcap/1e9:.1f}B\n"
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
    for coin in ['BTC', 'ETH', 'SOL', 'DOGE', 'XRP']:
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

    # 新闻
    s = '## 最近24h重要新闻\n'
    if news:
        for i, n in enumerate(news[:20], 1):
            s += f"{i}. {n['title']}\n"
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


def generate_preview_html(report_text, market, onchain, mining, funding, options, defi, macro, sentiment):
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
<title>加密投研日报 {TODAY_BJT}</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif; background: #0d1117; color: #e6edf3; line-height: 1.7; }}
.header {{ background: linear-gradient(135deg, #1a1f36 0%, #0d1117 100%); border-bottom: 2px solid #f7931a; padding: 20px; text-align: center; }}
.header h1 {{ font-size: 24px; color: #f7931a; margin-bottom: 8px; }}
.header .meta {{ font-size: 14px; color: #8b949e; }}
.header .price-banner {{ margin-top: 12px; font-size: 18px; }}
.header .price-banner .btc {{ color: #f7931a; font-weight: bold; font-size: 28px; }}
.content {{ max-width: 900px; margin: 0 auto; padding: 16px 20px; }}
.content h2 {{ font-size: 20px; color: #58a6ff; margin: 28px 0 12px; border-left: 4px solid #58a6ff; padding-left: 12px; }}
.content h3 {{ font-size: 17px; color: #d2a8ff; margin: 18px 0 8px; }}
.content h4 {{ font-size: 15px; color: #79c0ff; margin: 14px 0 6px; }}
.content p {{ margin: 8px 0; color: #c9d1d9; }}
.content ul {{ margin: 8px 0 8px 20px; }}
.content li {{ margin: 4px 0; color: #c9d1d9; }}
.content strong {{ color: #f0f6fc; }}
.content hr {{ border: none; border-top: 1px solid #30363d; margin: 20px 0; }}
.inline-chart {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 12px; margin: 16px 0; }}
.inline-chart .chart-label {{ font-size: 13px; color: #8b949e; margin-bottom: 6px; text-align: center; }}
.chart-row {{ display: flex; flex-wrap: wrap; gap: 12px; }}
.chart-half {{ flex: 1; min-width: 260px; }}
.chart-gauge {{ width: 100%; height: 200px; }}
.chart-bar {{ width: 100%; height: 260px; }}
.footer {{ text-align: center; padding: 20px; color: #484f58; font-size: 13px; border-top: 1px solid #30363d; margin-top: 40px; }}
@media (max-width: 768px) {{
  .chart-half {{ min-width: 100%; }}
  .chart-row {{ flex-direction: column; }}
  .header h1 {{ font-size: 20px; }}
  .content {{ padding: 12px; }}
}}
</style>
</head>
<body>
<div class="header">
  <h1>🪙 加密货币投研日报</h1>
  <div class="meta">{now_bjt} | Claude Sonnet 深度分析 | 20+ 数据源</div>
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
        'keywords': ['市场', 'market', 'btc', 'eth', '行情', '价格', '涨跌', '全景', '概览', '快照', '总览'],
        'data_check': lambda d: d.get('coin_changes') or d.get('fear_greed_value'),
        'html': '''<div class="inline-chart" aria-label="市场概览图表">
  <div class="chart-row">
    <div class="chart-half"><div class="chart-label">恐贪指数</div><div id="chart-fear-greed" class="chart-gauge"></div></div>
    <div class="chart-half"><div class="chart-label">24h 主要资产涨跌幅 (%)</div><div id="chart-assets" class="chart-bar"></div></div>
  </div>
</div>''',
    },
    'hashrate': {
        'keywords': ['矿工', '算力', 'hashrate', 'mining', '挖矿', '难度', '矿场'],
        'data_check': lambda d: len(d.get('hashrate_daily', [])) > 5,
        'html': '''<div class="inline-chart" aria-label="算力与收益走势">
  <div class="chart-label">40天全网算力 (EH/s) 与每TH/s日收益 (¥)</div>
  <div id="chart-hashrate" style="width:100%;height:300px;"></div>
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

    return '\n'.join(js)


def _md_to_html(text):
    """简易markdown→HTML"""
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

    # Server酱推送 — 图文一体化版本链接 + 文字正文
    header = (
        f'\n\n'
        f'## 📊 [点击查看完整图文报告（含交互图表）]({PREVIEW_URL})\n\n'
        f'> 恐贪指数仪表盘 · 资产涨跌图 · 费率热力图 · 链上指标 — 图表嵌在分析文字中，边看边理解\n\n'
        f'---\n\n'
        f'*以下为纯文字版，完整图文版请点击上方链接*\n\n'
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
    print(f'=== 加密货币投研日报 v1.0 ===')
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
            generate_preview_html(analysis, market, onchain, mining, funding, options, defi, macro, sentiment)
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
