# Codex Review Guidelines for news-secretary

## Project Context
This is the intelligence department of a conglomerate. It contains 3 intelligence lines:
- `crypto_daily_intelligence.py` — **Line 1**: Daily crypto intelligence (mining-focused, BTC/ETH only, 20+ API data sources, two-batch Claude Sonnet analysis with quality gates)
- `a_stock_intelligence.py` — **Line 2**: A-share + commodities + China macro morning briefing (10-step data pipeline, Eastmoney + Yahoo Finance APIs)
- `ai_industry_intelligence.py` — **Line 4**: AI industry weekly report (disabled, pending approval)
- `llm_engine.py` — Unified LLM layer (Claude Sonnet primary via Anthropic API, DeepSeek/GLM-5 fallback via OpenRouter)
- `notify.py` — Server酱 push notification module (single channel, auto-splits long content)
- `generate_preview.py` — ECharts interactive chart generation for HTML preview

## Deprecated Files (kept for reference, not actively used)
- `daily_intelligence.py` — Old comprehensive intelligence (disabled, replaced by Line 1 + Line 2)
- `market_snapshot.py` — Old morning snapshot (deprecated, replaced by Line 2)

## Review Focus Areas (P0/P1)
1. **Security**: No hardcoded API keys, tokens, or secrets. All credentials must come from environment variables
2. **Push reliability**: Server酱 messages must not exceed 25000 chars per call. Long content must be split
3. **Status accuracy**: Status reporting must reflect actual results (success/partial/failure), never hardcode "success"
4. **Data freshness**: All timestamps must use Beijing Time (BJT/UTC+8) context
5. **Graceful degradation**: Any data source failure must not crash the entire report. Mark offline sources at report footer
6. **LLM calls**: Must use `llm_engine.call_llm()` with `model='sonnet'`. Direct API calls prohibited

## Review Non-Goals
- Style/formatting nitpicks (low priority)
- Performance optimization (unless causing timeouts)
- Test coverage (no test framework in this project)

## Coding Standards
- Python 3.10+, minimal dependencies. Core modules use only stdlib (`urllib`, `json`, `re`, `os`)
- LLM calls go through `llm_engine.py` which handles Anthropic API directly (not via SDK)
- All print statements use Chinese for operational logs
- All API calls wrapped in `safe_get()` with retry and timeout
