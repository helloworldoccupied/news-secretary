#!/usr/bin/env python3
"""
生成三条情报线的预览HTML，不推送任何渠道。
每条线在独立子进程中运行，避免sys.stdout wrapper冲突。
包含ECharts交互式图表（价格走势、恐贪指数、板块热力图等）。

2026-03-04 更新：
  - 三线全部使用Claude Sonnet（直连Anthropic API）作为主力分析师
  - 中国LLM（DeepSeek/GLM-5/Qwen）仅作为fallback
  - 飞书已完全废弃，推送统一Server酱
  - 新增ECharts交互式图表
"""
import sys, os, io, json, time, subprocess, re, tempfile
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

# Windows GBK编码无法打印emoji，强制UTF-8
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ===== 每条线的独立运行脚本模板 =====
RUNNER_TEMPLATE = r'''#!/usr/bin/env python3
import sys, os, io, json
os.environ['SERVERCHAN_KEY'] = ''
os.environ['SUPABASE_URL'] = ''
os.environ['SUPABASE_KEY'] = ''
# 不在这里包装stdout/stderr，让被导入的模块自己处理（避免重复包装导致I/O closed错误）
sys.path.insert(0, {base_dir!r})
from llm_engine import call_llm
output_file = sys.argv[1]
chart_file = sys.argv[2] if len(sys.argv) > 2 else ''
try:
{body}
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(report)
    # 保存图表数据（如果有）
    if chart_file and chart_data:
        with open(chart_file, 'w', encoding='utf-8') as f:
            json.dump(chart_data, f, ensure_ascii=False)
    print('OK', flush=True)
except Exception as e:
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write('## 生成失败\n\n' + str(e))
    print(f'FAILED: {{e}}', flush=True)
    sys.exit(1)
'''

LINE2_BODY = '''
    import crypto_daily_intelligence as c
    m = c.collect_market_overview()
    oc = c.collect_onchain_fundamentals()
    mi = c.collect_mining_difficulty()
    fu = c.collect_derivatives_funding()
    oi_ls = c.collect_derivatives_oi_ls()
    op = c.collect_options_market()
    df = c.collect_defi()
    ma = c.collect_macro()
    se = c.collect_sentiment()
    ne = c.collect_news()
    ctx = c.format_data_context(m, oc, mi, fu, oi_ls, op, df, ma, se, ne)
    print(f'  数据上下文: {len(ctx)} 字符', flush=True)
    report = call_llm(c.CRYPTO_ANALYST_SYSTEM, c.CRYPTO_ANALYST_USER + '\\n\\n' + ctx,
                      model='sonnet', fallback='deepseek', max_tokens=8000) or '(LLM未返回结果)'
    print(f'  报告: {len(report)} 字符', flush=True)
    # 图表数据
    chart_data = {}
    # BTC价格
    btc = m.get('prices', {}).get('bitcoin', {})
    if btc:
        chart_data['btc_price'] = btc.get('usd', 0)
        chart_data['btc_change_24h'] = btc.get('usd_24h_change', 0)
    # ETH价格
    eth = m.get('prices', {}).get('ethereum', {})
    if eth:
        chart_data['eth_price'] = eth.get('usd', 0)
        chart_data['eth_change_24h'] = eth.get('usd_24h_change', 0)
    # 恐贪指数
    fg = se.get('fear_greed', {})
    if fg:
        chart_data['fear_greed_value'] = int(fg.get('value', 50))
        chart_data['fear_greed_label'] = fg.get('classification', 'Neutral')
    # 费率
    chart_data['funding_rates'] = {}
    for exch in ['binance', 'okx', 'bybit']:
        rates = fu.get(exch, {})
        if rates and isinstance(rates, dict):
            cleaned = {}
            for k, v in list(rates.items())[:8]:
                try:
                    if isinstance(v, (int, float)):
                        cleaned[k] = float(v)
                    elif isinstance(v, str):
                        cleaned[k] = float(v)
                    else:
                        cleaned[k] = 0
                except:
                    cleaned[k] = 0
            chart_data['funding_rates'][exch] = cleaned
    # DeFi TVL
    chart_data['defi_tvl'] = df.get('tvl_current', 0)
    chart_data['defi_tvl_change'] = df.get('tvl_change_24h', 0)
    # 宏观
    for k in ['DXY', 'Gold', 'US10Y', 'SPX']:
        macro_item = ma.get(k, {})
        if macro_item:
            chart_data[f'macro_{k.lower()}'] = macro_item.get('price', 0)
            chart_data[f'macro_{k.lower()}_change'] = macro_item.get('change_pct', 0)
    # 期权
    if op.get('btc_options'):
        chart_data['put_call_ratio'] = op['btc_options'].get('put_call_ratio', 0)
    if op.get('dvol'):
        chart_data['dvol'] = op['dvol'].get('current', 0)
    # 链上
    chart_data['puell_multiple'] = oc.get('puell_multiple', 0)
    chart_data['nvt_ratio'] = oc.get('nvt_ratio', 0)
'''

LINE3_BODY = '''
    import a_stock_intelligence as a
    idx = a.collect_market_indices()
    nb = a.collect_northbound()
    mg = a.collect_margin_data()
    lt = a.collect_limit_stats()
    sc = a.collect_sector_flow()
    ns = a.collect_news()
    ctx = a.format_data_context(idx, nb, mg, lt, sc, ns)
    print(f'  数据上下文: {len(ctx)} 字符', flush=True)
    report = call_llm(a.ASTOCK_ANALYST_SYSTEM, a.ASTOCK_ANALYST_USER + '\\n\\n' + ctx,
                      model='sonnet', fallback='glm5', max_tokens=8000) or '(LLM未返回结果)'
    print(f'  报告: {len(report)} 字符', flush=True)
    # 图表数据
    chart_data = {}
    # 指数
    if idx:
        chart_data['indices'] = {}
        for name, info in idx.items():
            if isinstance(info, dict):
                chart_data['indices'][name] = {
                    'price': info.get('price', info.get('close', 0)),
                    'change': info.get('change_pct', info.get('pct_change', 0)),
                }
    # 北向资金
    if nb:
        chart_data['northbound'] = {
            'net_buy': nb.get('net_buy', nb.get('total', 0)),
        }
    # 两融
    if mg:
        chart_data['margin'] = {
            'balance': mg.get('balance', 0),
            'change': mg.get('change', 0),
        }
    # 涨跌停
    if lt:
        chart_data['limits'] = {
            'up_count': lt.get('up_count', lt.get('涨停', 0)),
            'down_count': lt.get('down_count', lt.get('跌停', 0)),
        }
    # 板块资金流
    if sc and isinstance(sc, list):
        chart_data['sector_flow'] = sc[:10]
'''

LINE4_BODY = '''
    import ai_industry_intelligence as ai
    st = ai.collect_ai_stocks()
    ar = ai.collect_arxiv_papers()
    gh = ai.collect_github_trending()
    nw = ai.collect_ai_news()
    cm = ai.collect_compute_market()
    ctx = ai.format_data_context(st, ar, gh, nw, cm)
    print(f'  数据上下文: {len(ctx)} 字符', flush=True)
    report = call_llm(ai.AI_ANALYST_SYSTEM, ai.AI_ANALYST_USER + '\\n\\n' + ctx,
                      model='sonnet', fallback='qwen', max_tokens=8000) or '(LLM未返回结果)'
    print(f'  报告: {len(report)} 字符', flush=True)
    # 图表数据
    chart_data = {}
    # AI股票
    if st and isinstance(st, list):
        chart_data['ai_stocks'] = st[:10]
    elif st and isinstance(st, dict):
        chart_data['ai_stocks'] = list(st.values())[:10] if st.values() else []
    # GitHub trending
    if gh and isinstance(gh, list):
        chart_data['github_trending'] = gh[:8]
    # 算力市场
    if cm and isinstance(cm, dict):
        chart_data['compute_market'] = cm
'''

LINES = [
    ('crypto', '🪙 加密投研日报', 'Claude Sonnet', LINE2_BODY),
    ('astock', '📈 A股交易情报', 'Claude Sonnet', LINE3_BODY),
    ('ai',     '🤖 AI产业周报',  'Claude Sonnet', LINE4_BODY),
]


def run_line(line_id, line_name, body):
    """在独立子进程中运行一条情报线，返回(报告文本, 图表数据)"""
    # 创建临时runner脚本
    runner_code = RUNNER_TEMPLATE.format(base_dir=BASE_DIR, body=body)
    runner_path = os.path.join(tempfile.gettempdir(), f'run_{line_id}.py')
    output_path = os.path.join(tempfile.gettempdir(), f'report_{line_id}.txt')
    chart_path = os.path.join(tempfile.gettempdir(), f'chart_{line_id}.json')

    with open(runner_path, 'w', encoding='utf-8') as f:
        f.write(runner_code)

    print(f'\n=== {line_name} 开始生成 ===', flush=True)
    t0 = time.time()

    env = os.environ.copy()
    env['PYTHONIOENCODING'] = 'utf-8'

    try:
        proc = subprocess.run(
            [sys.executable, runner_path, output_path, chart_path],
            capture_output=True, text=True, timeout=300,
            cwd=BASE_DIR, env=env,
            encoding='utf-8', errors='replace'
        )
        elapsed = time.time() - t0

        # 打印子进程输出
        if proc.stdout:
            for line in proc.stdout.strip().split('\n'):
                print(f'  [{line_id}] {line}', flush=True)
        if proc.stderr:
            for line in proc.stderr.strip().split('\n')[:5]:
                print(f'  [{line_id} ERR] {line}', flush=True)

        # 读取报告
        report = ''
        if os.path.exists(output_path):
            with open(output_path, 'r', encoding='utf-8') as f:
                report = f.read()
            print(f'=== {line_name} 完成 ({elapsed:.1f}s, {len(report)}字符) ===', flush=True)
        else:
            msg = f'生成失败: 未产生输出文件 (exit code {proc.returncode})'
            print(f'=== {line_name} 失败 ({elapsed:.1f}s): {msg} ===', flush=True)
            report = f'## 生成失败\n\n{msg}'

        # 读取图表数据
        chart_data = {}
        if os.path.exists(chart_path):
            try:
                with open(chart_path, 'r', encoding='utf-8') as f:
                    chart_data = json.load(f)
            except:
                pass

        return report, chart_data

    except subprocess.TimeoutExpired:
        print(f'=== {line_name} 超时 (300s) ===', flush=True)
        return '## 生成失败\n\n子进程超时(300秒)', {}
    except Exception as e:
        print(f'=== {line_name} 异常: {e} ===', flush=True)
        return f'## 生成失败\n\n{e}', {}
    finally:
        # 清理临时文件
        for p in [runner_path, output_path, chart_path]:
            try:
                os.remove(p)
            except:
                pass


def md_to_html(text):
    """简易markdown→HTML转换"""
    text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    # 标题
    text = re.sub(r'^## (.+)$', r'<h2>\1</h2>', text, flags=re.MULTILINE)
    text = re.sub(r'^### (.+)$', r'<h3>\1</h3>', text, flags=re.MULTILINE)
    text = re.sub(r'^#### (.+)$', r'<h4>\1</h4>', text, flags=re.MULTILINE)
    # 加粗
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    # 列表项（- 开头）
    text = re.sub(r'^- (.+)$', r'<li>\1</li>', text, flags=re.MULTILINE)
    # 分隔线
    text = re.sub(r'^---+$', '<hr>', text, flags=re.MULTILINE)
    # 换行→段落
    paragraphs = text.split('\n\n')
    html_parts = []
    for p in paragraphs:
        p = p.strip()
        if not p:
            continue
        if p.startswith('<h') or p.startswith('<hr'):
            html_parts.append(p)
        elif '<li>' in p:
            html_parts.append(f'<ul>{p}</ul>')
        else:
            html_parts.append(f'<p>{p.replace(chr(10), "<br>")}</p>')
    return '\n'.join(html_parts)


def build_crypto_charts_js(data):
    """生成加密投研的ECharts图表JavaScript"""
    if not data:
        return ''

    js_parts = []

    # 1. 恐贪指数仪表盘
    fg_val = data.get('fear_greed_value', 50)
    fg_label = data.get('fear_greed_label', 'Neutral')
    js_parts.append(f'''
    // 恐贪指数
    var fgChart = echarts.init(document.getElementById('chart-fear-greed'));
    fgChart.setOption({{
      series: [{{
        type: 'gauge',
        startAngle: 180, endAngle: 0,
        min: 0, max: 100,
        splitNumber: 4,
        pointer: {{ show: true, length: '60%', width: 6 }},
        axisLine: {{
          lineStyle: {{
            width: 20,
            color: [[0.25, '#c62828'], [0.45, '#ef6c00'], [0.55, '#fdd835'], [0.75, '#66bb6a'], [1, '#2e7d32']]
          }}
        }},
        axisTick: {{ show: false }},
        splitLine: {{ show: false }},
        axisLabel: {{ show: false }},
        detail: {{
          fontSize: 28, fontWeight: 'bold', offsetCenter: [0, '30%'],
          formatter: function(v) {{ return v + '\\n{fg_label}'; }}
        }},
        data: [{{ value: {fg_val} }}]
      }}]
    }});
    ''')

    # 2. 主要资产价格对比柱状图
    assets = []
    changes = []
    colors = []
    for key, label in [('btc', 'BTC'), ('eth', 'ETH')]:
        chg = data.get(f'{key}_change_24h', 0)
        if chg:
            assets.append(label)
            changes.append(round(float(chg), 2))
            colors.append('#2e7d32' if chg >= 0 else '#c62828')
    for key, label in [('dxy', 'DXY'), ('gold', 'Gold'), ('spx', 'S&P500')]:
        chg = data.get(f'macro_{key}_change', 0)
        if chg:
            assets.append(label)
            changes.append(round(float(chg), 2))
            colors.append('#2e7d32' if chg >= 0 else '#c62828')

    if assets:
        js_parts.append(f'''
    // 资产24h涨跌幅
    var assetChart = echarts.init(document.getElementById('chart-assets'));
    assetChart.setOption({{
      tooltip: {{ trigger: 'axis', formatter: '{{b}}: {{c}}%' }},
      xAxis: {{ type: 'category', data: {json.dumps(assets)}, axisLabel: {{ fontSize: 13, fontWeight: 'bold' }} }},
      yAxis: {{ type: 'value', axisLabel: {{ formatter: '{{value}}%' }} }},
      series: [{{
        type: 'bar', data: {json.dumps(changes)},
        itemStyle: {{
          color: function(p) {{ return {json.dumps(colors)}[p.dataIndex]; }}
        }},
        label: {{ show: true, position: 'top', formatter: '{{c}}%', fontSize: 12 }}
      }}],
      grid: {{ left: 50, right: 20, top: 20, bottom: 40 }}
    }});
    ''')

    # 3. 资金费率热力图
    rates = data.get('funding_rates', {})
    if rates:
        exchanges = list(rates.keys())
        all_coins = set()
        for exch_rates in rates.values():
            all_coins.update(exch_rates.keys())
        coins = sorted(list(all_coins))[:8]
        heatmap_data = []
        for ei, exch in enumerate(exchanges):
            for ci, coin in enumerate(coins):
                val = rates.get(exch, {}).get(coin, 0)
                heatmap_data.append([ci, ei, round(float(val) * 100, 4)])

        js_parts.append(f'''
    // 资金费率热力图
    var rateChart = echarts.init(document.getElementById('chart-funding-rates'));
    rateChart.setOption({{
      tooltip: {{ formatter: function(p) {{ return p.data[2] ? p.data[2].toFixed(4) + '%' : 'N/A'; }} }},
      xAxis: {{ type: 'category', data: {json.dumps(coins)}, axisLabel: {{ fontSize: 11 }} }},
      yAxis: {{ type: 'category', data: {json.dumps(exchanges)}, axisLabel: {{ fontSize: 12 }} }},
      visualMap: {{
        min: -0.05, max: 0.1, calculable: true, orient: 'horizontal',
        left: 'center', bottom: 0,
        inRange: {{ color: ['#c62828', '#ffeb3b', '#2e7d32'] }},
        textStyle: {{ fontSize: 11 }}
      }},
      series: [{{
        type: 'heatmap', data: {json.dumps(heatmap_data)},
        label: {{ show: true, fontSize: 10, formatter: function(p) {{ return p.data[2] ? p.data[2].toFixed(3) : ''; }} }}
      }}],
      grid: {{ left: 70, right: 20, top: 10, bottom: 60 }}
    }});
    ''')

    # 4. 链上指标仪表盘（Puell + NVT）
    puell = data.get('puell_multiple', 0)
    nvt = data.get('nvt_ratio', 0)
    if puell or nvt:
        js_parts.append(f'''
    // 链上指标
    var onchainChart = echarts.init(document.getElementById('chart-onchain'));
    onchainChart.setOption({{
      tooltip: {{}},
      series: [
        {{
          type: 'gauge', center: ['30%', '55%'], radius: '80%',
          startAngle: 200, endAngle: -20,
          min: 0, max: 4, splitNumber: 4,
          pointer: {{ length: '55%', width: 5 }},
          axisLine: {{ lineStyle: {{ width: 15, color: [[0.3, '#2e7d32'], [0.7, '#fdd835'], [1, '#c62828']] }} }},
          axisTick: {{ show: false }}, splitLine: {{ show: false }}, axisLabel: {{ show: false }},
          title: {{ text: 'Puell\\nMultiple', offsetCenter: [0, '75%'], fontSize: 12 }},
          detail: {{ fontSize: 20, offsetCenter: [0, '45%'], formatter: '{{value}}' }},
          data: [{{ value: {round(float(puell), 2) if puell else 0} }}]
        }},
        {{
          type: 'gauge', center: ['70%', '55%'], radius: '80%',
          startAngle: 200, endAngle: -20,
          min: 0, max: 200, splitNumber: 4,
          pointer: {{ length: '55%', width: 5 }},
          axisLine: {{ lineStyle: {{ width: 15, color: [[0.3, '#c62828'], [0.5, '#fdd835'], [1, '#2e7d32']] }} }},
          axisTick: {{ show: false }}, splitLine: {{ show: false }}, axisLabel: {{ show: false }},
          title: {{ text: 'NVT\\nRatio', offsetCenter: [0, '75%'], fontSize: 12 }},
          detail: {{ fontSize: 20, offsetCenter: [0, '45%'], formatter: '{{value}}' }},
          data: [{{ value: {round(float(nvt), 1) if nvt else 0} }}]
        }}
      ]
    }});
    ''')

    return '\n'.join(js_parts)


def build_astock_charts_js(data):
    """生成A股情报的ECharts图表JavaScript"""
    if not data:
        return ''

    js_parts = []

    # 1. 指数涨跌幅柱状图
    indices = data.get('indices', {})
    if indices:
        names = []
        values = []
        colors = []
        for name, info in indices.items():
            if isinstance(info, dict):
                chg = info.get('change', 0)
                names.append(name)
                values.append(round(float(chg), 2) if chg else 0)
                colors.append('#c62828' if (chg or 0) >= 0 else '#2e7d32')
        if names:
            js_parts.append(f'''
    var idxChart = echarts.init(document.getElementById('chart-astock-indices'));
    idxChart.setOption({{
      tooltip: {{ trigger: 'axis', formatter: '{{b}}: {{c}}%' }},
      xAxis: {{ type: 'category', data: {json.dumps(names, ensure_ascii=False)},
                axisLabel: {{ fontSize: 11, rotate: 30 }} }},
      yAxis: {{ type: 'value', axisLabel: {{ formatter: '{{value}}%' }} }},
      series: [{{
        type: 'bar', data: {json.dumps(values)},
        itemStyle: {{ color: function(p) {{ return {json.dumps(colors)}[p.dataIndex]; }} }},
        label: {{ show: true, position: 'top', formatter: '{{c}}%', fontSize: 11 }}
      }}],
      grid: {{ left: 50, right: 20, top: 20, bottom: 60 }}
    }});
    ''')

    # 2. 涨跌停对比
    limits = data.get('limits', {})
    if limits:
        up = limits.get('up_count', 0)
        down = limits.get('down_count', 0)
        js_parts.append(f'''
    var limitChart = echarts.init(document.getElementById('chart-astock-limits'));
    limitChart.setOption({{
      tooltip: {{}},
      series: [{{
        type: 'pie', radius: ['40%', '70%'], center: ['50%', '55%'],
        data: [
          {{ value: {up}, name: '涨停 {up}', itemStyle: {{ color: '#c62828' }} }},
          {{ value: {down}, name: '跌停 {down}', itemStyle: {{ color: '#2e7d32' }} }}
        ],
        label: {{ fontSize: 14, fontWeight: 'bold' }}
      }}]
    }});
    ''')

    # 3. 板块资金流
    sectors = data.get('sector_flow', [])
    if sectors:
        sector_names = []
        sector_values = []
        for s in sectors[:8]:
            if isinstance(s, dict):
                sector_names.append(s.get('name', s.get('sector', '?')))
                val = s.get('net_flow', s.get('amount', s.get('value', 0)))
                sector_values.append(round(float(val) / 1e8, 2) if val else 0)
        if sector_names:
            js_parts.append(f'''
    var sectorChart = echarts.init(document.getElementById('chart-astock-sectors'));
    sectorChart.setOption({{
      tooltip: {{ formatter: '{{b}}: {{c}}亿' }},
      xAxis: {{ type: 'value', axisLabel: {{ formatter: '{{value}}亿' }} }},
      yAxis: {{ type: 'category', data: {json.dumps(sector_names[::-1], ensure_ascii=False)},
                axisLabel: {{ fontSize: 12 }} }},
      series: [{{
        type: 'bar', data: {json.dumps(sector_values[::-1])},
        itemStyle: {{ color: function(p) {{ return p.data >= 0 ? '#c62828' : '#2e7d32'; }} }},
        label: {{ show: true, position: 'right', formatter: '{{c}}亿', fontSize: 11 }}
      }}],
      grid: {{ left: 100, right: 60, top: 10, bottom: 30 }}
    }});
    ''')

    return '\n'.join(js_parts)


def build_ai_charts_js(data):
    """生成AI产业周报的ECharts图表JavaScript"""
    if not data:
        return ''

    js_parts = []

    # AI股票涨跌幅
    stocks = data.get('ai_stocks', [])
    if stocks:
        names = []
        values = []
        for s in stocks[:10]:
            if isinstance(s, dict):
                n = s.get('name', s.get('symbol', '?'))
                c = s.get('change_pct', s.get('change', s.get('pct_change', 0)))
                names.append(str(n)[:8])
                values.append(round(float(c), 2) if c else 0)
        if names:
            js_parts.append(f'''
    var aiStockChart = echarts.init(document.getElementById('chart-ai-stocks'));
    aiStockChart.setOption({{
      tooltip: {{ formatter: '{{b}}: {{c}}%' }},
      xAxis: {{ type: 'category', data: {json.dumps(names, ensure_ascii=False)},
                axisLabel: {{ fontSize: 11, rotate: 30 }} }},
      yAxis: {{ type: 'value', axisLabel: {{ formatter: '{{value}}%' }} }},
      series: [{{
        type: 'bar',
        data: {json.dumps(values)},
        itemStyle: {{ color: function(p) {{ return p.data >= 0 ? '#1a73e8' : '#c62828'; }} }},
        label: {{ show: true, position: 'top', formatter: '{{c}}%', fontSize: 11 }}
      }}],
      grid: {{ left: 50, right: 20, top: 20, bottom: 60 }}
    }});
    ''')

    # GitHub trending
    trending = data.get('github_trending', [])
    if trending:
        repo_names = []
        stars = []
        for t in trending[:8]:
            if isinstance(t, dict):
                repo_names.append(str(t.get('name', t.get('repo', '?')))[:15])
                stars.append(int(t.get('stars', t.get('star_count', 0))))
        if repo_names:
            js_parts.append(f'''
    var ghChart = echarts.init(document.getElementById('chart-ai-github'));
    ghChart.setOption({{
      tooltip: {{ formatter: '{{b}}: ⭐{{c}}' }},
      xAxis: {{ type: 'value', name: 'Stars' }},
      yAxis: {{ type: 'category', data: {json.dumps(repo_names[::-1], ensure_ascii=False)},
                axisLabel: {{ fontSize: 11 }} }},
      series: [{{
        type: 'bar', data: {json.dumps(stars[::-1])},
        itemStyle: {{ color: '#ffa726' }},
        label: {{ show: true, position: 'right', formatter: '⭐{{c}}', fontSize: 11 }}
      }}],
      grid: {{ left: 130, right: 60, top: 10, bottom: 30 }}
    }});
    ''')

    return '\n'.join(js_parts)


def main():
    print('=' * 60)
    print('  情报系统 v2.0 预览生成器')
    print('  三条线并行生成，Claude Sonnet主力，独立子进程')
    print('=' * 60, flush=True)

    # 确保API Key可用
    # 1. Anthropic API Key（主力）— 从环境变量或ai_board_config.json读取
    ant_key = os.environ.get('ANTHROPIC_API_KEY', '')
    if not ant_key:
        # 尝试从本地配置文件读取（仅本地预览用）
        config_path = os.path.join(os.path.dirname(BASE_DIR), '集团基础设施', 'ai_board_config.json')
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as cf:
                config = json.load(cf)
            ant_key = config.get('anthropic_api_key', '')
            if ant_key:
                os.environ['ANTHROPIC_API_KEY'] = ant_key
                print(f'  ANTHROPIC_API_KEY: 从配置文件加载 ✅')
    if ant_key:
        print(f'  ANTHROPIC_API_KEY: ...{ant_key[-8:]} ✅')
    else:
        print('  ⚠️ ANTHROPIC_API_KEY 未设置，将使用OpenRouter fallback')

    # 2. OpenRouter API Key（fallback）
    or_key = os.environ.get('OPENROUTER_API_KEY', '')
    if not or_key:
        config_path = os.path.join(os.path.dirname(BASE_DIR), '集团基础设施', 'ai_board_config.json')
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as cf:
                config = json.load(cf)
            or_key = config.get('openrouter_api_key', '')
            if or_key:
                os.environ['OPENROUTER_API_KEY'] = or_key
                print(f'  OPENROUTER_API_KEY: 从配置文件加载 ✅')
    if or_key:
        print(f'  OPENROUTER_API_KEY: ...{or_key[-8:]} ✅')

    if not ant_key and not or_key:
        print('  ❌ 无可用API Key (ANTHROPIC_API_KEY 和 OPENROUTER_API_KEY 均未设置)!')
        sys.exit(1)

    t_start = time.time()

    # 并行运行三条线
    reports = {}
    chart_datas = {}
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {}
        for line_id, line_name, model_name, body in LINES:
            future = executor.submit(run_line, line_id, line_name, body)
            futures[future] = (line_id, line_name, model_name)

        for future in as_completed(futures):
            line_id, line_name, model_name = futures[future]
            try:
                report, chart_data = future.result()
                reports[line_id] = report
                chart_datas[line_id] = chart_data
            except Exception as e:
                reports[line_id] = f'## 生成失败\n\n线程异常: {e}'
                chart_datas[line_id] = {}

    elapsed_total = time.time() - t_start
    print(f'\n三条线全部完成，耗时 {elapsed_total:.1f}s', flush=True)

    # ===== 生成预览HTML =====
    bjt = timezone(timedelta(hours=8))
    now = datetime.now(bjt).strftime('%Y-%m-%d %H:%M BJT')

    badge_classes = {'crypto': 'badge-crypto', 'astock': 'badge-astock', 'ai': 'badge-ai'}
    model_names = {'crypto': 'Claude Sonnet', 'astock': 'Claude Sonnet', 'ai': 'Claude Sonnet'}
    line_labels = {'crypto': 'Line 2', 'astock': 'Line 3', 'ai': 'Line 4'}
    tab_labels = {'crypto': '🪙 加密投研日报', 'astock': '📈 A股交易情报', 'ai': '🤖 AI产业周报'}

    # 图表容器HTML
    crypto_charts_html = '''
    <div class="charts-section">
      <h3>📊 数据可视化</h3>
      <div class="chart-row">
        <div class="chart-box"><div class="chart-title">恐贪指数</div><div id="chart-fear-greed" class="chart-gauge"></div></div>
        <div class="chart-box"><div class="chart-title">24h 资产涨跌幅 (%)</div><div id="chart-assets" class="chart-bar"></div></div>
      </div>
      <div class="chart-row">
        <div class="chart-box wide"><div class="chart-title">资金费率热力图 (%, 8h)</div><div id="chart-funding-rates" class="chart-heatmap"></div></div>
      </div>
      <div class="chart-row">
        <div class="chart-box wide"><div class="chart-title">链上估值指标</div><div id="chart-onchain" class="chart-dual-gauge"></div></div>
      </div>
    </div>'''

    astock_charts_html = '''
    <div class="charts-section">
      <h3>📊 数据可视化</h3>
      <div class="chart-row">
        <div class="chart-box"><div class="chart-title">主要指数涨跌幅 (%)</div><div id="chart-astock-indices" class="chart-bar"></div></div>
        <div class="chart-box"><div class="chart-title">涨跌停统计</div><div id="chart-astock-limits" class="chart-gauge"></div></div>
      </div>
      <div class="chart-row">
        <div class="chart-box wide"><div class="chart-title">板块资金净流入 (亿元)</div><div id="chart-astock-sectors" class="chart-bar-h"></div></div>
      </div>
    </div>'''

    ai_charts_html = '''
    <div class="charts-section">
      <h3>📊 数据可视化</h3>
      <div class="chart-row">
        <div class="chart-box wide"><div class="chart-title">AI 概念股涨跌幅 (%)</div><div id="chart-ai-stocks" class="chart-bar"></div></div>
      </div>
      <div class="chart-row">
        <div class="chart-box wide"><div class="chart-title">GitHub Trending AI 项目</div><div id="chart-ai-github" class="chart-bar-h"></div></div>
      </div>
    </div>'''

    charts_html_map = {
        'crypto': crypto_charts_html,
        'astock': astock_charts_html,
        'ai': ai_charts_html,
    }

    tabs_html = ''
    content_html = ''
    for i, (line_id, _, _, _) in enumerate(LINES):
        active = ' active' if i == 0 else ''
        report_text = reports.get(line_id, '未生成')
        tabs_html += f'''  <div class="tab{active}" onclick="showTab('{line_id}')">
    {tab_labels[line_id]} <span class="badge {badge_classes[line_id]}">{model_names[line_id]}</span>
  </div>\n'''
        content_html += f'''  <div id="{line_id}" class="report{active}">
    <div class="meta">{line_labels[line_id]} | 主力模型: {model_names[line_id]} (Anthropic直连) | 报告长度: {len(report_text)} 字符</div>
    {charts_html_map.get(line_id, '')}
    {md_to_html(report_text)}
  </div>\n'''

    # 生成图表JS
    crypto_js = build_crypto_charts_js(chart_datas.get('crypto', {}))
    astock_js = build_astock_charts_js(chart_datas.get('astock', {}))
    ai_js = build_ai_charts_js(chart_datas.get('ai', {}))

    all_charts_js = f'''
    // === 加密投研图表 ===
    {crypto_js}
    // === A股情报图表 ===
    {astock_js}
    // === AI产业图表 ===
    {ai_js}
    // 自适应
    window.addEventListener('resize', function() {{
      document.querySelectorAll('[id^="chart-"]').forEach(function(el) {{
        var c = echarts.getInstanceByDom(el);
        if (c) c.resize();
      }});
    }});
    '''

    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>情报系统 v2.0 预览</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;
         background: #f5f5f5; color: #333; line-height: 1.8; }}
  .header {{ background: linear-gradient(135deg, #1a73e8, #0d47a1); color: white;
             padding: 30px; text-align: center; }}
  .header h1 {{ font-size: 28px; margin-bottom: 8px; }}
  .header p {{ opacity: 0.9; font-size: 14px; }}
  .tabs {{ display: flex; background: white; border-bottom: 2px solid #e0e0e0;
           position: sticky; top: 0; z-index: 100; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
  .tab {{ flex: 1; padding: 15px; text-align: center; cursor: pointer;
          font-size: 16px; font-weight: 600; border-bottom: 3px solid transparent;
          transition: all 0.3s; }}
  .tab:hover {{ background: #f0f7ff; }}
  .tab.active {{ border-bottom-color: #1a73e8; color: #1a73e8; }}
  .content {{ max-width: 1000px; margin: 20px auto; padding: 0 20px; }}
  .report {{ display: none; background: white; border-radius: 12px;
             box-shadow: 0 2px 12px rgba(0,0,0,0.08); padding: 30px; margin-bottom: 20px; }}
  .report.active {{ display: block; }}
  .report h2 {{ color: #1a73e8; font-size: 22px; margin: 30px 0 15px;
                padding-bottom: 10px; border-bottom: 2px solid #e8f0fe; }}
  .report h2:first-of-type {{ margin-top: 10px; }}
  .report h3 {{ color: #333; font-size: 18px; margin: 20px 0 10px; }}
  .report h4 {{ color: #555; font-size: 16px; margin: 15px 0 8px; }}
  .report p {{ margin: 10px 0; font-size: 15px; line-height: 1.9; }}
  .report strong {{ color: #c62828; }}
  .report hr {{ border: none; border-top: 1px solid #e0e0e0; margin: 25px 0; }}
  .report ul {{ margin: 8px 0 8px 20px; }}
  .report li {{ margin: 4px 0; font-size: 15px; line-height: 1.7; }}
  .badge {{ display: inline-block; padding: 3px 10px; border-radius: 12px;
            font-size: 12px; font-weight: 600; margin-left: 8px; }}
  .badge-crypto {{ background: #e3f2fd; color: #1565c0; }}
  .badge-astock {{ background: #fce4ec; color: #c62828; }}
  .badge-ai {{ background: #e8eaf6; color: #283593; }}
  .meta {{ color: #888; font-size: 13px; margin-bottom: 15px; padding-bottom: 10px;
           border-bottom: 1px dashed #e0e0e0; }}
  .footer {{ text-align: center; padding: 20px; color: #999; font-size: 13px; }}

  /* 图表样式 */
  .charts-section {{ background: #fafbfc; border-radius: 10px; padding: 20px; margin-bottom: 25px;
                     border: 1px solid #e8f0fe; }}
  .charts-section h3 {{ color: #1a73e8; margin-bottom: 15px; font-size: 17px; }}
  .chart-row {{ display: flex; gap: 15px; margin-bottom: 15px; flex-wrap: wrap; }}
  .chart-box {{ flex: 1; min-width: 280px; background: white; border-radius: 8px;
                padding: 15px; box-shadow: 0 1px 4px rgba(0,0,0,0.06); }}
  .chart-box.wide {{ flex: 100%; }}
  .chart-title {{ font-size: 13px; color: #666; font-weight: 600; margin-bottom: 8px; text-align: center; }}
  .chart-gauge {{ width: 100%; height: 200px; }}
  .chart-bar {{ width: 100%; height: 220px; }}
  .chart-bar-h {{ width: 100%; height: 280px; }}
  .chart-heatmap {{ width: 100%; height: 250px; }}
  .chart-dual-gauge {{ width: 100%; height: 220px; }}
</style>
</head>
<body>
<div class="header">
  <h1>📊 情报系统 v2.0 预览</h1>
  <p>生成时间: {now} | 耗时: {elapsed_total:.0f}秒 | 主力模型: Claude Sonnet (Anthropic直连)</p>
</div>
<div class="tabs">
{tabs_html}</div>
<div class="content">
{content_html}</div>
<div class="footer">
  ⚠️ 预览模式 — 董事长确认后推送Server酱<br>
  情报系统 v2.0 | Claude Sonnet 主力分析 | 7步发布流水线 Step 6/7
</div>
<script>
function showTab(id) {{
  document.querySelectorAll('.report').forEach(r => r.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  event.currentTarget.classList.add('active');
  // 触发ECharts图表resize
  setTimeout(function() {{
    document.querySelectorAll('#' + id + ' [id^="chart-"]').forEach(function(el) {{
      var c = echarts.getInstanceByDom(el);
      if (c) c.resize();
    }});
  }}, 100);
}}

// 初始化图表（等DOM和ECharts加载完）
document.addEventListener('DOMContentLoaded', function() {{
  try {{
    {all_charts_js}
  }} catch(e) {{
    console.error('图表初始化失败:', e);
  }}
}});
</script>
</body>
</html>'''

    preview_path = os.path.join(BASE_DIR, 'preview.html')
    with open(preview_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f'\n预览文件: {preview_path}')

    # 自动用浏览器打开
    import webbrowser
    webbrowser.open(preview_path)
    print('已在浏览器中打开预览页面')
    print('=== 完成 ===')


if __name__ == '__main__':
    main()
