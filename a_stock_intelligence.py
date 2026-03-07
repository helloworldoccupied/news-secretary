#!/usr/bin/env python3
"""
A股+大宗商品+中国宏观情报 v2.0 — A-Share & Commodities Intelligence
情报体系 Line 2：A股市场深度投研 + 国内期货/大宗商品 + 中国宏观经济

v2.0 升级（2026-03-07 董事长指令）：
  - 新增国内期货主力合约行情（黑色/有色/贵金属/能源/农产品/化工）
  - 新增中国宏观经济数据（CPI/PPI/PMI/M2/社融/Shibor/汇率）
  - 新增全球隔夜市场（美股三指数/日经/恒生/美债/黄金/原油/DXY）
  - 涨跌停统计增加回溯逻辑（适配早间运行）
  - 分析视角扩展为"A股+大宗商品+中国宏观"
  - 调度时间从16:00 BJT改为08:05 BJT（晨间简报）
  - LLM提示词重写：增加期货/商品分析方法论

数据管线（10大数据源，全部免费API）：
  1. 大盘指数：上证/深证/创业板/科创50/沪深300/中证500/中证1000
  2. 北向资金：沪股通/深股通实时净流入 + 近10日趋势
  3. 两融数据：融资融券余额变化
  4. 涨跌停统计：涨停/跌停家数、连板、封板率
  5. 板块资金流：行业板块/概念板块资金净流入 Top 20
  6. A股新闻：财联社电报 + 东方财富要闻
  7. 国内期货：SHFE/DCE/CZCE/INE主力合约（20+品种）
  8. 中国宏观：CPI/PPI/PMI/M2/Shibor/USD-CNY
  9. 全球隔夜：美股/亚太/美债/黄金/原油/DXY（Yahoo Finance）
  10. 经济日历：近期重要数据发布/政策事件

分析：Claude Sonnet via Anthropic API（A股+商品CIO级分析），备选GLM-5
推送：Server酱（微信推送，唯一通道）
存档：Supabase daily_intelligence 表（title 前缀 [A-Stock]）

Schedule: Daily 08:05 BJT (morning briefing before market open)
"""
import sys
import os
import io
import json
import time
import re
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from urllib.parse import quote as url_quote

# Windows UTF-8 兼容 — 移到 __main__ 入口，避免被import时重复包装导致I/O closed
# （由 generate_preview.py 通过 PYTHONIOENCODING=utf-8 环境变量处理编码）

# ============================================================
# 配置
# ============================================================
SERVERCHAN_KEY = os.environ.get('SERVERCHAN_KEY', '')
SUPABASE_URL = os.environ.get('SUPABASE_URL', '')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY', '')

UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36'}
BJT = timezone(timedelta(hours=8))
NOW_BJT = datetime.now(BJT)
TODAY_BJT = NOW_BJT.strftime('%Y-%m-%d')
TODAY_YYYYMMDD = NOW_BJT.strftime('%Y%m%d')


def safe_float(val, default=0.0):
    """安全转float，处理空字符串/None/'-'"""
    if val is None or val == '' or val == '-':
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def safe_int(val, default=0):
    """安全转int"""
    if val is None or val == '' or val == '-':
        return default
    try:
        return int(float(val))
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
                print(f'  [FAIL] {url[:100]}... {e}')
                return None
            time.sleep(2)
    return None


def safe_get_text(url, timeout=20, headers=None, retries=2):
    """安全HTTP GET返回原始文本（处理JSONP等非标准JSON）"""
    hdrs = dict(UA)
    if headers:
        hdrs.update(headers)
    for attempt in range(retries + 1):
        try:
            req = Request(url, headers=hdrs)
            raw = urlopen(req, timeout=timeout).read().decode('utf-8', errors='replace')
            return raw
        except Exception as e:
            if attempt == retries:
                print(f'  [FAIL] {url[:100]}... {e}')
                return None
            time.sleep(2)
    return None


def fmt_num(val, unit=''):
    """格式化大数字，自动选择亿/万单位"""
    if val is None:
        return 'N/A'
    v = abs(val)
    sign = '-' if val < 0 else ''
    if v >= 1e8:
        return f'{sign}{v/1e8:.2f}亿{unit}'
    elif v >= 1e4:
        return f'{sign}{v/1e4:.2f}万{unit}'
    else:
        return f'{sign}{v:.2f}{unit}'


def fmt_pct(val):
    """格式化百分比"""
    if val is None:
        return 'N/A'
    return f'{val:+.2f}%'


def _get_last_trading_date():
    """获取最近一个交易日的日期（跳过周末，处理早间运行）"""
    now = datetime.now(BJT)
    # 如果当前时间在15:00之前（盘中或盘前），使用前一个交易日
    if now.hour < 15:
        now = now - timedelta(days=1)
    # 跳过周末
    while now.weekday() >= 5:  # 5=Saturday, 6=Sunday
        now = now - timedelta(days=1)
    return now.strftime('%Y%m%d')


# ============================================================
# 数据采集函数（Step 1-6: A股核心数据）
# ============================================================

def collect_market_indices():
    """Step 1: 大盘指数 — 上证/深证/创业板/科创50"""
    print('[1/10] 大盘指数...')
    result = {}

    # 指数代码映射: secid前缀 1=沪市 0=深市
    indices = {
        '上证指数': '1.000001',
        '深证成指': '0.399001',
        '创业板指': '0.399006',
        '科创50':   '1.000688',
        '沪深300':  '1.000300',
        '中证500':  '1.000905',
        '中证1000': '2.899050',
    }

    fields = 'f43,f44,f45,f46,f47,f48,f60,f116,f117,f170,f171'

    def _normalize_price(val):
        """启发式检测东方财富价格是否为整数编码（需要/100）"""
        v = safe_float(val)
        if v is not None and abs(v) > 100000:
            v = v / 100.0
        return v

    def _normalize_pct(val):
        """启发式检测涨跌幅是否为整数编码"""
        v = safe_float(val)
        if v is not None and abs(v) > 15:
            v = v / 100.0
        return v

    for name, secid in indices.items():
        url = f'https://push2.eastmoney.com/api/qt/stock/get?secid={secid}&fields={fields}'
        data = safe_get(url)
        if data and data.get('data'):
            d = data['data']
            result[name] = {
                'price': _normalize_price(d.get('f43')),
                'high': _normalize_price(d.get('f44')),
                'low': _normalize_price(d.get('f45')),
                'open': _normalize_price(d.get('f46')),
                'prev_close': _normalize_price(d.get('f60')),
                'volume': safe_int(d.get('f47')),
                'amount': safe_float(d.get('f48')),
                'change_pct': _normalize_pct(d.get('f170')),
                'change_amt': _normalize_price(d.get('f171')),
                'total_mcap': safe_float(d.get('f116')),
                'float_mcap': safe_float(d.get('f117')),
            }
            print(f'  {name}: {result[name]["price"]} ({fmt_pct(result[name]["change_pct"])})')
        else:
            print(f'  {name}: 获取失败')
        time.sleep(0.3)

    # 沪深两市合计成交额
    total_amount = 0
    if result.get('上证指数'):
        total_amount += result['上证指数'].get('amount', 0)
    if result.get('深证成指'):
        total_amount += result['深证成指'].get('amount', 0)
    result['_total_amount'] = total_amount

    return result


def collect_northbound():
    """Step 2: 北向资金 — 沪股通/深股通实时净流入"""
    print('[2/10] 北向资金...')
    result = {'summary': None, 'timeline': []}

    url = 'https://push2.eastmoney.com/api/qt/kamt.rtmin/get?fields1=f1,f2,f3,f4&fields2=f51,f52,f53,f54,f55,f56'
    data = safe_get(url)
    if data and data.get('data'):
        d = data['data']
        s1 = safe_float(d.get('s2n_hk2sh'))
        s2 = safe_float(d.get('s2n_hk2sz'))

        result['summary'] = {
            'total_net': s1 + s2,
            'sh_net': s1,
            'sz_net': s2,
            'date': d.get('s2nDate', ''),
        }

        if d.get('s2n'):
            for item in d['s2n']:
                parts = item.split(',')
                if len(parts) >= 4:
                    result['timeline'].append({
                        'time': parts[0],
                        'sh_net': safe_float(parts[1]),
                        'sz_net': safe_float(parts[2]),
                        'total_net': safe_float(parts[3]),
                    })
        print(f'  北向合计: {fmt_num(result["summary"]["total_net"])}')
    else:
        print(f'  北向资金: 获取失败')

    # 近期北向资金趋势（近10日）
    hist_url = ('https://datacenter-web.eastmoney.com/api/data/v1/get?'
                'reportName=RPT_MUTUAL_DEAL_HISTORY&columns=ALL&pageSize=10'
                '&sortColumns=TRADE_DATE&sortTypes=-1&filter=(MUTUAL_TYPE=%22001%22)')
    hist = safe_get(hist_url)
    if hist and hist.get('result') and hist['result'].get('data'):
        result['history'] = []
        for row in hist['result']['data'][:10]:
            result['history'].append({
                'date': row.get('TRADE_DATE', '')[:10],
                'net_buy': safe_float(row.get('NET_BUY_AMT')),
                'buy_amt': safe_float(row.get('BUY_AMT')),
                'sell_amt': safe_float(row.get('SELL_AMT')),
            })
        print(f'  近10日历史: {len(result["history"])}条')

    return result


def collect_margin_data():
    """Step 3: 两融数据 — 融资融券余额"""
    print('[3/10] 两融数据...')
    result = {'latest': None, 'history': []}

    sh_url = ('https://datacenter-web.eastmoney.com/api/data/v1/get?'
              'reportName=RPT_MARGIN_SH&columns=ALL&pageSize=5'
              '&sortColumns=TRADE_DATE&sortTypes=-1')
    sh_data = safe_get(sh_url)

    sz_url = ('https://datacenter-web.eastmoney.com/api/data/v1/get?'
              'reportName=RPT_MARGIN_SZ&columns=ALL&pageSize=5'
              '&sortColumns=TRADE_DATE&sortTypes=-1')
    sz_data = safe_get(sz_url)

    sh_rows = []
    sz_rows = []
    if sh_data and sh_data.get('result') and sh_data['result'].get('data'):
        sh_rows = sh_data['result']['data']
    if sz_data and sz_data.get('result') and sz_data['result'].get('data'):
        sz_rows = sz_data['result']['data']

    if sh_rows or sz_rows:
        sh_latest = sh_rows[0] if sh_rows else {}
        sz_latest = sz_rows[0] if sz_rows else {}

        sh_rzye = safe_float(sh_latest.get('RZYE', 0))
        sh_rzmre = safe_float(sh_latest.get('RZMRE', 0))
        sh_rqye = safe_float(sh_latest.get('RQYE', 0))
        sz_rzye = safe_float(sz_latest.get('RZYE', 0))
        sz_rzmre = safe_float(sz_latest.get('RZMRE', 0))
        sz_rqye = safe_float(sz_latest.get('RQYE', 0))

        total_rzye = sh_rzye + sz_rzye
        total_rzmre = sh_rzmre + sz_rzmre
        total_rqye = sh_rqye + sz_rqye

        result['latest'] = {
            'date': sh_latest.get('TRADE_DATE', sz_latest.get('TRADE_DATE', ''))[:10],
            'total_rzye': total_rzye,
            'total_rzmre': total_rzmre,
            'total_rqye': total_rqye,
            'sh_rzye': sh_rzye,
            'sz_rzye': sz_rzye,
            'total_margin': total_rzye + total_rqye,
        }
        print(f'  融资余额: {fmt_num(total_rzye)}  融券余额: {fmt_num(total_rqye)}')

        for i in range(min(len(sh_rows), len(sz_rows), 5)):
            sh_r = sh_rows[i] if i < len(sh_rows) else {}
            sz_r = sz_rows[i] if i < len(sz_rows) else {}
            result['history'].append({
                'date': sh_r.get('TRADE_DATE', sz_r.get('TRADE_DATE', ''))[:10],
                'total_rzye': safe_float(sh_r.get('RZYE', 0)) + safe_float(sz_r.get('RZYE', 0)),
                'total_rzmre': safe_float(sh_r.get('RZMRE', 0)) + safe_float(sz_r.get('RZMRE', 0)),
            })
    else:
        print(f'  两融数据: 获取失败')

    return result


def collect_limit_stats():
    """Step 4: 涨跌停统计 — 涨停/跌停家数、连板、封板率

    注意：早间运行时今日数据不存在，自动回溯到最近交易日。
    """
    print('[4/10] 涨跌停统计...')
    result = {'zt': None, 'dt': None, 'data_date': None}

    # 尝试最近4天（处理周末+早间运行）
    for days_back in range(4):
        check_date = (NOW_BJT - timedelta(days=days_back)).strftime('%Y%m%d')
        zt_url = f'https://push2ex.eastmoney.com/getYuBaoData?type=zt&date={check_date}'
        zt_data = safe_get(zt_url, timeout=10)
        if zt_data and zt_data.get('data') and zt_data['data'].get('pool'):
            result['data_date'] = check_date
            d = zt_data['data']
            pool = d.get('pool', [])
            lianban_counts = {}
            first_zt_count = 0
            for stock in pool:
                lb = safe_int(stock.get('lbc', 1))
                lianban_counts[lb] = lianban_counts.get(lb, 0) + 1
                if lb == 1:
                    first_zt_count += 1

            zbc = safe_int(d.get('zbc', 0))
            total_zt = len(pool)
            fengban_rate = total_zt / (total_zt + zbc) * 100 if (total_zt + zbc) > 0 else 0

            result['zt'] = {
                'count': total_zt,
                'zbc': zbc,
                'fengban_rate': fengban_rate,
                'first_zt': first_zt_count,
                'lianban': lianban_counts,
                'max_lianban': max(lianban_counts.keys()) if lianban_counts else 0,
                'top_stocks': [],
            }

            top_lb = sorted(pool, key=lambda x: safe_int(x.get('lbc', 1)), reverse=True)
            for s in top_lb[:8]:
                result['zt']['top_stocks'].append({
                    'name': s.get('n', ''),
                    'code': s.get('c', ''),
                    'lbc': safe_int(s.get('lbc', 1)),
                    'fund': safe_float(s.get('fund', 0)),
                    'amount': safe_float(s.get('amount', 0)),
                    'ftime': s.get('ftime', ''),
                })

            print(f'  涨停({check_date}): {total_zt}家  炸板: {zbc}家  封板率: {fengban_rate:.0f}%')
            break
    else:
        print(f'  涨停数据: 最近4天均无数据')

    # 跌停数据（使用同一日期）
    dt_date = result.get('data_date', TODAY_YYYYMMDD)
    dt_url = f'https://push2ex.eastmoney.com/getYuBaoData?type=dt&date={dt_date}'
    dt_data = safe_get(dt_url, timeout=10)
    if dt_data and dt_data.get('data'):
        d = dt_data['data']
        pool = d.get('pool', [])
        result['dt'] = {
            'count': len(pool),
            'top_stocks': [],
        }
        for s in pool[:5]:
            result['dt']['top_stocks'].append({
                'name': s.get('n', ''),
                'code': s.get('c', ''),
                'amount': safe_float(s.get('amount', 0)),
            })
        print(f'  跌停: {len(pool)}家')
    else:
        print(f'  跌停数据: 获取失败')

    return result


def collect_sector_flow():
    """Step 5: 板块资金流 — 行业板块资金净流入"""
    print('[5/10] 板块资金流...')
    result = {'industry': [], 'concept': []}

    # 行业板块
    ind_url = ('https://push2.eastmoney.com/api/qt/clist/get?'
               'pn=1&pz=20&fid=f62&po=1&fs=m:90+t:2'
               '&fields=f3,f12,f14,f62,f184,f66,f69,f72,f75,f78,f81,f84,f87')
    ind_data = safe_get(ind_url)
    if ind_data and ind_data.get('data') and ind_data['data'].get('diff'):
        diff = ind_data['data']['diff']
        items = diff.values() if isinstance(diff, dict) else diff
        for item in items:
            if not isinstance(item, dict):
                continue
            result['industry'].append({
                'name': item.get('f14', ''),
                'code': item.get('f12', ''),
                'change_pct': safe_float(item.get('f3')),
                'main_net': safe_float(item.get('f62')),
                'main_pct': safe_float(item.get('f184')),
                'super_large_net': safe_float(item.get('f66')),
                'large_net': safe_float(item.get('f72')),
                'medium_net': safe_float(item.get('f78')),
                'small_net': safe_float(item.get('f84')),
            })
        print(f'  行业板块: {len(result["industry"])}个')
        if result['industry']:
            top = result['industry'][0]
            print(f'  主力最多流入: {top["name"]} {fmt_num(top["main_net"])}')
    else:
        print(f'  行业板块: 获取失败')

    time.sleep(0.5)

    # 概念板块
    con_url = ('https://push2.eastmoney.com/api/qt/clist/get?'
               'pn=1&pz=20&fid=f62&po=1&fs=m:90+t:3'
               '&fields=f3,f12,f14,f62,f184,f66,f69,f72,f75')
    con_data = safe_get(con_url)
    if con_data and con_data.get('data') and con_data['data'].get('diff'):
        diff = con_data['data']['diff']
        items = diff.values() if isinstance(diff, dict) else diff
        for item in items:
            if not isinstance(item, dict):
                continue
            result['concept'].append({
                'name': item.get('f14', ''),
                'code': item.get('f12', ''),
                'change_pct': safe_float(item.get('f3')),
                'main_net': safe_float(item.get('f62')),
                'main_pct': safe_float(item.get('f184')),
                'super_large_net': safe_float(item.get('f66')),
                'large_net': safe_float(item.get('f72')),
            })
        print(f'  概念板块: {len(result["concept"])}个')
    else:
        print(f'  概念板块: 获取失败')

    # 资金流出最多的行业板块
    out_url = ('https://push2.eastmoney.com/api/qt/clist/get?'
               'pn=1&pz=10&fid=f62&po=0&fs=m:90+t:2'
               '&fields=f3,f12,f14,f62,f184')
    out_data = safe_get(out_url)
    if out_data and out_data.get('data') and out_data['data'].get('diff'):
        result['industry_outflow'] = []
        diff = out_data['data']['diff']
        items = diff.values() if isinstance(diff, dict) else diff
        for item in items:
            if not isinstance(item, dict):
                continue
            result['industry_outflow'].append({
                'name': item.get('f14', ''),
                'change_pct': safe_float(item.get('f3')),
                'main_net': safe_float(item.get('f62')),
            })

    return result


def collect_news():
    """Step 6: A股新闻 — 财联社电报 + 东方财富要闻"""
    print('[6/10] A股新闻...')
    news = []

    # 财联社电报
    try:
        cls_url = ('https://www.cls.cn/nodeapi/updateTelegraph?'
                   'app=CailianpressWeb&os=web&sv=8.4.6&rn=20')
        cls_data = safe_get(cls_url, timeout=15)
        if cls_data and cls_data.get('data') and cls_data['data'].get('roll_data'):
            for item in cls_data['data']['roll_data'][:15]:
                title = item.get('title', '') or item.get('brief', '') or ''
                content = item.get('content', '') or ''
                content = re.sub(r'<[^>]+>', '', content)
                if title or content:
                    news.append({
                        'source': '财联社',
                        'title': title[:100] if title else content[:100],
                        'desc': content[:200] if content else '',
                        'time': item.get('ctime', ''),
                        'importance': safe_int(item.get('level', 0)),
                    })
            print(f'  财联社: {len(news)}条')
    except Exception as e:
        print(f'  财联社: 获取失败 {e}')

    # 东方财富要闻
    try:
        em_url = ('https://np-listapi.eastmoney.com/comm/wap/getListInfo?'
                  'client=wap&type=1&mession=&pageSize=20&pageNo=1&fields=title,summary,showTime')
        em_data = safe_get(em_url, timeout=15)
        if em_data and em_data.get('data') and em_data['data'].get('list'):
            em_count = 0
            for item in em_data['data']['list'][:15]:
                title = item.get('title', '') or item.get('mediaName', '')
                desc = item.get('summary', '') or ''
                if title:
                    news.append({
                        'source': '东方财富',
                        'title': title[:100],
                        'desc': desc[:200],
                        'time': item.get('showTime', ''),
                        'importance': 0,
                    })
                    em_count += 1
            print(f'  东方财富: {em_count}条')
    except Exception as e:
        print(f'  东方财富: 获取失败 {e}')

    return news


# ============================================================
# 数据采集函数（Step 7-10: 新增大宗商品+宏观+全球数据）
# ============================================================

def collect_domestic_futures():
    """Step 7: 国内期货主力合约 — 黑色/有色/贵金属/能源/农产品/化工

    通过东方财富API获取SHFE/DCE/CZCE/INE/GFEX全市场期货行情，
    按品种名匹配关注列表，每品种取成交额最大的合约（即主力合约）。
    """
    print('[7/10] 国内期货...')
    result = {'contracts': [], 'categories': {}}

    # 关注的主力品种（名称关键词 → 分类）
    KEY_COMMODITIES = {
        # 黑色系（钢铁产业链，中国基建指标）
        '螺纹': '黑色系', '热卷': '黑色系', '铁矿': '黑色系',
        '焦煤': '黑色系', '焦炭': '黑色系', '不锈钢': '黑色系',
        # 有色金属（工业活动+新能源）
        '沪铜': '有色金属', '沪铝': '有色金属', '沪锌': '有色金属',
        '沪镍': '有色金属', '沪锡': '有色金属',
        # 贵金属（避险+通胀预期）
        '沪金': '贵金属', '沪银': '贵金属',
        # 能源（电力成本=矿场运营成本）
        '原油': '能源', '燃油': '能源', '液化气': '能源',
        # 农产品（通胀+消费）
        '豆粕': '农产品', '豆油': '农产品', '棕榈': '农产品',
        '玉米': '农产品', '生猪': '农产品', '白糖': '农产品',
        # 化工（中下游景气度）
        '甲醇': '化工', '纯碱': '化工', 'PTA': '化工',
        '聚丙烯': '化工', '乙二醇': '化工',
    }

    # 全市场期货行情：m:113=SHFE, m:114=DCE, m:115=CZCE, m:142=INE, m:225=GFEX
    url = ('https://push2.eastmoney.com/api/qt/clist/get?'
           'pn=1&pz=500'
           '&fs=m:113,m:114,m:115,m:142,m:225'
           '&fields=f2,f3,f4,f5,f6,f7,f12,f13,f14,f15,f16,f17,f18'
           '&fid=f6&po=1')

    data = safe_get(url, timeout=15)
    if not data or not data.get('data') or not data['data'].get('diff'):
        print('  期货数据获取失败')
        return result

    diff = data['data']['diff']
    items = diff.values() if isinstance(diff, dict) else diff

    # 按品种名匹配，每品种只取成交额最大的合约（已按f6排序）
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get('f14', '')

        matched_cat = None
        matched_key = None
        for key, cat in KEY_COMMODITIES.items():
            if key in name:
                matched_cat = cat
                matched_key = key
                break

        if matched_cat and matched_key not in seen:
            seen.add(matched_key)
            price = safe_float(item.get('f2'))
            change_pct = safe_float(item.get('f3'))
            # 东方财富期货涨跌幅：一般直接返回百分比值，但个别情况*100编码
            if change_pct is not None and abs(change_pct) > 30:
                change_pct = change_pct / 100.0

            contract = {
                'name': name,
                'code': item.get('f12', ''),
                'category': matched_cat,
                'price': price,
                'change_pct': change_pct,
                'change_amt': safe_float(item.get('f4')),
                'volume': safe_int(item.get('f5')),
                'amount': safe_float(item.get('f6')),
                'amplitude': safe_float(item.get('f7')),
                'high': safe_float(item.get('f15')),
                'low': safe_float(item.get('f16')),
                'open': safe_float(item.get('f17')),
                'prev_close': safe_float(item.get('f18')),
            }
            result['contracts'].append(contract)

            if matched_cat not in result['categories']:
                result['categories'][matched_cat] = []
            result['categories'][matched_cat].append(contract)

    print(f'  获取 {len(result["contracts"])} 个主力合约')
    for cat, contracts in sorted(result['categories'].items()):
        names = ', '.join(c['name'] for c in contracts[:3])
        rest = f'...+{len(contracts)-3}' if len(contracts) > 3 else ''
        print(f'    {cat}: {names}{rest}')

    return result


def collect_china_macro():
    """Step 8: 中国宏观经济 — CPI/PPI/PMI/M2/Shibor/USD-CNY

    使用东方财富数据中心API获取最新宏观经济指标，
    数据为月度发布（CPI/PPI/PMI每月中旬，M2每月中旬），
    此处获取最新一期数据用于趋势判断。
    """
    print('[8/10] 中国宏观...')
    result = {'indicators': {}, 'shibor': None, 'usdcny': None}

    # === CPI (月度，同比/环比) ===
    try:
        cpi_url = ('https://datacenter-web.eastmoney.com/api/data/v1/get?'
                   'reportName=RPT_ECONOMY_CPI&columns=REPORT_DATE,NATIONAL_SAME,NATIONAL_BASE,NATIONAL_SEQUENTIAL'
                   '&pageSize=6&sortColumns=REPORT_DATE&sortTypes=-1')
        cpi = safe_get(cpi_url, timeout=15)
        if cpi and cpi.get('result') and cpi['result'].get('data'):
            rows = cpi['result']['data']
            if rows:
                latest = rows[0]
                result['indicators']['CPI'] = {
                    'date': latest.get('REPORT_DATE', '')[:10],
                    'yoy': safe_float(latest.get('NATIONAL_SAME')),
                    'mom': safe_float(latest.get('NATIONAL_SEQUENTIAL')),
                }
                # 近6月趋势
                result['indicators']['CPI']['trend'] = [
                    {'date': r.get('REPORT_DATE', '')[:7], 'yoy': safe_float(r.get('NATIONAL_SAME'))}
                    for r in rows[:6]
                ]
                print(f'  CPI: 同比{result["indicators"]["CPI"]["yoy"]}%')
    except Exception as e:
        print(f'  CPI获取失败: {e}')

    # === PPI (月度，工业品出厂价格) ===
    try:
        ppi_url = ('https://datacenter-web.eastmoney.com/api/data/v1/get?'
                   'reportName=RPT_ECONOMY_PPI&columns=REPORT_DATE,NATIONAL_SAME,NATIONAL_SEQUENTIAL'
                   '&pageSize=6&sortColumns=REPORT_DATE&sortTypes=-1')
        ppi = safe_get(ppi_url, timeout=15)
        if ppi and ppi.get('result') and ppi['result'].get('data'):
            rows = ppi['result']['data']
            if rows:
                latest = rows[0]
                result['indicators']['PPI'] = {
                    'date': latest.get('REPORT_DATE', '')[:10],
                    'yoy': safe_float(latest.get('NATIONAL_SAME')),
                    'mom': safe_float(latest.get('NATIONAL_SEQUENTIAL')),
                }
                result['indicators']['PPI']['trend'] = [
                    {'date': r.get('REPORT_DATE', '')[:7], 'yoy': safe_float(r.get('NATIONAL_SAME'))}
                    for r in rows[:6]
                ]
                print(f'  PPI: 同比{result["indicators"]["PPI"]["yoy"]}%')
    except Exception as e:
        print(f'  PPI获取失败: {e}')

    # === PMI (月度，制造业+非制造业) ===
    try:
        pmi_url = ('https://datacenter-web.eastmoney.com/api/data/v1/get?'
                   'reportName=RPT_ECONOMY_PMI&columns=REPORT_DATE,MAKE_INDEX,NMAKE_INDEX'
                   '&pageSize=6&sortColumns=REPORT_DATE&sortTypes=-1')
        pmi = safe_get(pmi_url, timeout=15)
        if pmi and pmi.get('result') and pmi['result'].get('data'):
            rows = pmi['result']['data']
            if rows:
                latest = rows[0]
                result['indicators']['PMI'] = {
                    'date': latest.get('REPORT_DATE', '')[:10],
                    'manufacturing': safe_float(latest.get('MAKE_INDEX')),
                    'non_manufacturing': safe_float(latest.get('NMAKE_INDEX')),
                }
                result['indicators']['PMI']['trend'] = [
                    {'date': r.get('REPORT_DATE', '')[:7], 'val': safe_float(r.get('MAKE_INDEX'))}
                    for r in rows[:6]
                ]
                pmi_val = result['indicators']['PMI']['manufacturing']
                emoji = '🟢' if pmi_val and pmi_val >= 50 else '🔴'
                print(f'  PMI: {emoji} 制造业{pmi_val}')
    except Exception as e:
        print(f'  PMI获取失败: {e}')

    # === M2/M1货币供应 (月度) ===
    try:
        m2_url = ('https://datacenter-web.eastmoney.com/api/data/v1/get?'
                  'reportName=RPT_ECONOMY_CURRENCY_SUPPLY&columns=REPORT_DATE,BASIC_CURRENCY,BASIC_CURRENCY_SAME,'
                  'CURRENCY_SUPPLY,CURRENCY_SUPPLY_SAME,FREE_CASH,FREE_CASH_SAME'
                  '&pageSize=3&sortColumns=REPORT_DATE&sortTypes=-1')
        m2 = safe_get(m2_url, timeout=15)
        if m2 and m2.get('result') and m2['result'].get('data'):
            rows = m2['result']['data']
            if rows:
                latest = rows[0]
                result['indicators']['M2'] = {
                    'date': latest.get('REPORT_DATE', '')[:10],
                    'm2_yoy': safe_float(latest.get('CURRENCY_SUPPLY_SAME')),
                    'm1_yoy': safe_float(latest.get('BASIC_CURRENCY_SAME')),
                    'm0_yoy': safe_float(latest.get('FREE_CASH_SAME')),
                }
                print(f'  M2同比: {result["indicators"]["M2"]["m2_yoy"]}%  M1同比: {result["indicators"]["M2"]["m1_yoy"]}%')
    except Exception as e:
        print(f'  M2获取失败: {e}')

    # === USD/CNY 汇率 ===
    try:
        fx_url = ('https://push2.eastmoney.com/api/qt/stock/get?'
                  'secid=119.USDCNY&fields=f43,f44,f45,f46,f60,f170,f171')
        fx = safe_get(fx_url, timeout=10)
        if fx and fx.get('data'):
            d = fx['data']
            rate = safe_float(d.get('f43'))
            # 东方财富外汇有时*10000编码（USDCNY约7.2，如果>100说明被编码了）
            if rate and rate > 100:
                rate = rate / 10000.0
            change_pct = safe_float(d.get('f170'))
            if change_pct and abs(change_pct) > 10:
                change_pct = change_pct / 100.0
            result['usdcny'] = {
                'rate': rate,
                'change_pct': change_pct,
            }
            print(f'  USD/CNY: {rate:.4f} ({fmt_pct(change_pct)})')
    except Exception as e:
        print(f'  USD/CNY获取失败: {e}')

    # === Shibor (银行间同业拆借利率，隔夜) ===
    try:
        shibor_url = ('https://datacenter-web.eastmoney.com/api/data/v1/get?'
                      'reportName=RPT_IMP_INTRESTRATENEW&columns=REPORT_DATE,IR_RATE,CHANGE,CHANGE_RATE'
                      '&filter=(MARKET_CODE=%22001%22)(INDICATOR_ID=%22001%22)'
                      '&pageSize=5&sortColumns=REPORT_DATE&sortTypes=-1')
        shibor = safe_get(shibor_url, timeout=10)
        if shibor and shibor.get('result') and shibor['result'].get('data'):
            rows = shibor['result']['data']
            if rows:
                latest = rows[0]
                result['shibor'] = {
                    'date': latest.get('REPORT_DATE', '')[:10],
                    'rate': safe_float(latest.get('IR_RATE')),
                    'change': safe_float(latest.get('CHANGE')),
                }
                print(f'  Shibor O/N: {result["shibor"]["rate"]}%')
    except Exception as e:
        print(f'  Shibor获取失败: {e}')

    return result


def collect_global_overnight():
    """Step 9: 全球隔夜市场 — 美股/亚太/美债/黄金/原油/DXY (Yahoo Finance)

    早间简报的关键数据：隔夜外盘表现直接影响今日A股开盘。
    """
    print('[9/10] 全球隔夜市场...')
    result = {}

    tickers = {
        # 美股三大指数
        '^GSPC': '标普500',
        '^IXIC': '纳斯达克',
        '^DJI': '道琼斯',
        # 亚太
        '^N225': '日经225',
        '^HSI': '恒生指数',
        # 美元
        'DX-Y.NYB': '美元指数DXY',
        # 美债
        '^TNX': '美债10Y收益率',
        # 商品
        'GC=F': 'COMEX黄金',
        'CL=F': 'WTI原油',
        'SI=F': 'COMEX白银',
    }

    for ticker, name in tickers.items():
        try:
            url = f'https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=2d'
            data = safe_get(url, timeout=10)
            if data and data.get('chart') and data['chart'].get('result'):
                r = data['chart']['result'][0]
                meta = r.get('meta', {})
                price = safe_float(meta.get('regularMarketPrice'))
                prev = safe_float(meta.get('chartPreviousClose') or meta.get('previousClose'))
                change_pct = ((price - prev) / prev * 100) if price and prev and prev != 0 else None
                result[name] = {
                    'price': price,
                    'prev_close': prev,
                    'change_pct': change_pct,
                }
                print(f'  {name}: {price} ({fmt_pct(change_pct) if change_pct else "N/A"})')
            else:
                print(f'  {name}: 获取失败')
        except Exception as e:
            print(f'  {name}: {e}')
        time.sleep(0.3)

    return result


def collect_economic_calendar():
    """Step 10: 经济日历 — 近期重要数据发布/政策事件"""
    print('[10/10] 经济日历...')
    events = []

    # 东方财富经济数据日历
    try:
        cal_url = ('https://datacenter-web.eastmoney.com/api/data/v1/get?'
                   'reportName=RPT_ECONOMICDATA_RELEASES&columns=EMTITLE,EMVALUE,EMBASCI,REPORT_DATE,COUNTRY'
                   '&filter=(COUNTRY=%22%E4%B8%AD%E5%9B%BD%22)'
                   '&pageSize=10&sortColumns=REPORT_DATE&sortTypes=-1')
        cal = safe_get(cal_url, timeout=10)
        if cal and cal.get('result') and cal['result'].get('data'):
            for row in cal['result']['data'][:10]:
                events.append({
                    'title': row.get('EMTITLE', ''),
                    'value': row.get('EMVALUE', ''),
                    'prev': row.get('EMBASCI', ''),
                    'date': row.get('REPORT_DATE', '')[:10],
                })
            print(f'  经济日历: {len(events)}条')
    except Exception as e:
        print(f'  经济日历获取失败: {e}')

    return events


# ============================================================
# 数据格式化
# ============================================================

def format_data_context(indices, northbound, margin, limits, sectors, news,
                        futures, macro, global_mkt, calendar):
    """将所有数据格式化为LLM的输入上下文"""
    sections = []

    # 时间基准
    now_bjt = datetime.now(BJT)
    s = '## 时间基准\n'
    s += f'当前北京时间: {now_bjt.strftime("%Y-%m-%d %H:%M")} (BJT/UTC+8)\n'
    if now_bjt.hour < 9:
        s += f'这是盘前晨间简报。市场数据为上一交易日收盘数据，全球市场为隔夜最新。\n'
    else:
        s += f'以下数据为A股{now_bjt.strftime("%Y-%m-%d")}最新数据。\n'
    s += f'"今日"指北京时间{now_bjt.strftime("%Y-%m-%d")}，'
    s += f'"昨日"指{(now_bjt - timedelta(days=1)).strftime("%Y-%m-%d")}。\n'
    sections.append(s)

    # === 全球隔夜市场（早间简报最先看外盘）===
    if global_mkt:
        s = '## 全球隔夜市场\n'
        for name in ['标普500', '纳斯达克', '道琼斯', '日经225', '恒生指数',
                      '美元指数DXY', '美债10Y收益率', 'COMEX黄金', 'WTI原油', 'COMEX白银']:
            if name in global_mkt:
                g = global_mkt[name]
                emoji = '🟢' if g.get('change_pct') and g['change_pct'] > 0 else '🔴'
                pct_str = fmt_pct(g['change_pct']) if g.get('change_pct') else 'N/A'
                s += f'{emoji} {name}: {g["price"]} ({pct_str})\n'

        # 关键信号提取
        sp500_chg = global_mkt.get('标普500', {}).get('change_pct')
        nasdaq_chg = global_mkt.get('纳斯达克', {}).get('change_pct')
        if sp500_chg and abs(sp500_chg) > 1:
            s += f'\n⚡ 美股大幅{"上涨" if sp500_chg > 0 else "下跌"} {fmt_pct(sp500_chg)}，今日A股开盘预计受影响\n'
        dxy = global_mkt.get('美元指数DXY', {}).get('price')
        if dxy:
            if dxy > 105:
                s += f'⚠️ 美元指数{dxy}偏强，资金回流美国压力\n'
            elif dxy < 100:
                s += f'🟢 美元指数{dxy}偏弱，新兴市场资金宽松\n'
        sections.append(s)

    # === 大盘指数 ===
    s = '## 大盘指数\n'
    for name in ['上证指数', '深证成指', '创业板指', '科创50', '沪深300', '中证500', '中证1000']:
        if indices.get(name):
            d = indices[name]
            emoji = '🟢' if d['change_pct'] > 0 else ('🔴' if d['change_pct'] < 0 else '🟡')
            s += f'{emoji} {name}: {d["price"]:.2f} ({fmt_pct(d["change_pct"])})'
            s += f'  成交额: {fmt_num(d["amount"])}\n'
            s += f'   开{d["open"]:.2f} 高{d["high"]:.2f} 低{d["low"]:.2f}'
            if d.get('total_mcap'):
                s += f'  总市值: {fmt_num(d["total_mcap"])}'
            s += '\n'
    total_amt = indices.get('_total_amount', 0)
    if total_amt > 0:
        s += f'\n沪深两市合计成交: {fmt_num(total_amt)}\n'
        if total_amt < 6e11:
            s += '⚠️ 成交额低于6000亿，市场缩量\n'
        elif total_amt > 1.2e12:
            s += '🔥 成交额突破1.2万亿，市场放量\n'
        elif total_amt > 1e12:
            s += '成交额破万亿，活跃\n'
    sections.append(s)

    # === 北向资金 ===
    s = '## 北向资金（Smart Money）\n'
    if northbound.get('summary'):
        nb = northbound['summary']
        total = nb['total_net']
        emoji = '🟢' if total > 0 else '🔴'
        s += f'{emoji} 今日北向净流入: {fmt_num(total)}\n'
        s += f'  沪股通: {fmt_num(nb["sh_net"])}  深股通: {fmt_num(nb["sz_net"])}\n'
    if northbound.get('history'):
        s += '\n近期趋势:\n'
        total_5d = 0
        for h in northbound['history'][:5]:
            nb_net = h['net_buy']
            total_5d += nb_net
            emoji = '🟢' if nb_net > 0 else '🔴'
            s += f'  {h["date"]}: {emoji} {fmt_num(nb_net)}\n'
        s += f'  近5日累计: {fmt_num(total_5d)}\n'
        if total_5d > 10e8:
            s += '  → 外资持续流入，看好A股\n'
        elif total_5d < -10e8:
            s += '  → 外资持续流出，风险偏好下降\n'
    if northbound.get('timeline'):
        tl = northbound['timeline']
        if len(tl) >= 2:
            late_data = [t for t in tl if t['time'] >= '14:30']
            if late_data:
                late_net = late_data[-1]['total_net'] - late_data[0]['total_net']
                if abs(late_net) > 1e8:
                    s += f'\n尾盘(14:30后)净变化: {fmt_num(late_net)}'
                    if late_net > 0:
                        s += '（尾盘加速流入，看多信号）\n'
                    else:
                        s += '（尾盘加速流出，看空信号）\n'
    sections.append(s)

    # === 两融数据 ===
    s = '## 两融数据（杠杆资金）\n'
    if margin.get('latest'):
        m = margin['latest']
        s += f'日期: {m["date"]}\n'
        s += f'融资余额: {fmt_num(m["total_rzye"])} (沪{fmt_num(m["sh_rzye"])} + 深{fmt_num(m["sz_rzye"])})\n'
        s += f'融资买入额: {fmt_num(m["total_rzmre"])}\n'
        s += f'融券余额: {fmt_num(m["total_rqye"])}\n'
        s += f'两融余额合计: {fmt_num(m["total_margin"])}\n'

        if margin.get('history') and len(margin['history']) >= 2:
            today_rzye = margin['history'][0]['total_rzye']
            yesterday_rzye = margin['history'][1]['total_rzye']
            change = today_rzye - yesterday_rzye
            s += f'\n融资余额日变化: {fmt_num(change)}'
            if change > 0:
                s += '（杠杆资金增加，市场偏积极）\n'
            else:
                s += '（杠杆资金减少，市场偏谨慎）\n'
    else:
        s += '数据未获取（可能收盘后延迟发布）\n'
    sections.append(s)

    # === 涨跌停 ===
    s = '## 涨跌停统计（市场情绪温度计）\n'
    if limits.get('data_date') and limits['data_date'] != TODAY_YYYYMMDD:
        s += f'⚠️ 数据日期: {limits["data_date"]}（盘前简报使用上一交易日数据）\n\n'
    if limits.get('zt'):
        zt = limits['zt']
        s += f'涨停: **{zt["count"]}家**  炸板: {zt["zbc"]}家  封板率: **{zt["fengban_rate"]:.0f}%**\n'
        s += f'首板: {zt["first_zt"]}家  最高连板: {zt["max_lianban"]}板\n'

        if zt['lianban']:
            s += '连板分布: '
            for lb in sorted(zt['lianban'].keys(), reverse=True):
                if lb >= 2:
                    s += f'{lb}板{zt["lianban"][lb]}家 '
            s += '\n'

        if zt['fengban_rate'] >= 75 and zt['count'] >= 50:
            s += '🔥 高温市场：涨停多+封板率高，赚钱效应强\n'
        elif zt['fengban_rate'] <= 40 or zt['count'] <= 20:
            s += '🥶 冰点市场：涨停少或封板率低，亏钱效应重\n'
        elif zt['fengban_rate'] >= 60:
            s += '🟡 温和偏暖：封板率及格，短线可操作\n'

        if zt.get('top_stocks'):
            s += '\n高度板个股:\n'
            for st in zt['top_stocks'][:5]:
                s += f'  {st["name"]}({st["code"]}) {st["lbc"]}板'
                if st.get('fund'):
                    s += f' 封单{fmt_num(st["fund"])}'
                s += '\n'

    if limits.get('dt'):
        dt = limits['dt']
        s += f'\n跌停: **{dt["count"]}家**\n'
        if dt.get('top_stocks'):
            for st in dt['top_stocks'][:3]:
                s += f'  {st["name"]}({st["code"]})\n'

    zt_count = (limits.get('zt') or {}).get('count', 0)
    dt_count = (limits.get('dt') or {}).get('count', 0)
    if zt_count > 0 and dt_count > 0:
        ratio = zt_count / dt_count
        s += f'\n涨跌停比: {zt_count}:{dt_count} = {ratio:.1f}:1'
        if ratio > 3:
            s += ' (多头强势)\n'
        elif ratio < 0.5:
            s += ' (空头碾压)\n'
        else:
            s += ' (多空平衡)\n'
    sections.append(s)

    # === 板块资金流 ===
    s = '## 板块资金流\n'
    if sectors.get('industry'):
        s += '**行业板块主力资金净流入 Top 10:**\n'
        for i, sec in enumerate(sectors['industry'][:10], 1):
            emoji = '🟢' if sec['main_net'] > 0 else '🔴'
            s += f'{i}. {emoji} {sec["name"]}: {fmt_num(sec["main_net"])} (涨幅{fmt_pct(sec["change_pct"])})\n'
    if sectors.get('industry_outflow'):
        s += '\n**行业板块主力净流出 Top 5:**\n'
        for i, sec in enumerate(sectors['industry_outflow'][:5], 1):
            s += f'{i}. 🔴 {sec["name"]}: {fmt_num(sec["main_net"])} (涨幅{fmt_pct(sec["change_pct"])})\n'
    if sectors.get('concept'):
        s += '\n**概念板块主力资金净流入 Top 10:**\n'
        for i, sec in enumerate(sectors['concept'][:10], 1):
            emoji = '🟢' if sec['main_net'] > 0 else '🔴'
            s += f'{i}. {emoji} {sec["name"]}: {fmt_num(sec["main_net"])} (涨幅{fmt_pct(sec["change_pct"])})\n'
    sections.append(s)

    # === 国内期货（新增） ===
    if futures and futures.get('contracts'):
        s = '## 国内期货主力合约\n'
        for cat in ['贵金属', '黑色系', '有色金属', '能源', '农产品', '化工']:
            contracts = futures['categories'].get(cat, [])
            if contracts:
                s += f'\n**{cat}:**\n'
                for c in contracts:
                    emoji = '🟢' if c['change_pct'] and c['change_pct'] > 0 else '🔴'
                    s += f'{emoji} {c["name"]}: {c["price"]} ({fmt_pct(c["change_pct"])})'
                    s += f'  成交额{fmt_num(c["amount"])}\n'

        # 大宗商品情绪总结
        up_count = sum(1 for c in futures['contracts'] if c.get('change_pct') and c['change_pct'] > 0)
        down_count = sum(1 for c in futures['contracts'] if c.get('change_pct') and c['change_pct'] < 0)
        total = len(futures['contracts'])
        if total > 0:
            s += f'\n商品多空: {up_count}涨 / {down_count}跌（共{total}品种）\n'
            if up_count > total * 0.7:
                s += '🔥 大宗商品整体偏强，通胀预期升温\n'
            elif down_count > total * 0.7:
                s += '🥶 大宗商品整体偏弱，需求担忧/通缩预期\n'
        sections.append(s)

    # === 中国宏观（新增） ===
    if macro:
        s = '## 中国宏观经济\n'

        # USD/CNY
        if macro.get('usdcny'):
            fx = macro['usdcny']
            s += f'**USD/CNY**: {fx["rate"]:.4f} ({fmt_pct(fx["change_pct"])})\n'
            if fx['rate'] and fx['rate'] > 7.3:
                s += '⚠️ 人民币偏弱（>7.30），关注PBOC维稳信号\n'
            elif fx['rate'] and fx['rate'] < 7.0:
                s += '🟢 人民币偏强（<7.00），外资流入有利\n'

        # Shibor
        if macro.get('shibor'):
            sh = macro['shibor']
            s += f'**Shibor隔夜**: {sh["rate"]}% (变动{sh["change"]:+.4f})\n'
            if sh['rate'] and sh['rate'] > 2.0:
                s += '⚠️ Shibor偏高，银行间流动性偏紧\n'
            elif sh['rate'] and sh['rate'] < 1.2:
                s += '🟢 Shibor偏低，流动性充裕\n'

        # 宏观指标
        indicators = macro.get('indicators', {})
        if indicators.get('CPI'):
            cpi = indicators['CPI']
            s += f'\n**CPI** ({cpi["date"][:7]}): 同比{fmt_pct(cpi["yoy"])}  环比{fmt_pct(cpi["mom"])}\n'
        if indicators.get('PPI'):
            ppi = indicators['PPI']
            s += f'**PPI** ({ppi["date"][:7]}): 同比{fmt_pct(ppi["yoy"])}  环比{fmt_pct(ppi["mom"])}\n'
            # CPI-PPI剪刀差
            cpi_yoy = indicators.get('CPI', {}).get('yoy')
            ppi_yoy = ppi.get('yoy')
            if cpi_yoy is not None and ppi_yoy is not None:
                scissor = cpi_yoy - ppi_yoy
                s += f'  CPI-PPI剪刀差: {scissor:+.1f}pp'
                if scissor > 3:
                    s += '（下游利润好，中上游承压）\n'
                elif scissor < -2:
                    s += '（上游涨价传导中，下游承压）\n'
                else:
                    s += '\n'
        if indicators.get('PMI'):
            pmi = indicators['PMI']
            mfg = pmi['manufacturing']
            emoji = '🟢' if mfg and mfg >= 50 else '🔴'
            s += f'**PMI** ({pmi["date"][:7]}): {emoji} 制造业{mfg}  非制造业{pmi["non_manufacturing"]}\n'
            if mfg:
                if mfg >= 50:
                    s += '  → 经济扩张区间\n'
                else:
                    s += '  → 经济收缩区间\n'
        if indicators.get('M2'):
            m2 = indicators['M2']
            s += f'**M2** ({m2["date"][:7]}): 同比{fmt_pct(m2["m2_yoy"])}  '
            s += f'M1同比{fmt_pct(m2["m1_yoy"])}\n'
            # M1-M2剪刀差
            if m2.get('m2_yoy') is not None and m2.get('m1_yoy') is not None:
                m_scissor = m2['m1_yoy'] - m2['m2_yoy']
                s += f'  M1-M2剪刀差: {m_scissor:+.1f}pp'
                if m_scissor > 0:
                    s += '（企业活化资金，经济活跃）\n'
                else:
                    s += '（资金沉淀定期，实体偏冷）\n'
        sections.append(s)

    # === 经济日历（新增） ===
    if calendar:
        s = '## 近期经济数据日历\n'
        for evt in calendar[:8]:
            s += f'- {evt["date"]} {evt["title"]}'
            if evt.get('value'):
                s += f': 实际{evt["value"]}'
            if evt.get('prev'):
                s += f' (前值{evt["prev"]})'
            s += '\n'
        sections.append(s)

    # === 新闻 ===
    s = '## 最近24h重要新闻\n'
    if news:
        sorted_news = sorted(news, key=lambda x: (-x.get('importance', 0), x.get('time', '')), reverse=False)
        seen = set()
        unique_news = []
        for n in sorted_news:
            title_key = n['title'][:20]
            if title_key not in seen:
                seen.add(title_key)
                unique_news.append(n)

        for i, n in enumerate(unique_news[:25], 1):
            s += f'{i}. [{n["source"]}] {n["title"]}\n'
            if n.get('desc'):
                s += f'   {n["desc"][:120]}\n'
    else:
        s += '无重要新闻\n'
    sections.append(s)

    return '\n'.join(sections)


# ============================================================
# LLM分析
# ============================================================

ASTOCK_ANALYST_SYSTEM = """你是国兴超链集团的A股+大宗商品首席分析师（CIO级别），拥有20年A股和商品期货投研经验。
你的服务对象是一位同时经营BTC矿场和进行期货交易（可多可空）的企业家董事长。
你同时具备顶级卖方研究和买方投资的双重视角，精通A股和国内商品期货。

## 你的分析风格
- 结论先行，先给判断再给逻辑
- 数据驱动，每个观点必须有数据支撑
- 因果链清晰，不做无逻辑的联想
- 直白敢判断，不做骑墙分析
- 政策敏感度高，懂中国市场的"中国特色"
- 跨市场联动：A股↔期货↔外盘↔宏观，寻找共振和背离

## 分析方法论

### 核心矛盾法
每天市场只有1-2个核心矛盾，找到它们，围绕它们展开所有分析。
例如："PMI重回荣枯线上方但北向资金连续流出——核心矛盾是经济复苏vs外资撤退，谁说了算？"

### 因果链推演（必须做）
事件 → 传导机制 → 一阶效应 → 二阶效应 → 对交易的影响
不要只说"X发生了"，要推演"X发生了 → 因为Y机制 → 导致Z → 这意味着..."

### 政策舆情因子（A股特色，必须分析）
- 证监会/国务院近期表态
- 官媒（新华社/人民日报/经济日报）论调
- 近期政策方向（宽松/收紧/结构性）
- IPO/再融资节奏变化
- 重要时间窗口（两会/经济工作会议/MLF/LPR等）

### 板块轮动分析
- 主力资金流向揭示的板块轮动方向
- 涨停板题材归类（哪些题材在发酵/退潮）
- 行业板块vs概念板块的资金分歧
- 大盘股(沪深300)vs小盘股(中证1000)的风格切换
- 连板股的身位分布

### 北向资金解读（Smart Money）
- 北向资金的方向通常领先1-3天
- 尾盘加速流入/流出是最强信号
- 沪股通vs深股通分歧暗示蓝筹vs成长偏好
- 连续5日同方向流动是趋势确认

### 大宗商品分析（期货视角，董事长做期货可多可空）
- **黑色系**（螺纹/铁矿/焦煤焦炭）：反映中国基建和房地产需求
  - 螺纹钢是最重要的中国经济晴雨表
  - 铁矿石受海运+澳巴供给影响
  - 焦煤焦炭反映钢厂利润
- **有色金属**（铜/铝/镍）：全球工业活动风向标
  - 铜被称为"铜博士"，领先经济周期
  - 铝反映中国电力和新能源需求
- **贵金属**（黄金/白银）：与BTC竞争的避险资产
  - 金价走势影响BTC的"数字黄金"叙事
  - 实际利率（名义利率-通胀预期）是黄金的核心驱动
- **能源**（原油/天然气）：直接影响矿场电力成本
  - 原油涨→电力成本涨→BTC矿场利润压缩
  - 国内成品油调价窗口
- **农产品**：反映通胀预期和消费
  - 猪肉价格是中国CPI权重最大的单项
  - 豆粕反映饲料成本→养殖成本→食品通胀

### 宏观经济分析框架
- **CPI/PPI剪刀差**：反映上下游利润分配
- **PMI荣枯线**：50以上扩张，以下收缩
- **M1-M2剪刀差**：企业活期存款变化反映实体经济活跃度
- **Shibor/DR007**：银行间流动性晴雨表
- **USD/CNY**：汇率影响北向资金和外贸型企业
- **隔夜外盘**：美股和美债收益率对A股开盘的映射

## 铁律
1. 不说"建议关注"、"值得关注" — 要说"应该做什么"
2. 不说"可能涨也可能跌" — 要给方向判断和概率
3. 不说"谨慎观望" — 要说在什么条件下做什么
4. 每个判断附带置信度（高/中/低）和逻辑链
5. 信号冲突时用⚡显式标注，分析哪个信号更可靠
6. 风险提示必须具体：不是"注意风险"，而是"如果X跌破Y，止损Z"
7. 数据必须量化到具体数字，不用"大幅"、"显著"等模糊词
8. 所有时间都用北京时间（BJT）
9. 期货分析必须给出方向（做多/做空/观望）和关键价位

## 输出格式要求（笔记本/iPad阅读，不限篇幅）
- 用 ## 大标题
- 关键数字全部**加粗**
- 每段不超过4行
- 段落间用空行分隔
- 正负面emoji：🔴负面 🟡中性 🟢正面 ⚡冲突
- 可以使用表格（用markdown表格语法）
- 分隔线 --- 分开大板块"""

ASTOCK_ANALYST_USER = """请基于以下A股和大宗商品数据，撰写今日晨间投研简报。

要求：
1. 先找到今日1-2个核心矛盾，作为整篇报告的主线
2. 深度分析，不是数据罗列——每个数据点都要解读"这意味着什么"
3. 所有判断给出因果链
4. A股和期货都给出明确的交易建议（方向+关键价位+止损）

## 报告结构

**第一部分：核心矛盾与结论**（最重要，放最前面）
- 今日核心矛盾是什么？
- 你的判断是什么？（方向+置信度+逻辑）
- 今日操作建议（A股+期货）

**第二部分：隔夜外盘影响**
- 美股/美债/黄金/原油隔夜表现
- 对今日A股开盘的影响映射
- 美元指数和汇率变化含义

**第三部分：大盘全景**
- 三大指数涨跌分析
- 成交额变化含义
- 大盘股vs小盘股风格判断
- 关键技术位

**第四部分：北向资金解读**
- 净流入/出分析
- 沪股通vs深股通分歧
- 结合近期趋势判断外资态度

**第五部分：情绪面（涨跌停分析）**
- 涨停家数+封板率情绪判断
- 连板梯队分析
- 核心题材归类

**第六部分：板块轮动**
- 资金净流入最多的行业 = 主线
- 资金净流出最多的行业 = 退潮
- 概念板块热点 = 短线题材

**第七部分：大宗商品深度**（董事长做期货，可多可空）
- 黑色系（螺纹/铁矿/焦煤焦炭）：基建需求判断
- 有色（铜/铝）：工业活动和新能源
- 贵金属（黄金/白银）：与BTC的跷跷板关系
- 能源（原油）：对矿场电力成本的影响
- 农产品：通胀预期
- 每个品种给出：方向判断 + 关键价位 + 交易建议

**第八部分：宏观环境**
- CPI/PPI趋势和剪刀差含义
- PMI景气度判断
- M1-M2剪刀差和流动性判断
- 汇率和Shibor流动性信号
- 近期重要数据/政策事件日历

**第九部分：杠杆资金（两融）**
- 融资余额变化和市场杠杆水平
- 两融趋势对后市的影响

**第十部分：重要新闻与政策**
- 筛选真正影响市场的新闻（不超过5条）
- 每条给出影响判断（利好/利空/中性 + 影响量级 + 影响板块）

**第十一部分：风险矩阵与机会**
- Top 3风险事件 + 触发条件 + 防御策略
- Top 3机会 + 入场条件 + 目标
- A股 + 期货分别给出风险/机会

--- 以下是市场数据 ---

{data_context}"""


def call_llm_analysis(data_context):
    """调用LLM深度分析（Claude Sonnet直连Anthropic API，备选GLM-5）"""
    from llm_engine import call_llm
    print('\n调用LLM深度分析（Claude Sonnet → GLM-5 fallback）...')
    user_msg = ASTOCK_ANALYST_USER.replace('{data_context}', data_context)
    return call_llm(
        system_prompt=ASTOCK_ANALYST_SYSTEM,
        user_prompt=user_msg,
        model='sonnet',
        fallback='glm5',
        max_tokens=10000,
        timeout=240,
    )


# ============================================================
# 推送
# ============================================================

def split_and_push(analysis_text, date_str):
    """将分析报告推送（Server酱）"""
    from notify import push_serverchan_report, push_serverchan_status

    if not analysis_text:
        push_serverchan_status('A股+商品情报', '失败', 'LLM分析未返回结果')
        return

    sc_ok = push_serverchan_report(f'【A股+商品情报】{date_str} 晨间简报', analysis_text)

    if sc_ok:
        push_serverchan_status('A股+商品情报', '成功', f'{date_str} 晨间简报已推送，{len(analysis_text)}字')
    else:
        push_serverchan_status('A股+商品情报', '失败', f'{date_str} Server酱推送失败')


def save_to_supabase(date_str, analysis_text, data_summary):
    """存档到Supabase — 复用daily_intelligence表"""
    try:
        row = {
            'date': date_str,
            'title': f'[A-Stock] {date_str} A股+大宗商品晨间简报',
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
    print(f'=== A股+大宗商品情报 v2.0 ===')
    print(f'日期: {TODAY_BJT}')
    print(f'时间: {datetime.now(BJT).strftime("%H:%M:%S")} BJT\n')

    # Step 1-6: A股核心数据
    indices = collect_market_indices()
    northbound = collect_northbound()
    margin = collect_margin_data()
    limits = collect_limit_stats()
    sectors = collect_sector_flow()
    news = collect_news()

    # Step 7-10: 大宗商品+宏观+全球
    futures = collect_domestic_futures()
    macro = collect_china_macro()
    global_mkt = collect_global_overnight()
    calendar = collect_economic_calendar()

    # 格式化数据
    print('\n格式化数据...')
    data_context = format_data_context(
        indices, northbound, margin, limits, sectors, news,
        futures, macro, global_mkt, calendar
    )

    print(f'  数据上下文: {len(data_context)} 字符')

    # LLM深度分析
    analysis = call_llm_analysis(data_context)

    if analysis:
        print(f'\n分析报告: {len(analysis)} 字符')

        # 推送
        split_and_push(analysis, TODAY_BJT)

        # Supabase存档
        data_summary = {
            'sh_index': indices.get('上证指数', {}).get('price'),
            'sh_change': indices.get('上证指数', {}).get('change_pct'),
            'sz_index': indices.get('深证成指', {}).get('price'),
            'cyb_index': indices.get('创业板指', {}).get('price'),
            'total_amount': indices.get('_total_amount'),
            'northbound_net': (northbound.get('summary') or {}).get('total_net'),
            'margin_rzye': (margin.get('latest') or {}).get('total_rzye') if margin else None,
            'zt_count': (limits.get('zt') or {}).get('count'),
            'dt_count': (limits.get('dt') or {}).get('count'),
            'fengban_rate': (limits.get('zt') or {}).get('fengban_rate'),
            'top_sector': sectors.get('industry', [{}])[0].get('name') if sectors.get('industry') else None,
            'news_count': len(news),
            'futures_count': len(futures.get('contracts', [])),
            'usdcny': (macro.get('usdcny') or {}).get('rate'),
            'pmi': (macro.get('indicators', {}).get('PMI') or {}).get('manufacturing'),
        }
        save_to_supabase(TODAY_BJT, analysis, data_summary)
    else:
        from notify import push_serverchan_status
        push_serverchan_status('A股+商品情报', '失败',
                               f'{TODAY_BJT} LLM分析未返回结果，请检查API Key')

    print('\n=== 完成 ===')


if __name__ == '__main__':
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    main()
