#!/usr/bin/env python3
"""
新闻大秘 v3.0 — 陈总的AI新闻秘书
每日08:00/20:00 采集→摘要→推送
覆盖: AI/机器人 | 加密货币 | 宏观经济/政策 | 供应链预判
v2.0: OKX实时数据、多维市场指标、大幅扩充新闻源、深度分析prompt升级
v3.0: 推送渠道从企微切换为飞书群消息（无IP白名单限制），支持GitHub Actions运行
"""
import sys
import os
import io
import requests
import json
import time
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

# Windows GBK兼容：强制stdout为UTF-8
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# ========== 配置 ==========
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "sk-461aecaf772847afb2d08aa11458ffdc")
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://dmdicqhkjefxethauypp.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImRtZGljcWhramVmeGV0aGF1eXBwIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc2OTgxMTMyMiwiZXhwIjoyMDg1Mzg3MzIyfQ.hAbf2cC97-iLsmplti_S1HjnKS0h7nbs9plmkKqlMsc")

# 飞书配置
FEISHU_APP_ID = os.environ.get("FEISHU_APP_ID", "cli_a91d4284fdb8dbd1")
FEISHU_APP_SECRET = os.environ.get("FEISHU_APP_SECRET", "c5Ay0goMYhmVIEi6MGJfdl4Q21eH8raO")
FEISHU_CHAT_ID = os.environ.get("FEISHU_CHAT_ID", "oc_123fc3961f8f42051abeddd78760f4c1")  # 国兴超链新闻组
FEISHU_API = "https://open.feishu.cn"

BJT = timezone(timedelta(hours=8))
UA = {"User-Agent": "NewsSecretary/2.0 (+https://chaoshpc.com)"}

CATEGORIES = {
    "ai_robot": {"name": "AI与机器人", "emoji": "🤖"},
    "crypto":   {"name": "加密货币", "emoji": "💰"},
    "macro":    {"name": "宏观经济与政策", "emoji": "📈"},
}

# ========== 新闻源配置（v2.0 大幅扩充） ==========
RSS_SOURCES = [
    # ===== AI/科技 — 海外权威 =====
    {"name": "TechCrunch", "url": "https://techcrunch.com/feed/", "category": "ai_robot", "max": 12},
    {"name": "The Verge", "url": "https://www.theverge.com/rss/index.xml", "category": "ai_robot", "max": 10},
    {"name": "Ars Technica", "url": "https://feeds.arstechnica.com/arstechnica/technology-lab", "category": "ai_robot", "max": 10},
    {"name": "MIT Tech Review", "url": "https://www.technologyreview.com/feed/", "category": "ai_robot", "max": 8},
    {"name": "VentureBeat", "url": "https://venturebeat.com/feed/", "category": "ai_robot", "max": 8},
    {"name": "Wired", "url": "https://www.wired.com/feed/rss", "category": "ai_robot", "max": 8},
    {"name": "IEEE Spectrum", "url": "https://spectrum.ieee.org/feeds/topic/robotics.rss", "category": "ai_robot", "max": 6},
    {"name": "The Robot Report", "url": "https://www.therobotreport.com/feed/", "category": "ai_robot", "max": 6},
    # ===== AI/科技 — 官方博客 =====
    {"name": "OpenAI Blog", "url": "https://openai.com/blog/rss.xml", "category": "ai_robot", "max": 5},
    {"name": "Google AI Blog", "url": "https://blog.google/technology/ai/rss/", "category": "ai_robot", "max": 5},
    {"name": "Anthropic Blog", "url": "https://www.anthropic.com/feed.xml", "category": "ai_robot", "max": 5},
    {"name": "NVIDIA Blog", "url": "https://blogs.nvidia.com/feed/", "category": "ai_robot", "max": 5},
    {"name": "Meta AI Blog", "url": "https://ai.meta.com/blog/rss/", "category": "ai_robot", "max": 5},
    {"name": "DeepMind Blog", "url": "https://deepmind.google/blog/rss.xml", "category": "ai_robot", "max": 5},
    {"name": "HuggingFace Blog", "url": "https://huggingface.co/blog/feed.xml", "category": "ai_robot", "max": 5},
    # ===== AI/科技 — 中文 =====
    {"name": "机器之心", "url": "https://www.jiqizhixin.com/rss", "category": "ai_robot", "max": 8},
    {"name": "量子位", "url": "https://www.qbitai.com/feed", "category": "ai_robot", "max": 8},
    {"name": "36氪AI", "url": "https://36kr.com/feed", "category": "ai_robot", "max": 8},
    # ===== 加密货币 — 海外权威 =====
    {"name": "CoinDesk", "url": "https://www.coindesk.com/arc/outboundfeeds/rss/", "category": "crypto", "max": 10},
    {"name": "CoinTelegraph", "url": "https://cointelegraph.com/rss", "category": "crypto", "max": 10},
    {"name": "The Block", "url": "https://www.theblock.co/rss.xml", "category": "crypto", "max": 8},
    {"name": "Bitcoin Magazine", "url": "https://bitcoinmagazine.com/feed", "category": "crypto", "max": 6},
    {"name": "Decrypt", "url": "https://decrypt.co/feed", "category": "crypto", "max": 6},
    {"name": "DL News", "url": "https://www.dlnews.com/arc/outboundfeeds/rss/", "category": "crypto", "max": 6},
    # ===== 加密货币 — 中文 =====
    {"name": "金色财经", "url": "https://www.jinse.cn/rss", "category": "crypto", "max": 8},
    {"name": "PANews", "url": "https://www.panewslab.com/rss/index.html", "category": "crypto", "max": 6},
    {"name": "律动BlockBeats", "url": "https://www.theblockbeats.info/rss", "category": "crypto", "max": 6},
    # ===== 宏观 =====
    {"name": "Reuters via GNews", "url": "https://news.google.com/rss/search?q=site:reuters.com+technology+OR+economy&hl=en-US&gl=US&ceid=US:en", "category": "macro", "max": 10},
    {"name": "Bloomberg via GNews", "url": "https://news.google.com/rss/search?q=site:bloomberg.com+economy+OR+technology+OR+markets&hl=en-US&gl=US&ceid=US:en", "category": "macro", "max": 8},
    {"name": "WSJ via GNews", "url": "https://news.google.com/rss/search?q=site:wsj.com+economy+OR+technology+OR+markets&hl=en-US&gl=US&ceid=US:en", "category": "macro", "max": 8},
    # ===== Google News 关键词聚合 =====
    {"name": "GNews AI", "url": "https://news.google.com/rss/search?q=artificial+intelligence+OR+LLM+OR+OpenAI+OR+Anthropic+OR+GPU+shortage&hl=en-US&gl=US&ceid=US:en", "category": "ai_robot", "max": 10},
    {"name": "GNews Crypto", "url": "https://news.google.com/rss/search?q=bitcoin+OR+ethereum+OR+crypto+regulation+OR+BTC+ETF&hl=en-US&gl=US&ceid=US:en", "category": "crypto", "max": 10},
    {"name": "GNews Robot", "url": "https://news.google.com/rss/search?q=humanoid+robot+OR+embodied+AI+OR+Figure+AI+OR+Optimus+OR+Unitree&hl=en-US&gl=US&ceid=US:en", "category": "ai_robot", "max": 8},
    {"name": "GNews Macro", "url": "https://news.google.com/rss/search?q=federal+reserve+OR+CPI+OR+trade+war+OR+tariff+OR+interest+rate&hl=en-US&gl=US&ceid=US:en", "category": "macro", "max": 8},
    # ===== X/Twitter 热点（通过Google News聚合搜索替代，Nitter实例不稳定）=====
    {"name": "X-AI热点", "url": "https://news.google.com/rss/search?q=site:x.com+OR+site:twitter.com+AI+OR+GPT+OR+robot&hl=en-US&gl=US&ceid=US:en", "category": "ai_robot", "max": 8},
    {"name": "X-Crypto热点", "url": "https://news.google.com/rss/search?q=site:x.com+OR+site:twitter.com+bitcoin+OR+crypto+OR+BTC&hl=en-US&gl=US&ceid=US:en", "category": "crypto", "max": 8},
]

# ========== RSS通用采集器 ==========
def fetch_rss(name, url, max_items=10):
    """通用RSS采集，支持RSS 2.0和Atom"""
    news = []
    try:
        resp = requests.get(url, timeout=8, headers=UA)
        resp.encoding = resp.apparent_encoding
        root = ET.fromstring(resp.content)

        # RSS 2.0: .//item  |  Atom: .//entry (带namespace)
        items = root.findall(".//item")
        if not items:
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            items = root.findall(".//atom:entry", ns)
            for item in items[:max_items]:
                title = (item.findtext("atom:title", "", ns)).strip()
                link_el = item.find("atom:link", ns)
                link = link_el.get("href", "") if link_el is not None else ""
                desc = (item.findtext("atom:summary", "", ns) or item.findtext("atom:content", "", ns) or "").strip()
                desc = re.sub(r'<[^>]+>', '', desc)[:300]
                if title:
                    news.append({"title": title, "source": name, "link": link, "desc": desc})
        else:
            for item in items[:max_items]:
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                desc = (item.findtext("description") or "").strip()
                desc = re.sub(r'<[^>]+>', '', desc)[:300]
                if title:
                    news.append({"title": title, "source": name, "link": link, "desc": desc})
    except Exception as e:
        print(f"  [RSS {name}] {e}")
    return news


# ========== 财联社快讯 ==========
def fetch_cls(max_items=20):
    """财联社电报——中国政策/A股独家快讯"""
    news = []
    try:
        resp = requests.get(
            "https://www.cls.cn/nodeapi/updateTelegraphList",
            params={"app": "CailianpressWeb", "os": "web", "rn": max_items, "sv": "8.4.6"},
            headers=UA, timeout=12
        )
        data = resp.json()
        for item in data.get("data", {}).get("roll_data", []):
            title = (item.get("title") or item.get("content", "")[:80]).strip()
            if not title:
                continue
            content = item.get("content", "")[:300]
            news.append({
                "title": title,
                "source": "财联社",
                "link": f"https://www.cls.cn/detail/{item.get('id', '')}",
                "desc": content,
            })
    except Exception as e:
        print(f"  [财联社] {e}")
    return news


# ========== OKX + 多维市场数据 ==========
def get_market_data():
    """从OKX和多个数据源获取完整市场快照"""
    data = {}

    # --- OKX BTC/USDT 实时价格 ---
    try:
        r = requests.get("https://www.okx.com/api/v5/market/ticker?instId=BTC-USDT", timeout=10)
        d = r.json()["data"][0]
        price = float(d["last"])
        open24h = float(d["open24h"])
        high = float(d["high24h"])
        low = float(d["low24h"])
        vol = float(d["volCcy24h"])
        change_pct = (price - open24h) / open24h * 100
        data["btc_price"] = price
        data["btc_change"] = change_pct
        data["btc_high"] = high
        data["btc_low"] = low
        data["btc_vol_usd"] = vol
        data["btc_str"] = f"BTC ${price:,.0f} ({'+' if change_pct >= 0 else ''}{change_pct:.2f}%)"
        data["btc_range"] = f"${low:,.0f} - ${high:,.0f}"
        data["btc_vol_str"] = f"${vol/1e8:.1f}亿" if vol > 1e8 else f"${vol/1e6:.0f}M"
        print(f"  OKX BTC: ${price:,.0f} ({'+' if change_pct >= 0 else ''}{change_pct:.2f}%)")
    except Exception as e:
        print(f"  [OKX BTC] {e}")

    # --- OKX ETH/USDT ---
    try:
        r = requests.get("https://www.okx.com/api/v5/market/ticker?instId=ETH-USDT", timeout=10)
        d = r.json()["data"][0]
        eth_price = float(d["last"])
        eth_open = float(d["open24h"])
        eth_change = (eth_price - eth_open) / eth_open * 100
        data["eth_price"] = eth_price
        data["eth_change"] = eth_change
        data["eth_str"] = f"ETH ${eth_price:,.0f} ({'+' if eth_change >= 0 else ''}{eth_change:.2f}%)"
    except Exception as e:
        print(f"  [OKX ETH] {e}")

    # --- OKX 资金费率 ---
    try:
        r = requests.get("https://www.okx.com/api/v5/public/funding-rate?instId=BTC-USDT-SWAP", timeout=10)
        d = r.json()["data"][0]
        funding = float(d["fundingRate"]) * 100
        data["funding_rate"] = funding
        data["funding_str"] = f"{funding:+.4f}%"
        # 年化
        data["funding_annual"] = f"{funding * 3 * 365:.1f}%"
    except Exception as e:
        print(f"  [OKX Funding] {e}")

    # --- OKX 多空持仓比 ---
    try:
        r = requests.get("https://www.okx.com/api/v5/rubik/stat/contracts/long-short-account-ratio?ccy=BTC&period=1H", timeout=10)
        d = r.json()["data"]
        if d:
            ratio = float(d[0][1])
            data["long_short_ratio"] = ratio
            data["ls_str"] = f"{ratio:.2f}:1"
            if ratio > 2:
                data["ls_signal"] = "多头拥挤"
            elif ratio < 0.8:
                data["ls_signal"] = "空头拥挤"
            else:
                data["ls_signal"] = "均衡"
    except Exception as e:
        print(f"  [OKX L/S] {e}")

    # --- 恐贪指数 ---
    try:
        r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=10)
        d = r.json()["data"][0]
        fng_val = int(d["value"])
        fng_cls = d["value_classification"]
        data["fng_value"] = fng_val
        data["fng_class"] = fng_cls
        # 中文化
        fng_cn = {"Extreme Fear": "极度恐惧", "Fear": "恐惧", "Neutral": "中性",
                  "Greed": "贪婪", "Extreme Greed": "极度贪婪"}.get(fng_cls, fng_cls)
        data["fng_str"] = f"{fng_val} ({fng_cn})"
    except Exception as e:
        print(f"  [FNG] {e}")

    # --- mempool 手续费+难度 ---
    try:
        r = requests.get("https://mempool.space/api/v1/fees/recommended", timeout=10)
        d = r.json()
        data["btc_fee"] = f"{d.get('fastestFee',0)}/{d.get('halfHourFee',0)}/{d.get('hourFee',0)} sat/vB"
    except Exception as e:
        print(f"  [Mempool Fee] {e}")
    try:
        r = requests.get("https://mempool.space/api/v1/difficulty-adjustment", timeout=10)
        d = r.json()
        progress = d.get("progressPercent", 0)
        change = d.get("difficultyChange", 0)
        data["diff_str"] = f"进度{progress:.0f}% 预计{'+' if change >= 0 else ''}{change:.1f}%"
    except Exception as e:
        print(f"  [Mempool Diff] {e}")

    return data


# ========== 分类器 ==========
KW_AI = {"ai", "artificial intelligence", "llm", "gpt", "openai", "anthropic", "claude",
         "deepseek", "gemini", "nvidia", "gpu", "chip", "robot", "humanoid", "embodied",
         "transformer", "diffusion", "neural", "training", "inference", "算力", "芯片",
         "机器人", "大模型", "人工智能", "具身", "智能", "figure", "optimus", "unitree",
         "boston dynamics", "tesla bot", "宇树", "智元"}
KW_CRYPTO = {"bitcoin", "btc", "ethereum", "eth", "crypto", "blockchain", "defi", "web3",
             "stablecoin", "nft", "exchange", "binance", "coinbase", "sec", "etf", "okx",
             "比特币", "以太坊", "加密", "区块链", "交易所", "监管", "稳定币", "矿机", "mining"}
KW_MACRO = {"fed", "federal reserve", "interest rate", "cpi", "gdp", "inflation", "tariff",
            "trade war", "fiscal", "monetary", "recession", "employment", "treasury",
            "央行", "利率", "cpi", "gdp", "通胀", "关税", "贸易", "财政", "货币", "经济",
            "政策", "降准", "降息", "semiconductor", "supply chain", "制裁", "sanctions"}

def classify(text):
    """根据关键词判断新闻类别"""
    t = text.lower()
    scores = {"ai_robot": 0, "crypto": 0, "macro": 0}
    for kw in KW_AI:
        if kw in t:
            scores["ai_robot"] += 1
    for kw in KW_CRYPTO:
        if kw in t:
            scores["crypto"] += 1
    for kw in KW_MACRO:
        if kw in t:
            scores["macro"] += 1
    if max(scores.values()) == 0:
        return None
    return max(scores, key=scores.get)


# ========== 采集所有新闻 ==========
def collect_all_news():
    """从所有源采集新闻"""
    all_news = []

    # RSS源
    for src in RSS_SOURCES:
        items = fetch_rss(src["name"], src["url"], src.get("max", 10))
        for n in items:
            n["category"] = src["category"]
        all_news += items
        print(f"  {src['name']}: {len(items)}条")
        time.sleep(0.2)

    # 财联社
    cls_items = fetch_cls(20)
    for n in cls_items:
        cat = classify(n["title"] + " " + n.get("desc", ""))
        n["category"] = cat or "macro"
    all_news += cls_items
    print(f"  财联社: {len(cls_items)}条")

    return all_news


# ========== 去重 ==========
def fuzzy_dedup(news_list, threshold=0.50):
    """模糊去重: 标题词集重合度>50%视为重复"""
    unique = []
    seen_words = []
    for n in news_list:
        words = set(re.findall(r'\w{2,}', n["title"].lower()))
        if not words:
            continue
        is_dup = False
        for prev in seen_words:
            overlap = len(words & prev) / max(len(words | prev), 1)
            if overlap > threshold:
                is_dup = True
                break
        if not is_dup:
            unique.append(n)
            seen_words.append(words)
    return unique


# ========== DeepSeek摘要引擎 v2.0 ==========
def deepseek_summarize(news_by_cat, market_data):
    """调用DeepSeek，把原始新闻+市场数据→结构化中文摘要+供应链预判"""
    # 构建新闻素材文本
    parts = []

    # 市场数据作为上下文
    parts.append("## 实时市场数据（来自OKX等）")
    if market_data.get("btc_str"):
        parts.append(f"- BTC: {market_data['btc_str']}，24h区间 {market_data.get('btc_range','N/A')}，成交额 {market_data.get('btc_vol_str','N/A')}")
    if market_data.get("eth_str"):
        parts.append(f"- ETH: {market_data['eth_str']}")
    if market_data.get("funding_str"):
        parts.append(f"- BTC永续资金费率: {market_data['funding_str']}（年化 {market_data.get('funding_annual','N/A')}）")
    if market_data.get("ls_str"):
        parts.append(f"- 多空持仓比: {market_data['ls_str']}（{market_data.get('ls_signal','N/A')}）")
    if market_data.get("fng_str"):
        parts.append(f"- 恐惧贪婪指数: {market_data['fng_str']}")
    if market_data.get("btc_fee"):
        parts.append(f"- BTC手续费: {market_data['btc_fee']}")
    if market_data.get("diff_str"):
        parts.append(f"- 难度调整: {market_data['diff_str']}")
    parts.append("")

    for cat_key, cat_info in CATEGORIES.items():
        items = news_by_cat.get(cat_key, [])
        if not items:
            continue
        parts.append(f"\n## {cat_info['name']} ({len(items)}条)")
        for i, n in enumerate(items[:25], 1):  # 每类最多25条送给DeepSeek
            line = f"{i}. [{n['source']}] {n['title']}"
            if n.get("desc"):
                line += f" — {n['desc']}"
            if n.get("link"):
                line += f" | 链接: {n['link']}"
            parts.append(line)

    news_text = "\n".join(parts)
    if not news_text.strip():
        return None

    system_prompt = """你是CEO的首席情报分析师。

你的老板管理着BTC矿场（26个F2Pool子账户）、GPU算力中心（chaoshpc.com）、关注人形机器人投资、并持有加密货币仓位。他每天只看你这一份简报，所以每个字都必须有价值。

## 输入说明
你会收到两部分数据：
1. **实时市场数据**：来自OKX的BTC/ETH价格、资金费率、多空比、恐贪指数等——这些是事实，直接使用，不要猜测
2. **新闻素材**：来自多个源的新闻标题和摘要，每条都附有原文链接

## 核心原则
- 每个领域选出**3-5条最重要**的新闻，不是最多3条——如果当天信息密度高，可以选5条
- 每条新闻必须保留原文链接（link字段），这非常重要
- 分析要有深度：为什么重要？对老板的业务意味着什么？应该关注什么？
- 市场数据部分直接使用输入的OKX数据，不要自己编造价格
- 语气像高盛首席分析师写给VIP客户的morning brief

## 每条新闻的分析要求
1. **event**: 一句话说清楚发生了什么（中文，25字以内）
2. **analysis**: 深度分析段落（150-300字），必须包含：
   - 事件背景和来龙去脉
   - 对行业的影响和战略意义
   - 对老板业务的具体影响（矿场运营/算力销售/机器人投资/加密持仓）
   - 如有历史类似事件，做对照分析
   - 可操作的建议或关注点
3. **source**: 新闻来源名
4. **link**: 原文链接URL（必须保留，从素材中提取）

## 领域总结（summary）
不是罗列要点。写一段完整的趋势研判（5-8句），回答：
- 当前处于什么周期阶段？
- 关键指标在说什么？（引用实时市场数据）
- 方向性判断和拐点信号

## 市场数据解读（market_analysis）
专门针对OKX市场数据写一段解读（3-5句）：资金费率、多空比、恐贪指数各说明了什么？综合来看是什么信号？对矿场运营和持仓策略有什么建议？

## 今日洞察（insight）
跨领域的战略级判断（5-8句）。要具体、可操作、有时间维度。

## 供应链预判
有信号时深度分析，没有就设has_signal=false。

## 输出格式（严格JSON）
{
  "market_analysis": "基于OKX数据的市场解读(3-5句)",
  "ai_robot": {
    "summary": "5-8句趋势研判",
    "items": [
      {
        "event": "25字以内事件描述",
        "analysis": "150-300字深度分析",
        "source": "来源名",
        "link": "原文链接URL"
      }
    ]
  },
  "crypto": {
    "summary": "趋势研判(引用实时数据)",
    "items": [同上格式]
  },
  "macro": {
    "summary": "趋势研判",
    "items": [同上格式]
  },
  "insight": "跨领域战略判断(5-8句)",
  "supply_chain": {
    "has_signal": true/false,
    "trigger": "触发品类",
    "root_cause": "根因链条(追溯2-3个环节)",
    "impact": "影响分析",
    "watchlist": ["品类1: 原因", "品类2: 原因"],
    "confidence": "高/中/低"
  }
}

全部用中文，专业术语保留英文缩写。只输出JSON。"""

    try:
        resp = requests.post(
            DEEPSEEK_URL,
            headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"以下是今日采集到的市场数据和新闻素材，请整理成简报：\n{news_text}"}
                ],
                "temperature": 0.3,
                "max_tokens": 8192,
                "response_format": {"type": "json_object"}
            },
            timeout=120
        )
        data = resp.json()
        if "error" in data:
            print(f"  [DeepSeek API Error] {data['error']}")
            return None
        if "choices" not in data:
            print(f"  [DeepSeek] Unexpected response keys: {list(data.keys())}")
            return None
        content = data["choices"][0]["message"]["content"]
        return json.loads(content)
    except json.JSONDecodeError as e:
        print(f"  [DeepSeek JSON] {e}")
        print(f"  Raw content (first 500): {content[:500]}")
        return None
    except Exception as e:
        print(f"  [DeepSeek] {e}")
        return None


# ========== 消息排版 v2.0 ==========
NUM_ICONS = ["①", "②", "③", "④", "⑤"]

def build_message(ds_result, news_by_cat, market_data):
    """构建大秘汇报风格的Markdown消息"""
    now = datetime.now(BJT)
    slot = "晨报" if now.hour < 14 else "晚报"
    title = f"要闻简报 · {now.strftime('%m月%d日')}{slot}"

    lines = [
        f"# {title}",
        "",
    ]

    # ===== 市场仪表盘 =====
    lines.append("## 📊 市场仪表盘")
    lines.append("")
    if market_data.get("btc_str"):
        lines.append(f"> **{market_data['btc_str']}**")
        parts = []
        if market_data.get("btc_range"):
            parts.append(f"24h区间: {market_data['btc_range']}")
        if market_data.get("btc_vol_str"):
            parts.append(f"成交额: {market_data['btc_vol_str']}")
        if parts:
            lines.append(f"> {' | '.join(parts)}")
    if market_data.get("eth_str"):
        lines.append(f"> {market_data['eth_str']}")
    extra = []
    if market_data.get("funding_str"):
        extra.append(f"资金费率: {market_data['funding_str']}")
    if market_data.get("ls_str"):
        extra.append(f"多空比: {market_data['ls_str']}({market_data.get('ls_signal','')})")
    if market_data.get("fng_str"):
        extra.append(f"恐贪: {market_data['fng_str']}")
    if extra:
        lines.append(f"> {' | '.join(extra)}")
    chain_info = []
    if market_data.get("btc_fee"):
        chain_info.append(f"手续费: {market_data['btc_fee']}")
    if market_data.get("diff_str"):
        chain_info.append(f"难度: {market_data['diff_str']}")
    if chain_info:
        lines.append(f"> {' | '.join(chain_info)}")
    lines.append("")

    # ===== 市场数据解读 =====
    if ds_result and ds_result.get("market_analysis"):
        lines.append(ds_result["market_analysis"])
        lines.append("")

    lines.append("---")
    lines.append("")

    if ds_result:
        # 各领域板块
        for cat_key, cat_info in CATEGORIES.items():
            cat_data = ds_result.get(cat_key)
            if not cat_data or not cat_data.get("items"):
                continue

            lines.append(f"## {cat_info['emoji']} {cat_info['name']}")
            lines.append("")

            # 趋势研判
            summary = cat_data.get("summary", "")
            if summary:
                lines.append(f"> {summary}")
                lines.append("")

            # 深度分析条目
            for i, item in enumerate(cat_data.get("items", [])[:5]):
                icon = NUM_ICONS[i] if i < len(NUM_ICONS) else f"({i+1})"
                event = item.get("event", item.get("headline", ""))
                analysis = item.get("analysis", "")
                source = item.get("source", "")
                link = item.get("link", "")

                lines.append(f"**{icon} {event}**")
                lines.append("")
                if analysis:
                    lines.append(analysis)
                    lines.append("")
                if link and link.startswith("http"):
                    lines.append(f"🔗 [{source}]({link})")
                elif source:
                    lines.append(f"— {source}")
                lines.append("")

            lines.append("---")
            lines.append("")

        # 战略洞察
        insight = ds_result.get("insight", "")
        if insight:
            lines.append("## 💡 战略洞察")
            lines.append("")
            lines.append(insight)
            lines.append("")
            lines.append("---")
            lines.append("")

        # 供应链预判（仅有信号时显示）
        sc = ds_result.get("supply_chain", {})
        if sc.get("has_signal"):
            confidence = sc.get("confidence", "中")
            lines.append(f"## ⚡ 供应链预判（置信度: {confidence}）")
            lines.append("")
            trigger = sc.get("trigger", "")
            root_cause = sc.get("root_cause", sc.get("analysis", ""))
            impact = sc.get("impact", "")
            if trigger:
                lines.append(f"> {trigger}")
                lines.append("")
            if root_cause:
                lines.append(f"**根因链条**: {root_cause}")
                lines.append("")
            if impact:
                lines.append(f"**影响判断**: {impact}")
                lines.append("")
            watchlist = sc.get("watchlist", [])
            if watchlist:
                lines.append("**关注品类**:")
                for w in watchlist:
                    lines.append(f"- {w}")
                lines.append("")
            lines.append("---")
            lines.append("")

    else:
        # DeepSeek失败，降级为原始标题
        lines.append("> ⚠️ AI摘要暂不可用，以下为原始要闻")
        lines.append("")
        for cat_key, cat_info in CATEGORIES.items():
            items = news_by_cat.get(cat_key, [])
            if not items:
                continue
            lines.append(f"## {cat_info['emoji']} {cat_info['name']}")
            lines.append("")
            for i, n in enumerate(items[:8]):
                icon = NUM_ICONS[i] if i < len(NUM_ICONS) else f"({i+1})"
                if n.get("link"):
                    lines.append(f"**{icon}** [{n['title']}]({n['link']})")
                else:
                    lines.append(f"**{icon}** {n['title']} ({n['source']})")
            lines.append("")
            lines.append("---")
            lines.append("")

    # 底部统计
    total = sum(len(v) for v in news_by_cat.values())
    selected = sum(len(ds_result.get(k, {}).get("items", [])) for k in CATEGORIES) if ds_result else 0
    src_count = len(RSS_SOURCES) + 1  # +1 for 财联社
    lines.append(f"*{src_count}个信息源采集{total}条 → DeepSeek精选{selected}条 · 新闻大秘 v3.0*")

    return title, "\n".join(lines)


# ========== 飞书推送 ==========
def get_feishu_token():
    """获取飞书 tenant_access_token"""
    try:
        r = requests.post(
            f"{FEISHU_API}/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET},
            timeout=10
        )
        d = r.json()
        if d.get("code") == 0:
            return d["tenant_access_token"]
        print(f"  飞书token失败: {d.get('msg')}")
    except Exception as e:
        print(f"  飞书token错误: {e}")
    return None


def md_to_feishu_post(md_text):
    """将Markdown内容转换为飞书post富文本格式"""
    lines = md_text.split('\n')
    content_blocks = []  # 飞书post的content是二维数组，每个元素是一行

    for line in lines:
        stripped = line.strip()
        if not stripped:
            content_blocks.append([{"tag": "text", "text": ""}])
            continue

        # 标题行
        if stripped.startswith('# '):
            content_blocks.append([{"tag": "text", "text": stripped[2:], "style": ["bold"]}])
            continue
        if stripped.startswith('## '):
            content_blocks.append([{"tag": "text", "text": stripped[3:], "style": ["bold"]}])
            continue

        # 分隔线
        if stripped == '---':
            content_blocks.append([{"tag": "text", "text": "━━━━━━━━━━━━━━━━━━━━"}])
            continue

        # 引用行（>开头）
        if stripped.startswith('> '):
            text = stripped[2:]
            # 处理加粗
            text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
            content_blocks.append([{"tag": "text", "text": f"│ {text}"}])
            continue

        # 列表
        if stripped.startswith('- '):
            text = stripped[2:]
            text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
            content_blocks.append([{"tag": "text", "text": f"  • {text}"}])
            continue

        # 处理含链接的行：[text](url)
        link_pattern = r'\[([^\]]+)\]\(([^)]+)\)'
        parts = []
        last_end = 0
        text = stripped
        # 先去掉 🔗 符号
        text = text.replace('🔗 ', '')
        # 去掉markdown加粗标记用于显示
        bold_ranges = []
        clean_text = text

        for m in re.finditer(link_pattern, text):
            # 链接前的文本
            before = text[last_end:m.start()]
            before = re.sub(r'\*\*(.+?)\*\*', r'\1', before)
            if before:
                parts.append({"tag": "text", "text": before})
            # 链接本身
            parts.append({"tag": "a", "text": m.group(1), "href": m.group(2)})
            last_end = m.end()

        if parts:
            # 链接后的剩余文本
            after = text[last_end:]
            after = re.sub(r'\*\*(.+?)\*\*', r'\1', after)
            if after:
                parts.append({"tag": "text", "text": after})
            content_blocks.append(parts)
        else:
            # 普通文本行，处理加粗
            # 把**text**转为bold样式
            bold_parts = re.split(r'(\*\*.+?\*\*)', text)
            line_parts = []
            for part in bold_parts:
                if part.startswith('**') and part.endswith('**'):
                    line_parts.append({"tag": "text", "text": part[2:-2], "style": ["bold"]})
                elif part:
                    line_parts.append({"tag": "text", "text": part})
            if line_parts:
                content_blocks.append(line_parts)
            else:
                content_blocks.append([{"tag": "text", "text": text}])

    return content_blocks


def push_feishu(title, content):
    """推送到飞书群（post富文本格式，支持长内容，无IP限制）"""
    token = get_feishu_token()
    if not token:
        return False
    try:
        post_content = md_to_feishu_post(content)
        msg_body = {
            "receive_id": FEISHU_CHAT_ID,
            "msg_type": "post",
            "content": json.dumps({
                "zh_cn": {
                    "title": title,
                    "content": post_content
                }
            })
        }
        r = requests.post(
            f"{FEISHU_API}/open-apis/im/v1/messages?receive_id_type=chat_id",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            },
            json=msg_body,
            timeout=30
        )
        d = r.json()
        ok = d.get("code") == 0
        if not ok:
            print(f"  飞书推送失败: code={d.get('code')} msg={d.get('msg')}")
        return ok
    except Exception as e:
        print(f"  飞书推送错误: {e}")
        return False


# ========== Supabase存储 ==========
def sb_headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates"
    }

def save_to_supabase(ds_result, news_by_cat, now):
    """存档到Supabase"""
    date_str = now.strftime("%Y-%m-%d")
    time_slot = "morning" if now.hour < 14 else "evening"

    if ds_result:
        sc = ds_result.get("supply_chain", {})
        brief = {
            "date": date_str,
            "time_slot": time_slot,
            "ai_summary": ds_result.get("ai_robot", {}).get("summary", ""),
            "crypto_summary": ds_result.get("crypto", {}).get("summary", ""),
            "macro_summary": ds_result.get("macro", {}).get("summary", ""),
            "insight": ds_result.get("insight", ""),
            "supply_chain_signal": sc.get("has_signal", False),
            "supply_chain_detail": json.dumps(sc, ensure_ascii=False) if sc.get("has_signal") else None,
            "raw_count": sum(len(v) for v in news_by_cat.values()),
        }
        try:
            r = requests.post(f"{SUPABASE_URL}/rest/v1/news_briefs",
                              headers=sb_headers(), json=brief, timeout=10)
            print(f"  news_briefs: {r.status_code}")
        except Exception as e:
            print(f"  news_briefs错误: {e}")

    articles = []
    for cat_key, items in news_by_cat.items():
        for n in items:
            articles.append({
                "date": date_str,
                "time_slot": time_slot,
                "title": n["title"][:300],
                "url": n.get("link", "")[:500],
                "source": n.get("source", "")[:50],
                "category": cat_key,
            })
    if articles:
        for i in range(0, len(articles), 50):
            batch = articles[i:i+50]
            try:
                r = requests.post(f"{SUPABASE_URL}/rest/v1/news_articles",
                                  headers=sb_headers(), json=batch, timeout=15)
                print(f"  news_articles batch: {r.status_code} ({len(batch)}条)")
            except Exception as e:
                print(f"  news_articles错误: {e}")


# ========== 主流程 ==========
def main():
    now = datetime.now(BJT)
    slot = "晨报" if now.hour < 14 else "晚报"
    print(f"\n{'='*50}")
    print(f"[{now.strftime('%Y-%m-%d %H:%M')}] 新闻大秘 v3.0 {slot}")
    print(f"{'='*50}")

    # [1] 市场数据
    print("\n[1/6] 采集市场数据...")
    market_data = get_market_data()

    # [2] 采集新闻
    print("\n[2/6] 采集新闻源...")
    all_news = collect_all_news()
    print(f"\n  合计采集 {len(all_news)} 条原始新闻")

    if not all_news:
        print("  所有新闻源均无法访问")
        push_feishu("新闻大秘 | 采集失败", "> ⚠️ 所有新闻源均无法访问，请检查网络连接。")
        return

    # [3] 去重
    print("\n[3/6] 去重...")
    unique = fuzzy_dedup(all_news)
    print(f"  去重后 {len(unique)} 条")

    # [4] 按类别分组
    news_by_cat = {"ai_robot": [], "crypto": [], "macro": []}
    for n in unique:
        cat = n.get("category", "macro")
        if cat in news_by_cat:
            news_by_cat[cat].append(n)

    for cat_key, cat_info in CATEGORIES.items():
        print(f"  {cat_info['emoji']} {cat_info['name']}: {len(news_by_cat[cat_key])}条")

    # [5] DeepSeek摘要
    print("\n[4/6] DeepSeek生成深度分析...")
    ds_result = deepseek_summarize(news_by_cat, market_data)
    if ds_result:
        print("  ✓ 分析生成成功")
        sc = ds_result.get("supply_chain", {})
        if sc.get("has_signal"):
            print(f"  ⚡ 供应链信号: {sc.get('trigger', '未知')}")
    else:
        print("  ✗ 分析失败，使用降级格式")

    # [6] 排版+推送（飞书群消息）
    print("\n[5/6] 排版推送...")
    msg_title, msg_content = build_message(ds_result, news_by_cat, market_data)
    ok = push_feishu(msg_title, msg_content)
    print(f"  飞书群: {'✓ OK' if ok else '✗ FAIL'}")

    # [7] 存储
    print("\n[6/6] 存储到Supabase...")
    save_to_supabase(ds_result, news_by_cat, now)

    print(f"\n{'='*50}")
    print("完成")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    main()
