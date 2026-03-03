# 工单 WO-001 交付报告

## 执行摘要

工单001三项优先级全部完成：安全审计、推送双通道正规化、晨间快照模块。

## Priority 1: 安全审计 — 清除硬编码密钥

### 扫描结果

| 文件 | 发现的硬编码密钥 | 处理方式 |
|------|-----------------|---------|
| crypto_daily_intelligence.py | ANTHROPIC_API_KEY, SERVERCHAN_KEY, SUPABASE_URL, SUPABASE_KEY (4个) | 全部改为 os.environ.get() |
| daily_intelligence.py | ANTHROPIC_API_KEY, SERVERCHAN_KEY, SUPABASE_URL, SUPABASE_KEY (4个) | 全部改为 os.environ.get() |
| auditor.py | ANTHROPIC_API_KEY, SERVERCHAN_KEY, SUPABASE_URL, SUPABASE_KEY, GH_TOKEN (5个) | 全部改为 os.environ.get() |
| market_snapshot.py | 无（新建文件，从一开始就用env） | N/A |
| notify.py | 无（新建文件，从一开始就用env） | N/A |

### 新增安全文件

- `.env.example` — 环境变量模板（只有占位符，无真实值）
- `.gitignore` — 排除 .env、__pycache__、IDE文件
- `SECRETS_ROTATION_CHECKLIST.md` — 5种密钥的轮换流程文档

### GitHub Actions 状态

GitHub Actions的workflow yml文件已经在用 `${{ secrets.XXX }}`，无需修改。密钥仅在Python源码中硬编码，现已全部清除。

## Priority 2: 推送双通道正规化 — notify.py

### 新建文件: notify.py

统一推送层，所有脚本不再直接调用推送API，统一通过notify.py。

**3个公开函数：**

| 函数 | 用途 | 通道 |
|------|------|------|
| `push_serverchan_status(task_name, status, summary)` | 短状态通知（开始/成功/失败/告警） | Server酱 |
| `push_feishu_report(title, content, chat_id)` | 正文主通道（投研报告全文） | 飞书消息卡片 |
| `push_serverchan_report(title, content)` | 长正文fallback（飞书不可用时） | Server酱（自动按##拆分） |

**调用示例：**

```python
from notify import push_feishu_report, push_serverchan_status, push_serverchan_report

# 状态通知
push_serverchan_status('加密投研日报', '开始', '数据采集中')

# 正文推送（优先飞书，失败走Server酱）
ok = push_feishu_report('【情报】加密投研日报', report_text)
if not ok:
    push_serverchan_report('【情报】加密投研日报', report_text)

push_serverchan_status('加密投研日报', '成功', '已推送')
```

### 已改造的脚本

| 脚本 | 改动 |
|------|------|
| crypto_daily_intelligence.py | 删除内联push_serverchan()和split_and_push()，改用notify.py |
| daily_intelligence.py | 删除内联push_serverchan()，改用notify.py |
| auditor.py | 删除内联push_serverchan()，改用notify.py |

## Priority 3: 晨间快照 — market_snapshot.py

### 新建文件: market_snapshot.py (456行)

**4个板块（顺序固定）：**

1. 虚拟资产 — CoinGecko BTC/ETH/SOL价格 + 市值 + BTC市占 + 恐贪指数
2. A股 — 东方财富 上证/深证指数
3. AI/具身机器人 — Yahoo Finance NVDA + BOTZ ETF
4. 今日机会与风险 — Claude Sonnet生成（含操作提示）

**数据流：**
collect_crypto() + collect_ashare() + collect_ai_robotics() + collect_macro()
-> build_structured_data() -> call_claude() -> render_snapshot() -> push

**推送路径：** 飞书正文（优先） -> Server酱fallback -> 状态通知

**存档：** Supabase daily_intelligence表，title前缀 `[Snapshot]`

**fallback：** Claude分析失败时直接展示原始数据

### 尚未创建的配套文件

- GitHub Actions workflow（如 market_snapshot.yml）尚未创建，等Codex审核通过后再建

## 文件清单

| 文件 | 状态 | 行数 |
|------|------|------|
| notify.py | 新建 | 222行 |
| market_snapshot.py | 新建 | 456行 |
| .env.example | 新建 | 19行 |
| .gitignore | 新建 | 17行 |
| SECRETS_ROTATION_CHECKLIST.md | 新建 | 30行 |
| crypto_daily_intelligence.py | 改动 | 密钥+推送重构 |
| daily_intelligence.py | 改动 | 密钥+推送重构 |
| auditor.py | 改动 | 密钥+推送重构 |

## 待Codex审核确认的问题

1. notify.py的飞书消息卡片格式是否满足需求？当前用interactive card + lark_md
2. market_snapshot.py的板块顺序和数据源是否需要调整？
3. 是否需要创建 market_snapshot.yml workflow？建议cron: 07:50 BJT（早于加密投研日报08:00）
4. 密钥轮换checklist是否需要补充飞书相关密钥？

## 未提交Git

所有改动仅在本地，尚未commit/push到GitHub。等Codex审核通过后统一提交。
