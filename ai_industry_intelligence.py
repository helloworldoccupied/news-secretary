#!/usr/bin/env python3
"""
AI产业情报周报 v1.0 — AI Industry Intelligence Weekly
每周一08:00 BJT发布，覆盖算力供应链、模型进展、具身智能、政策监管、商业落地

数据管线（5大数据源）：
  1. AI公司股价：Yahoo Finance（NVDA/AMD/TSM/GOOGL/MSFT/META/AVGO）
  2. AI/ML论文趋势：arXiv API（cs.AI + cs.RO最新论文）
  3. GitHub AI趋势：GitHub API（AI/LLM/Robotics热门仓库）
  4. AI产业新闻：RSS feeds（TechCrunch/The Verge/机器之心/量子位）
  5. 算力市场：mempool.space算力趋势（与加密情报线共享）

分析：DeepSeek V3.2 via OpenRouter（主力），Gemini 3.1（备选）
推送：飞书卡片（主通道）+ Server酱状态通知（备用）
存档：Supabase daily_intelligence表（title前缀 [AI-Industry]）
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
SERVERCHAN_KEY = os.environ.get('SERVERCHAN_KEY', '')
SUPABASE_URL = os.environ.get('SUPABASE_URL', '')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY', '')

UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
BJT = timezone(timedelta(hours=8))
NOW_BJT = datetime.now(BJT)
TODAY_BJT = NOW_BJT.strftime('%Y-%m-%d')
WEEK_STR = f'{(NOW_BJT - timedelta(days=7)).strftime("%m/%d")}-{NOW_BJT.strftime("%m/%d")}'

# AI公司股票列表
AI_STOCKS = {
    'NVDA': 'NVIDIA',
    'AMD': 'AMD',
    'TSM': 'TSMC',
    'GOOGL': 'Google',
    'MSFT': 'Microsoft',
    'META': 'Meta',
    'AVGO': 'Broadcom',
}

# RSS源
RSS_FEEDS = [
    ('TechCrunch AI', 'https://techcrunch.com/category/artificial-intelligence/feed/'),
    ('The Verge AI', 'https://www.theverge.com/rss/ai-artificial-intelligence/index.xml'),
    ('机器之心', 'https://www.jiqizhixin.com/rss'),
    ('量子位', 'https://www.qbitai.com/feed'),
]

# AI相关关键词过滤
AI_KEYWORDS = re.compile(
    r'AI|人工智能|artificial.?intelligence|LLM|大模型|GPT|Claude|Gemini|DeepSeek|'
    r'机器学习|machine.?learning|deep.?learning|深度学习|神经网络|neural|'
    r'NVIDIA|英伟达|AMD|TSMC|台积电|GPU|芯片|chip|HBM|算力|compute|'
    r'机器人|robot|具身智能|embodied|humanoid|'
    r'自动驾驶|autonomous|自动化|automation|'
    r'OpenAI|Anthropic|Google.?AI|Meta.?AI|Microsoft.?AI|百度|阿里|腾讯|字节|'
    r'开源|open.?source|Llama|Mistral|Qwen|通义|'
    r'AGI|alignment|对齐|安全|safety|监管|regulat|policy|'
    r'融资|funding|投资|invest|估值|valuation|IPO|'
    r'数据中心|data.?center|cloud|云计算|edge|边缘计算|'
    r'diffusion|扩散|生成式|generative|AIGC|Sora|视频生成|'
    r'transformer|attention|推理|inference|训练|training|'
    r'Agent|智能体|RAG|向量|embedding|微调|fine.?tun',
    re.IGNORECASE
)


# ============================================================
# 工具函数
# ============================================================

def safe_float(val, default=0.0):
    """安全转float"""
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
        except json.JSONDecodeError:
            # 非JSON响应（如XML），返回原始bytes
            try:
                req2 = Request(url, headers=hdrs)
                return urlopen(req2, timeout=timeout).read()
            except Exception as e2:
                if attempt == retries:
                    print(f'  [FAIL] {url[:80]}... {e2}')
                    return None
                time.sleep(2)
        except Exception as e:
            if attempt == retries:
                print(f'  [FAIL] {url[:80]}... {e}')
                return None
            time.sleep(2)
    return None


def safe_get_xml(url, timeout=20):
    """安全获取XML内容"""
    hdrs = dict(UA)
    for attempt in range(3):
        try:
            req = Request(url, headers=hdrs)
            raw = urlopen(req, timeout=timeout).read()
            return ET.fromstring(raw)
        except Exception as e:
            if attempt == 2:
                print(f'  [FAIL XML] {url[:80]}... {e}')
                return None
            time.sleep(2)
    return None


def safe_get_json(url, timeout=20, headers=None):
    """安全获取JSON（明确JSON解析）"""
    hdrs = dict(UA)
    if headers:
        hdrs.update(headers)
    for attempt in range(3):
        try:
            req = Request(url, headers=hdrs)
            raw = urlopen(req, timeout=timeout).read()
            return json.loads(raw)
        except Exception as e:
            if attempt == 2:
                print(f'  [FAIL JSON] {url[:80]}... {e}')
                return None
            time.sleep(2)
    return None


# ============================================================
# 数据采集函数
# ============================================================

def collect_ai_stocks():
    """Step 1: AI公司股价 — Yahoo Finance 5日行情"""
    print('[1/5] AI公司股价...')
    result = {}

    for symbol, name in AI_STOCKS.items():
        data = safe_get_json(
            f'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=5d&interval=1d'
        )
        if data and data.get('chart', {}).get('result'):
            r = data['chart']['result'][0]
            meta = r.get('meta', {})
            quotes = r.get('indicators', {}).get('quote', [{}])[0]
            closes = quotes.get('close', [])
            volumes = quotes.get('volume', [])
            closes = [c for c in closes if c is not None]
            volumes = [v for v in volumes if v is not None]

            if closes:
                current = closes[-1]
                prev = closes[-2] if len(closes) > 1 else current
                change_1d_pct = (current - prev) / prev * 100 if prev else 0
                first = closes[0] if closes else current
                change_5d_pct = (current - first) / first * 100 if first else 0
                avg_vol = sum(volumes) / len(volumes) if volumes else 0

                result[symbol] = {
                    'name': name,
                    'price': round(current, 2),
                    'change_1d_pct': round(change_1d_pct, 2),
                    'change_5d_pct': round(change_5d_pct, 2),
                    'high_5d': round(max(closes), 2),
                    'low_5d': round(min(closes), 2),
                    'avg_volume': int(avg_vol),
                    'market_cap': meta.get('regularMarketPrice', 0),
                    'currency': meta.get('currency', 'USD'),
                }

        time.sleep(0.5)  # rate limit

    # 计算板块整体表现
    if result:
        changes = [v['change_5d_pct'] for v in result.values()]
        result['_sector_avg_5d'] = round(sum(changes) / len(changes), 2)
        # 找出领涨和领跌
        sorted_stocks = sorted(result.items(), key=lambda x: x[1].get('change_5d_pct', 0) if isinstance(x[1], dict) else 0, reverse=True)
        top = [(k, v) for k, v in sorted_stocks if isinstance(v, dict) and 'change_5d_pct' in v]
        if top:
            result['_leader'] = top[0][0]
            result['_laggard'] = top[-1][0]

    return result


def collect_arxiv_papers():
    """Step 2: AI/ML论文趋势 — arXiv API"""
    print('[2/5] arXiv论文趋势...')
    result = {'papers': [], 'categories': {}}

    root = safe_get_xml(
        'http://export.arxiv.org/api/query?search_query=cat:cs.AI+OR+cat:cs.RO&sortBy=submittedDate&max_results=20'
    )
    if root is None:
        return result

    ns = {'atom': 'http://www.w3.org/2005/Atom', 'arxiv': 'http://arxiv.org/schemas/atom'}

    for entry in root.findall('atom:entry', ns):
        title = (entry.findtext('atom:title', '', ns) or '').strip().replace('\n', ' ')
        summary = (entry.findtext('atom:summary', '', ns) or '').strip()[:300]
        published = entry.findtext('atom:published', '', ns) or ''
        link = ''
        for lnk in entry.findall('atom:link', ns):
            if lnk.get('type') == 'text/html':
                link = lnk.get('href', '')
                break

        # 分类标签
        categories = []
        for cat in entry.findall('atom:category', ns):
            term = cat.get('term', '')
            if term:
                categories.append(term)

        # 作者
        authors = []
        for author in entry.findall('atom:author', ns):
            name = author.findtext('atom:name', '', ns)
            if name:
                authors.append(name.strip())

        if title:
            result['papers'].append({
                'title': title,
                'summary': summary,
                'published': published[:10],
                'link': link,
                'categories': categories,
                'authors': authors[:3],  # 前3作者
            })
            # 统计分类
            for cat in categories:
                result['categories'][cat] = result['categories'].get(cat, 0) + 1

    return result


def collect_github_trending():
    """Step 3: GitHub AI趋势 — GitHub Search API"""
    print('[3/5] GitHub AI趋势...')
    result = {'trending': [], 'weekly_stars': []}

    # 按star排序的AI/LLM仓库（近期活跃）
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime('%Y-%m-%d')
    url = (
        f'https://api.github.com/search/repositories?'
        f'q=AI+OR+LLM+OR+robotics+pushed:>{week_ago}&sort=stars&order=desc&per_page=10'
    )
    gh_headers = {'Accept': 'application/vnd.github.v3+json'}
    data = safe_get_json(url, headers=gh_headers)
    if data and data.get('items'):
        for repo in data['items'][:10]:
            result['trending'].append({
                'name': repo.get('full_name', ''),
                'description': (repo.get('description') or '')[:150],
                'stars': repo.get('stargazers_count', 0),
                'forks': repo.get('forks_count', 0),
                'language': repo.get('language', ''),
                'updated': (repo.get('pushed_at') or '')[:10],
                'topics': repo.get('topics', [])[:5],
            })

    time.sleep(1)  # GitHub rate limit

    # 本周新创建的AI仓库（按star）
    url2 = (
        f'https://api.github.com/search/repositories?'
        f'q=AI+OR+LLM+created:>{week_ago}&sort=stars&order=desc&per_page=10'
    )
    data2 = safe_get_json(url2, headers=gh_headers)
    if data2 and data2.get('items'):
        for repo in data2['items'][:10]:
            result['weekly_stars'].append({
                'name': repo.get('full_name', ''),
                'description': (repo.get('description') or '')[:150],
                'stars': repo.get('stargazers_count', 0),
                'language': repo.get('language', ''),
                'created': (repo.get('created_at') or '')[:10],
            })

    return result


def collect_ai_news():
    """Step 4: AI产业新闻 — RSS feeds"""
    print('[4/5] AI产业新闻...')
    all_news = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)  # 一周内的新闻

    for source_name, feed_url in RSS_FEEDS:
        print(f'  [{source_name}]...', end=' ')
        try:
            root = safe_get_xml(feed_url, timeout=15)
            if root is None:
                print('失败')
                continue

            count = 0
            # RSS 2.0格式
            items = root.findall('.//item')
            # Atom格式
            if not items:
                ns = {'atom': 'http://www.w3.org/2005/Atom'}
                items = root.findall('atom:entry', ns)

            for item in items:
                # RSS 2.0
                title = (item.findtext('title') or '').strip()
                desc = (item.findtext('description') or '').strip()
                pub = item.findtext('pubDate') or item.findtext('published') or ''
                link = item.findtext('link') or ''

                # Atom格式
                if not title:
                    ns = {'atom': 'http://www.w3.org/2005/Atom'}
                    title = (item.findtext('atom:title', '', ns) or '').strip()
                    desc = (item.findtext('atom:summary', '', ns) or '').strip()
                    pub = item.findtext('atom:published', '', ns) or item.findtext('atom:updated', '', ns) or ''
                    for lnk in item.findall('atom:link', ns):
                        if lnk.get('rel', 'alternate') == 'alternate':
                            link = lnk.get('href', '')
                            break

                if not title:
                    continue

                # 时间过滤
                try:
                    if pub:
                        dt = parsedate_to_datetime(pub) if ',' in pub else datetime.fromisoformat(pub.replace('Z', '+00:00'))
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        if dt < cutoff:
                            continue
                except Exception:
                    pass  # 无法解析时间就不过滤

                # AI相关性过滤
                text = f'{title} {desc}'
                if not AI_KEYWORDS.search(text):
                    continue

                # 去HTML标签
                desc = re.sub(r'<[^>]+>', '', desc)[:200]

                all_news.append({
                    'source': source_name,
                    'title': title,
                    'desc': desc,
                    'link': link,
                    'pub': pub[:25],
                })
                count += 1

            print(f'{count}条')

        except Exception as e:
            print(f'异常: {e}')

    # 去重（标题相似度>80%视为重复）
    unique_news = []
    seen_titles = set()
    for n in all_news:
        # 简单去重：取标题前30字符
        key = re.sub(r'\s+', '', n['title'][:30].lower())
        if key not in seen_titles:
            seen_titles.add(key)
            unique_news.append(n)

    return unique_news[:50]  # 最多50条


def collect_compute_market():
    """Step 5: 算力市场 — mempool.space算力趋势"""
    print('[5/5] 算力市场...')
    result = {}

    # BTC全网算力趋势（60天）— 反映全球算力供需
    hr = safe_get_json('https://api.blockchain.info/charts/hash-rate?timespan=60days&format=json&sampled=true')
    if hr and 'values' in hr:
        vals = hr['values']
        if vals:
            rates = [v['y'] for v in vals if v.get('y')]
            if rates:
                current = rates[-1]
                prev_week = rates[-7] if len(rates) >= 7 else rates[0]
                prev_month = rates[-30] if len(rates) >= 30 else rates[0]
                result['hashrate'] = {
                    'current_eh': round(current / 1e6, 1),  # TH/s -> EH/s
                    'change_7d_pct': round((current - prev_week) / prev_week * 100, 2) if prev_week else 0,
                    'change_30d_pct': round((current - prev_month) / prev_month * 100, 2) if prev_month else 0,
                    'high_60d_eh': round(max(rates) / 1e6, 1),
                    'low_60d_eh': round(min(rates) / 1e6, 1),
                }

    # 难度调整（反映算力经济性）
    da = safe_get_json('https://mempool.space/api/v1/difficulty-adjustment')
    if da:
        result['difficulty'] = {
            'progress_pct': round(da.get('progressPercent', 0), 1),
            'estimated_change_pct': round(da.get('difficultyChange', 0), 2),
            'remaining_blocks': da.get('remainingBlocks', 0),
        }

    # 矿工收入（反映算力盈利能力）
    mr = safe_get_json('https://api.blockchain.info/charts/miners-revenue?timespan=30days&format=json&sampled=true')
    if mr and 'values' in mr:
        vals = [v['y'] for v in mr['values'] if v.get('y', 0) > 0]
        if vals:
            result['miners_revenue'] = {
                'today_usd': round(vals[-1]),
                'avg_30d_usd': round(sum(vals) / len(vals)),
                'trend': 'up' if vals[-1] > sum(vals) / len(vals) else 'down',
            }

    return result


# ============================================================
# 数据格式化
# ============================================================

def format_data_context(stocks, papers, github, news, compute):
    """将所有数据格式化为LLM的输入"""
    sections = []

    # 时间基准
    now_bjt = datetime.now(BJT)
    s = '## 时间基准\n'
    s += f'当前北京时间: {now_bjt.strftime("%Y-%m-%d %H:%M")} (BJT/UTC+8)\n'
    s += f'本期周报覆盖时段: {WEEK_STR}\n'
    s += f'所有分析中的时间引用必须使用北京时间。\n'
    sections.append(s)

    # AI公司股价
    s = '## AI公司股价（过去5个交易日）\n'
    if stocks:
        sector_avg = stocks.get('_sector_avg_5d', 0)
        leader = stocks.get('_leader', '')
        laggard = stocks.get('_laggard', '')
        s += f'AI板块5日平均涨跌: {sector_avg:+.2f}%\n'
        if leader and leader in stocks:
            s += f'领涨: {leader} ({stocks[leader]["name"]}) {stocks[leader]["change_5d_pct"]:+.2f}%\n'
        if laggard and laggard in stocks:
            s += f'领跌: {laggard} ({stocks[laggard]["name"]}) {stocks[laggard]["change_5d_pct"]:+.2f}%\n'
        s += '\n各公司详情:\n'
        for symbol in ['NVDA', 'AMD', 'TSM', 'GOOGL', 'MSFT', 'META', 'AVGO']:
            if symbol in stocks and isinstance(stocks[symbol], dict):
                st = stocks[symbol]
                s += f'  {symbol} ({st["name"]}): ${st["price"]:,.2f}'
                s += f' | 日涨跌{st["change_1d_pct"]:+.2f}% | 周涨跌{st["change_5d_pct"]:+.2f}%'
                s += f' | 5日区间${st["low_5d"]}-${st["high_5d"]}\n'
    else:
        s += '数据获取失败\n'
    sections.append(s)

    # arXiv论文
    s = '## AI/ML最新论文（arXiv cs.AI + cs.RO）\n'
    if papers.get('papers'):
        s += f'最新{len(papers["papers"])}篇论文:\n'
        for i, p in enumerate(papers['papers'][:15], 1):
            cats = ', '.join(p['categories'][:3])
            authors = ', '.join(p['authors']) if p['authors'] else '未知'
            s += f'{i}. [{p["published"]}] {p["title"]}\n'
            s += f'   作者: {authors} | 分类: {cats}\n'
            s += f'   摘要: {p["summary"][:200]}\n'
        if papers.get('categories'):
            s += '\n分类分布:\n'
            sorted_cats = sorted(papers['categories'].items(), key=lambda x: x[1], reverse=True)
            for cat, count in sorted_cats[:10]:
                s += f'  {cat}: {count}篇\n'
    else:
        s += '数据获取失败\n'
    sections.append(s)

    # GitHub趋势
    s = '## GitHub AI趋势\n'
    if github.get('trending'):
        s += '本周活跃AI仓库（按star排序）:\n'
        for i, repo in enumerate(github['trending'][:10], 1):
            topics = ', '.join(repo['topics']) if repo['topics'] else ''
            s += f'{i}. {repo["name"]} - {repo["stars"]:,} stars'
            if repo['language']:
                s += f' ({repo["language"]})'
            s += f'\n   {repo["description"]}\n'
            if topics:
                s += f'   标签: {topics}\n'
    if github.get('weekly_stars'):
        s += '\n本周新创建的热门AI仓库:\n'
        for i, repo in enumerate(github['weekly_stars'][:5], 1):
            s += f'{i}. {repo["name"]} - {repo["stars"]:,} stars'
            if repo['language']:
                s += f' ({repo["language"]})'
            s += f' | 创建于{repo["created"]}\n'
            s += f'   {repo["description"]}\n'
    if not github.get('trending') and not github.get('weekly_stars'):
        s += '数据获取失败\n'
    sections.append(s)

    # AI新闻
    s = '## AI产业新闻（过去7天）\n'
    if news:
        s += f'共{len(news)}条AI相关新闻:\n\n'
        # 按来源分组
        by_source = {}
        for n in news:
            src = n['source']
            if src not in by_source:
                by_source[src] = []
            by_source[src].append(n)
        for src, items in by_source.items():
            s += f'【{src}】({len(items)}条)\n'
            for n in items[:8]:
                s += f'  - {n["title"]}\n'
                if n['desc']:
                    s += f'    {n["desc"][:150]}\n'
            s += '\n'
    else:
        s += '无AI相关新闻\n'
    sections.append(s)

    # 算力市场
    s = '## 算力市场\n'
    if compute.get('hashrate'):
        hr = compute['hashrate']
        s += f'BTC全网算力: {hr["current_eh"]} EH/s\n'
        s += f'  7日变化: {hr["change_7d_pct"]:+.2f}%  30日变化: {hr["change_30d_pct"]:+.2f}%\n'
        s += f'  60日区间: {hr["low_60d_eh"]}-{hr["high_60d_eh"]} EH/s\n'
    if compute.get('difficulty'):
        da = compute['difficulty']
        s += f'难度调整进度: {da["progress_pct"]}%  预估变化: {da["estimated_change_pct"]:+.2f}%\n'
    if compute.get('miners_revenue'):
        mr = compute['miners_revenue']
        s += f'矿工日收入: ${mr["today_usd"]:,}  30日均值: ${mr["avg_30d_usd"]:,}  趋势: {mr["trend"]}\n'
    if not compute:
        s += '数据获取失败\n'
    sections.append(s)

    return '\n'.join(sections)


# ============================================================
# LLM分析
# ============================================================

AI_ANALYST_SYSTEM = """你是一位管理千亿级GPU算力基础设施的AI产业首席分析师，每周向集团董事长提交AI产业情报周报。

## 你的身份
- 你为一家拥有60,000+张GPU、12+ EFlops算力的基础设施公司工作
- 董事长关心的核心问题：GPU算力需求趋势、供应链变化、哪些AI应用在真正消耗算力
- 你的分析必须从"算力基础设施运营者"的视角出发，而非单纯的科技媒体视角

## 时间规范
- 所有时间引用必须使用**北京时间（BJT/UTC+8）**
- 本报告为周报，覆盖过去一周的重要事件和趋势

## 分析框架

### 算力供应链（最核心板块）
- NVIDIA产能与交付周期：H100/H200/B200/GB200各代产品供需
- HBM供应：SK Hynix/Samsung/Micron产能分配
- TSMC先进制程：CoWoS封装产能、3nm/2nm排期
- AMD竞争格局：MI300X/MI325X/MI400市场渗透率
- 国产替代：华为昇腾、寒武纪、海光等进展
- 对董事长的启示：供应紧张=我们的GPU资产增值，供应宽松=需关注定价策略

### 模型进展（算力需求端）
- 新模型发布：参数规模、训练算力消耗、推理效率
- 开源vs闭源：Llama/Mistral/Qwen等开源模型对算力民主化的影响
- 推理优化：量化/蒸馏/MoE等技术对GPU需求的影响
- Scaling Law最新验证：是否还在log-linear增长

### 具身智能（下一个算力大客户）
- 人形机器人：Figure/1X/Unitree/特斯拉Optimus/灵生科技等进展
- 自动驾驶：端到端大模型路线对算力需求的爆发
- 边缘算力需求：机器人需要什么级别的计算芯片

### 政策与监管
- 美国出口管制：实体清单更新、芯片出口限制、扩散规则
- 欧盟AI Act实施进展
- 中国政策：算力补贴、数据安全法、AI备案制度
- 对董事长的影响：出口管制=国内GPU供需缺口扩大=利好我们

### 商业落地
- 企业AI支出：云厂商CapEx、AI收入增速
- Killer App出现了吗？哪些应用在真正规模化消耗算力
- AI Agent/Copilot在企业的渗透率

### 美国实体清单追踪
- GLM-5董事会建议关注：新增实体、出口许可变化、合规风险

## 铁律
1. 不说"建议关注"、"值得关注" — 要说"对我们意味着什么"和"建议采取什么行动"
2. 每个判断给出数据支撑和逻辑链
3. 算力供应链分析必须量化到数字（芯片数量、产能utilization、交付周期）
4. 投资机会必须与董事长的GPU算力业务直接关联
5. 风险提示必须具体：不是"注意风险"，而是"如果X发生，我们应该Y"
6. 中国市场特殊关注：国产替代进展直接影响我们的竞争格局

## 输出格式要求（手机+电脑阅读）
- 用 ## 大标题（不要用###）
- 关键数字全部**加粗**
- 每段不超过4行
- 段落间用空行分隔
- 正负面emoji：🔴负面 🟡中性 🟢正面 ⚡冲突
- 不用表格（手机显示会乱）
- 分隔线 --- 分开大板块"""

AI_ANALYST_USER = """请基于以下本周数据，撰写AI产业情报周报。

要求：
1. 先找到本周1-2个核心事件/趋势，作为整篇报告的主线
2. 深度分析，不是新闻摘要——每个数据点都要解读"这对GPU算力业务意味着什么"
3. 所有判断给出因果链和数据支撑
4. 最后给出明确的行动建议（不是"建议关注"）

## 报告结构

**第一部分：本周核心判断**（最重要，放最前面）
- 本周AI产业最重要的1-2件事是什么？
- 对我们的GPU算力业务意味着什么？
- 具体行动建议

**第二部分：AI公司股价与市值**
- 七大AI公司本周表现
- 资本市场对AI的信心变化
- NVIDIA vs AMD竞争格局变化

**第三部分：算力供应链**
- GPU供需与定价趋势
- BTC算力变化反映的全球算力供需
- 算力基础设施投资动向

**第四部分：模型进展与算力需求**
- 本周重要论文和模型发布
- 哪些技术进展会改变算力需求曲线
- 开源vs闭源模型对算力民主化的影响

**第五部分：具身智能与机器人**
- 人形机器人最新进展
- 边缘算力需求增长
- 与GPU算力业务的关联

**第六部分：AI产业新闻精选**
- 按重要性排序的本周新闻
- 每条新闻给出影响判断和与算力业务的关联

**第七部分：政策与监管**
- 美国出口管制最新动态
- 中国AI政策变化
- 欧盟AI Act进展

**第八部分：投资机会与风险**
- 短期（1个月）: 具体操作建议
- 中期（3-6个月）: 战略布局建议
- 风险矩阵: Top 3风险 + 对冲方案

--- 以下是本周数据 ---

{data_context}"""


def call_llm_analysis(data_context):
    """调用LLM深度分析（DeepSeek via OpenRouter，备选Gemini）"""
    from llm_engine import call_llm
    print('\n调用LLM深度分析（DeepSeek -> Gemini fallback）...')
    user_msg = AI_ANALYST_USER.replace('{data_context}', data_context)
    return call_llm(
        system_prompt=AI_ANALYST_SYSTEM,
        user_prompt=user_msg,
        model='deepseek',
        fallback='gemini',
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
        push_serverchan_status('AI产业周报', '失败', 'LLM分析未返回结果')
        return

    title = f'【AI产业】{date_str} 周报 ({WEEK_STR})'

    # 优先飞书推送完整报告
    feishu_ok = push_feishu_report(title, analysis_text)

    if not feishu_ok:
        # 飞书不可用时 fallback 到 Server酱长报告
        push_serverchan_report(title, analysis_text)

    # Server酱只发状态通知
    push_serverchan_status('AI产业周报', '成功', f'{date_str} 周报已推送，{len(analysis_text)}字')


# ============================================================
# Supabase存档
# ============================================================

def save_to_supabase(date_str, analysis_text, data_summary):
    """存档到Supabase — 复用daily_intelligence表，title字段标记为AI-Industry类型"""
    if not SUPABASE_URL or not SUPABASE_KEY:
        print('  Supabase未配置，跳过存档')
        return

    try:
        row = {
            'date': date_str,
            'title': f'[AI-Industry] {date_str} AI产业情报周报',
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
    print(f'=== AI产业情报周报 v1.0 ===')
    print(f'日期: {TODAY_BJT}')
    print(f'覆盖周期: {WEEK_STR}')
    print(f'时间: {datetime.now(BJT).strftime("%H:%M:%S")} BJT\n')

    from notify import push_serverchan_status
    push_serverchan_status('AI产业周报', '开始', f'{TODAY_BJT} 数据采集中...')

    # Step 1-5: 数据采集
    stocks = collect_ai_stocks()
    papers = collect_arxiv_papers()
    github = collect_github_trending()
    news = collect_ai_news()
    compute = collect_compute_market()

    # 统计数据源状态
    sources_ok = 0
    sources_total = 5
    if stocks: sources_ok += 1
    if papers.get('papers'): sources_ok += 1
    if github.get('trending'): sources_ok += 1
    if news: sources_ok += 1
    if compute: sources_ok += 1
    print(f'\n数据源状态: {sources_ok}/{sources_total} 在线')

    # 格式化数据
    print('\n格式化数据...')
    data_context = format_data_context(stocks, papers, github, news, compute)
    print(f'  数据上下文: {len(data_context)} 字符')

    # LLM深度分析（DeepSeek via OpenRouter）
    analysis = call_llm_analysis(data_context)

    if analysis:
        print(f'\n分析报告: {len(analysis)} 字符')

        # 添加离线数据源标注
        offline_sources = []
        if not stocks:
            offline_sources.append('Yahoo Finance')
        if not papers.get('papers'):
            offline_sources.append('arXiv')
        if not github.get('trending'):
            offline_sources.append('GitHub')
        if not news:
            offline_sources.append('RSS新闻源')
        if not compute:
            offline_sources.append('算力市场')

        if offline_sources:
            analysis += f'\n\n---\n⚠️ 本期以下数据源离线: {", ".join(offline_sources)}\n'

        # 推送
        split_and_push(analysis, TODAY_BJT)

        # Supabase存档
        data_summary = {
            'stocks': {k: v for k, v in stocks.items() if isinstance(v, dict) and 'price' in v} if stocks else {},
            'papers_count': len(papers.get('papers', [])),
            'github_trending_count': len(github.get('trending', [])),
            'news_count': len(news),
            'hashrate_eh': compute.get('hashrate', {}).get('current_eh') if compute else None,
            'sources_online': sources_ok,
            'sources_total': sources_total,
            'week_range': WEEK_STR,
        }
        save_to_supabase(TODAY_BJT, analysis, data_summary)
    else:
        push_serverchan_status('AI产业周报', '失败', f'{TODAY_BJT} LLM分析未返回结果，请检查OpenRouter API Key')

    print('\n=== 完成 ===')


if __name__ == '__main__':
    main()
