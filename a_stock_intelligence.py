#!/usr/bin/env python3
"""
A股交易情报 v1.0 — A-Share Trading Intelligence
情报体系 Line 3：专注A股市场深度投研分析

数据管线（6大数据源，全部东方财富免费API）：
  1. 大盘指数：上证/深证/创业板/科创50 实时行情
  2. 北向资金：沪股通/深股通 实时净流入
  3. 两融数据：融资融券余额变化
  4. 涨跌停统计：涨停/跌停家数、连板、封板率
  5. 板块资金流：行业板块资金净流入 Top 10
  6. A股新闻：财联社电报 + 东方财富要闻

分析：GLM-5 via OpenRouter（中国市场专长，核心矛盾+因果链+政策舆情+板块轮动），备选Qwen 3.5 Plus
推送：飞书卡片（主通道）+ Server酱状态通知（备用）
存档：Supabase daily_intelligence 表（title 前缀 [A-Stock]）

Schedule: Daily 16:00 BJT (after market close)
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

# Windows UTF-8 兼容
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# ============================================================
# 配置
# ============================================================
# LLM分析引擎：GLM-5 via OpenRouter（董事会2026-03-04选型决议，质量优先：中国市场专长）
# 备选：Qwen 3.5 Plus（自动fallback）
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


# ============================================================
# 数据采集函数
# ============================================================

def collect_market_indices():
    """Step 1: 大盘指数 — 上证/深证/创业板/科创50"""
    print('[1/6] 大盘指数...')
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

    # 需要的字段:
    # f43=最新价 f44=最高 f45=最低 f46=开盘
    # f47=成交量(手) f48=成交额 f170=涨跌幅 f171=涨跌额
    # f60=昨收 f116=总市值 f117=流通市值
    # 注意：东方财富API个股价格字段(f43/f44/f45/f46/f60)是整数编码（需要/100），
    # 但指数有时返回浮点真实值。用启发式检测：如果值>100000则认为是整数编码需要/100
    fields = 'f43,f44,f45,f46,f47,f48,f60,f116,f117,f170,f171'

    def _normalize_price(val, field_name='f43'):
        """启发式检测东方财富价格是否为整数编码（需要/100）。
        指数价格范围: 上证~3000-4000, 深证~9000-13000, 创业板~1800-2500
        如果原始值>100000，说明是整数编码（如3250.12返回为325012），需要/100"""
        v = safe_float(val)
        if v is not None and v > 100000:
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
                'volume': safe_int(d.get('f47')),         # 手
                'amount': safe_float(d.get('f48')),       # 元
                'change_pct': safe_float(d.get('f170')),  # 涨跌幅%
                'change_amt': safe_float(d.get('f171')),  # 涨跌额
                'total_mcap': safe_float(d.get('f116')),  # 总市值
                'float_mcap': safe_float(d.get('f117')),  # 流通市值
            }
            print(f'  {name}: {result[name]["price"]} ({fmt_pct(result[name]["change_pct"])})')
        else:
            print(f'  {name}: 获取失败')
        time.sleep(0.3)

    # 沪深两市全市场成交额（通过两市汇总）
    # 使用沪深市场概况API
    sh_url = 'https://push2.eastmoney.com/api/qt/ulist.np/get?fields=f1,f2,f3,f4,f6,f12,f13&secids=1.000001'
    sz_url = 'https://push2.eastmoney.com/api/qt/ulist.np/get?fields=f1,f2,f3,f4,f6,f12,f13&secids=0.399001'
    sh_data = safe_get(sh_url)
    sz_data = safe_get(sz_url)

    total_amount = 0
    if result.get('上证指数'):
        total_amount += result['上证指数'].get('amount', 0)
    if result.get('深证成指'):
        total_amount += result['深证成指'].get('amount', 0)
    result['_total_amount'] = total_amount

    return result


def collect_northbound():
    """Step 2: 北向资金 — 沪股通/深股通实时净流入"""
    print('[2/6] 北向资金...')
    result = {'summary': None, 'timeline': []}

    # 实时北向资金流向
    url = 'https://push2.eastmoney.com/api/qt/kamt.rtmin/get?fields1=f1,f2,f3,f4&fields2=f51,f52,f53,f54,f55,f56'
    data = safe_get(url)
    if data and data.get('data'):
        d = data['data']

        # f1=沪股通净流入 f2=深股通净流入 f3=北向合计净流入 f4=数据日期
        s1 = safe_float(d.get('s2n_hk2sh'))  # 沪股通净买入
        s2 = safe_float(d.get('s2n_hk2sz'))  # 深股通净买入

        result['summary'] = {
            'total_net': s1 + s2,
            'sh_net': s1,
            'sz_net': s2,
            'date': d.get('s2nDate', ''),
        }

        # 时间线数据（分钟级别）
        # f51=时间 f52=沪股通净流入 f53=深股通净流入 f54=北向合计 f55=沪股通累计 f56=深股通累计
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
    print('[3/6] 两融数据...')
    result = {'latest': None, 'history': []}

    # 沪市融资融券
    sh_url = ('https://datacenter-web.eastmoney.com/api/data/v1/get?'
              'reportName=RPT_MARGIN_SH&columns=ALL&pageSize=5'
              '&sortColumns=TRADE_DATE&sortTypes=-1')
    sh_data = safe_get(sh_url)

    # 深市融资融券
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
        # 取最新一天的数据合并
        sh_latest = sh_rows[0] if sh_rows else {}
        sz_latest = sz_rows[0] if sz_rows else {}

        # 沪市字段: RZYE(融资余额), RZMRE(融资买入额), RQYE(融券余额)
        sh_rzye = safe_float(sh_latest.get('RZYE', 0))
        sh_rzmre = safe_float(sh_latest.get('RZMRE', 0))
        sh_rqye = safe_float(sh_latest.get('RQYE', 0))
        # 深市字段: RZYE, RZMRE, RQYE
        sz_rzye = safe_float(sz_latest.get('RZYE', 0))
        sz_rzmre = safe_float(sz_latest.get('RZMRE', 0))
        sz_rqye = safe_float(sz_latest.get('RQYE', 0))

        total_rzye = sh_rzye + sz_rzye
        total_rzmre = sh_rzmre + sz_rzmre
        total_rqye = sh_rqye + sz_rqye

        result['latest'] = {
            'date': sh_latest.get('TRADE_DATE', sz_latest.get('TRADE_DATE', ''))[:10],
            'total_rzye': total_rzye,        # 两市融资余额
            'total_rzmre': total_rzmre,       # 两市融资买入额
            'total_rqye': total_rqye,         # 两市融券余额
            'sh_rzye': sh_rzye,
            'sz_rzye': sz_rzye,
            'total_margin': total_rzye + total_rqye,  # 两融余额合计
        }
        print(f'  融资余额: {fmt_num(total_rzye)}  融券余额: {fmt_num(total_rqye)}')

        # 历史趋势（近5日变化）
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
    """Step 4: 涨跌停统计 — 涨停/跌停家数、连板、封板率"""
    print('[4/6] 涨跌停统计...')
    result = {'zt': None, 'dt': None}

    # 涨停数据
    zt_url = f'https://push2ex.eastmoney.com/getYuBaoData?type=zt&date={TODAY_YYYYMMDD}'
    zt_data = safe_get(zt_url)
    if zt_data and zt_data.get('data'):
        d = zt_data['data']
        pool = d.get('pool', [])
        # 统计连板
        lianban_counts = {}
        first_zt_count = 0
        for stock in pool:
            lb = safe_int(stock.get('lbc', 1))  # 连板数
            lianban_counts[lb] = lianban_counts.get(lb, 0) + 1
            if lb == 1:
                first_zt_count += 1

        # 封板率 = 封住的涨停 / (封住+炸板)
        zbc = safe_int(d.get('zbc', 0))  # 炸板数（来自zbc字段）
        total_zt = len(pool)
        fengban_rate = total_zt / (total_zt + zbc) * 100 if (total_zt + zbc) > 0 else 0

        result['zt'] = {
            'count': total_zt,
            'zbc': zbc,                    # 炸板数
            'fengban_rate': fengban_rate,   # 封板率
            'first_zt': first_zt_count,    # 首板数
            'lianban': lianban_counts,     # 各级连板分布
            'max_lianban': max(lianban_counts.keys()) if lianban_counts else 0,
            'top_stocks': [],              # 高度板个股
        }

        # 提取连板最高的几只
        top_lb = sorted(pool, key=lambda x: safe_int(x.get('lbc', 1)), reverse=True)
        for s in top_lb[:8]:
            result['zt']['top_stocks'].append({
                'name': s.get('n', ''),
                'code': s.get('c', ''),
                'lbc': safe_int(s.get('lbc', 1)),
                'fund': safe_float(s.get('fund', 0)),   # 封单金额
                'amount': safe_float(s.get('amount', 0)),
                'ftime': s.get('ftime', ''),             # 首次封板时间
            })

        print(f'  涨停: {total_zt}家  炸板: {zbc}家  封板率: {fengban_rate:.0f}%')
    else:
        print(f'  涨停数据: 获取失败')

    # 跌停数据
    dt_url = f'https://push2ex.eastmoney.com/getYuBaoData?type=dt&date={TODAY_YYYYMMDD}'
    dt_data = safe_get(dt_url)
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
    print('[5/6] 板块资金流...')
    result = {'industry': [], 'concept': []}

    # 行业板块资金流向（按主力净流入排序）
    # f12=板块代码 f14=板块名称 f62=主力净流入 f184=主力净占比
    # f66=超大单净流入 f69=超大单净占比 f72=大单净流入 f75=大单净占比
    # f78=中单净流入 f81=中单净占比 f84=小单净流入 f87=小单净占比
    # f3=涨跌幅
    ind_url = ('https://push2.eastmoney.com/api/qt/clist/get?'
               'pn=1&pz=20&fid=f62&po=1&fs=m:90+t:2'
               '&fields=f3,f12,f14,f62,f184,f66,f69,f72,f75,f78,f81,f84,f87')
    ind_data = safe_get(ind_url)
    if ind_data and ind_data.get('data') and ind_data['data'].get('diff'):
        for item in ind_data['data']['diff']:
            result['industry'].append({
                'name': item.get('f14', ''),
                'code': item.get('f12', ''),
                'change_pct': safe_float(item.get('f3')),
                'main_net': safe_float(item.get('f62')),         # 主力净流入
                'main_pct': safe_float(item.get('f184')),        # 主力净占比
                'super_large_net': safe_float(item.get('f66')),  # 超大单
                'large_net': safe_float(item.get('f72')),        # 大单
                'medium_net': safe_float(item.get('f78')),       # 中单
                'small_net': safe_float(item.get('f84')),        # 小单
            })
        print(f'  行业板块: {len(result["industry"])}个')
        if result['industry']:
            top = result['industry'][0]
            print(f'  主力最多流入: {top["name"]} {fmt_num(top["main_net"])}')
    else:
        print(f'  行业板块: 获取失败')

    time.sleep(0.5)

    # 概念板块资金流向（按主力净流入排序）
    con_url = ('https://push2.eastmoney.com/api/qt/clist/get?'
               'pn=1&pz=20&fid=f62&po=1&fs=m:90+t:3'
               '&fields=f3,f12,f14,f62,f184,f66,f69,f72,f75')
    con_data = safe_get(con_url)
    if con_data and con_data.get('data') and con_data['data'].get('diff'):
        for item in con_data['data']['diff']:
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

    # 也获取资金流出最多的行业板块（倒序）
    out_url = ('https://push2.eastmoney.com/api/qt/clist/get?'
               'pn=1&pz=10&fid=f62&po=0&fs=m:90+t:2'
               '&fields=f3,f12,f14,f62,f184')
    out_data = safe_get(out_url)
    if out_data and out_data.get('data') and out_data['data'].get('diff'):
        result['industry_outflow'] = []
        for item in out_data['data']['diff']:
            result['industry_outflow'].append({
                'name': item.get('f14', ''),
                'change_pct': safe_float(item.get('f3')),
                'main_net': safe_float(item.get('f62')),
            })

    return result


def collect_news():
    """Step 6: A股新闻 — 财联社电报 + 东方财富要闻"""
    print('[6/6] A股新闻...')
    news = []

    # 财联社电报（cls.cn telegraph API）
    try:
        cls_url = ('https://www.cls.cn/nodeapi/updateTelegraph?'
                   'app=CailianpressWeb&os=web&sv=8.4.6&rn=20')
        cls_data = safe_get(cls_url, timeout=15)
        if cls_data and cls_data.get('data') and cls_data['data'].get('roll_data'):
            for item in cls_data['data']['roll_data'][:15]:
                title = item.get('title', '') or item.get('brief', '') or ''
                content = item.get('content', '') or ''
                # 去除HTML标签
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

    # 东方财富要闻（7x24快讯）
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
# 数据格式化
# ============================================================

def format_data_context(indices, northbound, margin, limits, sectors, news):
    """将所有数据格式化为LLM的输入上下文"""
    sections = []

    # 时间基准
    now_bjt = datetime.now(BJT)
    s = '## 时间基准\n'
    s += f'当前北京时间: {now_bjt.strftime("%Y-%m-%d %H:%M")} (BJT/UTC+8)\n'
    s += f'以下数据为A股{now_bjt.strftime("%Y-%m-%d")}收盘后采集。\n'
    s += f'"今日"指北京时间{now_bjt.strftime("%Y-%m-%d")}，'
    s += f'"昨日"指{(now_bjt - timedelta(days=1)).strftime("%Y-%m-%d")}。\n'
    sections.append(s)

    # 大盘指数
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

    # 北向资金
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
            # 尾盘加速分析（最后30分钟 vs 全天）
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

    # 两融数据
    s = '## 两融数据（杠杆资金）\n'
    if margin.get('latest'):
        m = margin['latest']
        s += f'日期: {m["date"]}\n'
        s += f'融资余额: {fmt_num(m["total_rzye"])} (沪{fmt_num(m["sh_rzye"])} + 深{fmt_num(m["sz_rzye"])})\n'
        s += f'融资买入额: {fmt_num(m["total_rzmre"])}\n'
        s += f'融券余额: {fmt_num(m["total_rqye"])}\n'
        s += f'两融余额合计: {fmt_num(m["total_margin"])}\n'

        # 趋势分析
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

    # 涨跌停
    s = '## 涨跌停统计（市场情绪温度计）\n'
    if limits.get('zt'):
        zt = limits['zt']
        s += f'涨停: **{zt["count"]}家**  炸板: {zt["zbc"]}家  封板率: **{zt["fengban_rate"]:.0f}%**\n'
        s += f'首板: {zt["first_zt"]}家  最高连板: {zt["max_lianban"]}板\n'

        # 连板梯队
        if zt['lianban']:
            s += '连板分布: '
            for lb in sorted(zt['lianban'].keys(), reverse=True):
                if lb >= 2:
                    s += f'{lb}板{zt["lianban"][lb]}家 '
            s += '\n'

        # 情绪判断
        if zt['fengban_rate'] >= 75 and zt['count'] >= 50:
            s += '🔥 高温市场：涨停多+封板率高，赚钱效应强\n'
        elif zt['fengban_rate'] <= 40 or zt['count'] <= 20:
            s += '🥶 冰点市场：涨停少或封板率低，亏钱效应重\n'
        elif zt['fengban_rate'] >= 60:
            s += '🟡 温和偏暖：封板率及格，短线可操作\n'

        # 高度板个股
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

    # 涨跌停比（zt/dt可能为None，需要额外guard）
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

    # 板块资金流
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

    # 新闻
    s = '## 最近24h重要新闻\n'
    if news:
        # 按重要性排序（importance高的优先），同级按时间倒序
        sorted_news = sorted(news, key=lambda x: (-x.get('importance', 0), x.get('time', '')), reverse=False)
        # 去重标题
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

ASTOCK_ANALYST_SYSTEM = """你是国兴超链集团的A股首席分析师（CIO级别），拥有20年A股投研经验。
你同时具备顶级卖方研究和买方投资的双重视角。

你的分析风格：
- 结论先行，先给判断再给逻辑
- 数据驱动，每个观点必须有数据支撑
- 因果链清晰，不做无逻辑的联想
- 直白敢判断，不做骑墙分析
- 政策敏感度高，懂中国市场的"中国特色"

## 分析方法论

### 核心矛盾法
每天A股只有1-2个核心矛盾，找到它们，围绕它们展开所有分析。
例如："北向资金连续5日大幅流出，但两融余额不降反升——核心矛盾是外资撤退但内资杠杆加码，谁对了？"

### 因果链推演（必须做）
事件 → 传导机制 → 一阶效应 → 二阶效应 → 对仓位的影响
不要只说"X发生了"，要推演"X发生了 → 因为Y机制 → 导致Z → 这意味着..."

### 政策舆情因子（A股特色，必须分析）
- 证监会/国务院近期表态（稳定市场还是改革加压）
- 官媒（新华社/人民日报/经济日报）论调（暖风还是风险提示）
- 近期政策方向（宽松/收紧/结构性，对哪些板块利好/利空）
- IPO/再融资节奏变化
- 重要时间窗口（两会/经济工作会议/MLF/LPR等）

### 板块轮动分析（核心竞争力）
- 主力资金流向揭示的板块轮动方向
- 涨停板题材归类（哪些题材在发酵/退潮）
- 行业板块vs概念板块的资金分歧
- 大盘股(沪深300)vs小盘股(中证1000)的风格切换
- 连板股的身位分布（高度板断裂=情绪退潮，新龙头出现=新周期启动）

### 北向资金解读（Smart Money）
- 北向资金的方向通常领先1-3天
- 尾盘加速流入/流出是最强信号
- 沪股通vs深股通分歧暗示蓝筹vs成长偏好
- 连续5日同方向流动是趋势确认
- 但要注意：北向资金有时是被动调仓（指数权重调整），不一定代表主动观点

### 两融数据解读
- 融资余额增加 = 杠杆资金看多，减少 = 去杠杆
- 融资买入额放大 = 加仓意愿强
- 融券余额增加 = 做空力量加码
- 两融余额在1.5万亿以下偏冷，1.8万亿以上偏热
- 融资余额变化方向通常与指数同向，背离时要警惕

## 铁律
1. 不说"建议关注"、"值得关注" — 要说"应该做什么"
2. 不说"可能涨也可能跌" — 要给方向判断和概率
3. 不说"谨慎观望" — 要说在什么条件下做什么
4. 每个判断附带置信度（高/中/低）和逻辑链
5. 信号冲突时用⚡显式标注，分析哪个信号更可靠
6. 风险提示必须具体：不是"注意风险"，而是"如果X跌破Y，止损Z"
7. 数据必须量化到具体数字，不用"大幅"、"显著"等模糊词
8. 所有时间都用北京时间（BJT）

## 输出格式要求（手机+电脑阅读）
- 用 ## 大标题（不要用###）
- 关键数字全部**加粗**
- 每段不超过4行
- 段落间用空行分隔
- 正负面emoji：🔴负面 🟡中性 🟢正面 ⚡冲突
- 不用表格（手机显示会乱）
- 分隔线 --- 分开大板块"""

ASTOCK_ANALYST_USER = """请基于以下A股收盘数据，撰写今日A股交易情报。

要求：
1. 先找到今日1-2个核心矛盾，作为整篇报告的主线
2. 深度分析，不是数据罗列——每个数据点都要解读"这意味着什么"
3. 所有判断给出因果链
4. 最后给出明确的交易建议（不是"建议关注"）

## 报告结构

**第一部分：核心矛盾与结论**（最重要，放最前面）
- 今日核心矛盾是什么？
- 你的判断是什么？（方向+置信度+逻辑）
- 明日操作建议（仓位/板块/条件）

**第二部分：大盘全景**
- 三大指数涨跌分析（谁强谁弱、为什么）
- 成交额变化含义（放量/缩量说明什么）
- 大盘股vs小盘股风格判断（沪深300 vs 中证1000）
- 今日最关键的技术位（支撑/阻力）

**第三部分：北向资金解读**
- 今日北向净流入/出分析
- 沪股通vs深股通的分歧含义
- 结合近期趋势判断外资态度
- 尾盘加速是否有重要信号

**第四部分：情绪面（涨跌停分析）**
- 涨停家数+封板率代表什么情绪
- 连板梯队分析（高度板是否健康、有无断层）
- 核心题材归类（哪些题材在涨停，说明资金在炒什么）
- 跌停数量的警示意义

**第五部分：板块轮动**
- 资金净流入最多的行业 = 主线在哪里
- 资金净流出最多的行业 = 什么在退潮
- 概念板块热点 = 短线题材机会
- 行业板块 vs 概念板块资金分歧分析

**第六部分：杠杆资金（两融）**
- 融资余额变化代表的市场杠杆水平
- 融资买入额代表的加仓意愿
- 两融趋势对后市的影响

**第七部分：重要新闻与政策**
- 筛选真正影响市场的新闻（不超过5条）
- 每条给出影响判断（利好/利空/中性 + 影响量级 + 影响板块）
- 近期政策方向判断

**第八部分：风险矩阵与机会**
- Top 3风险事件 + 触发条件 + 防御策略
- Top 3机会 + 入场条件 + 目标板块/个股方向
- 明日重点关注事件（经济数据发布、IPO、到期等）

--- 以下是今日A股收盘数据 ---

{data_context}"""


def call_llm_analysis(data_context):
    """调用LLM深度分析（GLM-5 via OpenRouter，备选Qwen 3.5 Plus）"""
    from llm_engine import call_llm
    print('\n调用LLM深度分析（GLM-5 → Qwen fallback）...')
    user_msg = ASTOCK_ANALYST_USER.replace('{data_context}', data_context)
    return call_llm(
        system_prompt=ASTOCK_ANALYST_SYSTEM,
        user_prompt=user_msg,
        model='glm5',
        fallback='qwen',
        max_tokens=8000,
        timeout=180,
    )


# ============================================================
# 推送
# ============================================================

def split_and_push(analysis_text, date_str):
    """将分析报告推送（通过统一推送层）"""
    from notify import push_feishu_report, push_serverchan_report, push_serverchan_status

    if not analysis_text:
        push_serverchan_status('A股交易情报', '失败', 'LLM分析未返回结果')
        return

    # 优先飞书推送完整报告
    feishu_ok = push_feishu_report(f'【A股情报】{date_str} 交易情报', analysis_text)

    sc_ok = False
    if not feishu_ok:
        # 飞书不可用时 fallback 到 Server酱长报告
        sc_ok = push_serverchan_report(f'【A股情报】{date_str}', analysis_text)

    # 根据实际推送结果判断状态
    if feishu_ok:
        push_serverchan_status('A股交易情报', '成功', f'{date_str} 报告已推送(飞书)，{len(analysis_text)}字')
    elif sc_ok:
        push_serverchan_status('A股交易情报', '部分成功', f'{date_str} 飞书失败，Server酱推送，{len(analysis_text)}字')
    else:
        push_serverchan_status('A股交易情报', '失败', f'{date_str} 飞书和Server酱均推送失败')


def save_to_supabase(date_str, analysis_text, data_summary):
    """存档到Supabase — 复用daily_intelligence表，title字段标记为A-Stock类型"""
    try:
        row = {
            'date': date_str,
            'title': f'[A-Stock] {date_str} A股交易情报',
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
    print(f'=== A股交易情报 v1.0 ===')
    print(f'日期: {TODAY_BJT}')
    print(f'时间: {datetime.now(BJT).strftime("%H:%M:%S")} BJT\n')

    # Step 1-6: 数据采集
    indices = collect_market_indices()
    northbound = collect_northbound()
    margin = collect_margin_data()
    limits = collect_limit_stats()
    sectors = collect_sector_flow()
    news = collect_news()

    # 格式化数据
    print('\n格式化数据...')
    data_context = format_data_context(
        indices, northbound, margin, limits, sectors, news
    )

    # 打印数据长度
    print(f'  数据上下文: {len(data_context)} 字符')

    # LLM深度分析（Qwen via OpenRouter）
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
            'northbound_net': northbound.get('summary', {}).get('total_net'),
            'margin_rzye': margin.get('latest', {}).get('total_rzye'),
            'zt_count': limits.get('zt', {}).get('count'),
            'dt_count': limits.get('dt', {}).get('count'),
            'fengban_rate': limits.get('zt', {}).get('fengban_rate'),
            'top_sector': sectors.get('industry', [{}])[0].get('name') if sectors.get('industry') else None,
            'news_count': len(news),
        }
        save_to_supabase(TODAY_BJT, analysis, data_summary)
    else:
        from notify import push_serverchan_status
        push_serverchan_status('A股交易情报', '失败',
                               f'{TODAY_BJT} LLM分析未返回结果，请检查OpenRouter API Key')

    print('\n=== 完成 ===')


if __name__ == '__main__':
    main()
