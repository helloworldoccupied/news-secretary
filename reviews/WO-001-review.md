# WO-001 交付复核报告（Codex 质检复核）

## 复核结论
**有条件通过**。

本次交付在“统一推送层抽离、晨间快照模块落地、核心脚本改造”方面基本达成目标；但**仍存在1项高严重度安全问题（硬编码 GitHub Token fallback）**，与“硬编码密钥全部清除”的目标不一致，需修复后再视为完全通过。

---

## 问题清单（按严重程度排序）

## P0 / 严重

### 1) `auditor.py` 仍保留硬编码 GH Token fallback（安全漏洞）
- 位置：`check_github_actions()` 中 `gh_token = os.environ.get('GH_TOKEN') or 'gho_...'`
- 风险：
  - 源码泄漏后可直接导致 GitHub Token 暴露与被滥用。
  - 与交付报告“硬编码密钥全部清除”的声明冲突。
- 结论：**不符合安全整改验收标准**。

---

## P1 / 高

### 2) `notify.py` 的 Server酱长文拆分存在超长分片风险
- 当前逻辑按 `## ` 标题拆分并累积到 25000 字以内再发送。
- 但若某个单独 section 本身 > 25000 字，逻辑不会二次切片，仍可能发送超长 payload 导致推送失败。
- 影响：飞书失败后 fallback 到 Server酱时，长文在极端情况下可能“全部失败”，降低可靠性。

---

## P2 / 中

### 3) `market_snapshot.py` 数据采集 fallback 基本可用，但“成功状态”判定偏乐观
- 优点：
  - `_get_json()` 失败返回 `None`，各采集函数局部异常不致崩溃。
  - Claude 失败时可回退到结构化原始数据渲染并继续推送。
- 问题：
  - 即使关键数据源全失败、甚至飞书和 Server酱都失败，流程仍固定发送“成功”状态通知（`push_serverchan_status(..., '成功', ...)`），缺少基于实际推送结果与数据完整度的降级状态。
- 影响：监控可观测性不足，易出现“假成功”。

### 4) 数据源健壮性改进空间（`market_snapshot.py`）
- A股接口对字段空值直接 `/100`，依赖 `get(...,0)` 虽可避免崩溃，但会把异常数据吞成 `0.00`，容易与真实零值混淆。
- 多处 `except Exception: pass` 会抑制问题定位（尤其第三方 API 字段结构变更时）。

---

## 已复核通过项

1. **硬编码密钥整改（部分通过）**
   - `notify.py`、`market_snapshot.py`、`crypto_daily_intelligence.py`、`daily_intelligence.py` 的主要密钥均改为 `os.environ.get(...)`。
   - 但 `auditor.py` 的 GH Token fallback 仍是硬编码，故只能判定“部分通过”。

2. **`notify.py` 通道拆分方向正确**
   - 状态通知：`push_serverchan_status()`
   - 正文主通道：`push_feishu_report()`（interactive card + lark_md）
   - 正文 fallback：`push_serverchan_report()`（按 `##` 分段）
   - 设计思路符合“主通道 + 降级通道”目标。

3. **各脚本 `import notify` 路径检查通过**
   - `market_snapshot.py` / `crypto_daily_intelligence.py` / `daily_intelligence.py` / `auditor.py` 均使用 `from notify import ...`。
   - 这些脚本与 `notify.py` 位于同级目录时可正常解析，未发现明显路径错误。

---

## 建议修改点（可直接纳入 WO-001 收尾）

### 必改（上线前）
1. **移除 `auditor.py` 的硬编码 GH token**
   - 改为仅从环境变量读取：`gh_token = os.environ.get('GH_TOKEN', '')`
   - 若为空：
     - 记录 `YELLOW` 告警（配置缺失），并跳过 GitHub API 调用；
     - 不应使用任何源码内 fallback token。

### 强烈建议（稳定性）
2. **增强 `push_serverchan_report()` 超长保护**
   - 对“单 section 超过上限”增加二次切片（按字符硬切）逻辑。
   - 为每片追加 `[i/N]` 标记，确保任意长度文本都可送达。

3. **`market_snapshot.py` 成功状态改为结果驱动**
   - 以 `feishu_ok or serverchan_ok` 判定是否“推送成功”。
   - 若双通道都失败，发送“失败”状态（或至少打印 error 并返回非0退出码，便于 CI 监控）。

4. **完善数据源可观测性**
   - 将 `except Exception: pass` 改为最少限度日志（源名 + 异常摘要）。
   - 在快照正文中附“数据完整度”提示（例如：4个板块中X个为fallback）。

### 可选优化
5. **飞书消息长度策略**
   - 当前 `content[:30000]` 直接截断，建议在截断时补充“内容已截断，请查看存档”提示。
   - 或对飞书正文也做分片发送，避免信息丢失。

---

## 复核结语
本单整体设计已接近可用版本，尤其统一推送层与晨间快照的骨架合理；但鉴于 `auditor.py` 仍有硬编码密钥，建议先完成必改项后再将 WO-001 标记为“完全通过”。
