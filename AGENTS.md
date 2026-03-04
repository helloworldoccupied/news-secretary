# Codex Review Guidelines for news-secretary

## Project Context
This is the intelligence/news department of a conglomerate. It contains:
- `crypto_daily_intelligence.py` — Daily crypto intelligence report (20+ API data sources, Claude Sonnet analysis)
- `daily_intelligence.py` — Comprehensive market intelligence (crypto + A-stock + macro)
- `market_snapshot.py` — Morning market snapshot
- `notify.py` — Server酱 push notification module
- `auditor.py` — QA auditor agent (GitHub Actions + Supabase + Claude Sonnet quality scoring)

## Review Focus Areas (P0/P1)
1. **Security**: No hardcoded API keys, tokens, or secrets. All credentials must come from environment variables
2. **Push reliability**: Server酱 messages must not exceed 25000 chars per call. Long content must be split
3. **Status accuracy**: Status reporting must reflect actual results (success/partial/failure), never hardcode "success"
4. **Data freshness**: All timestamps must use Beijing Time (BJT/UTC+8) context
5. **Graceful degradation**: Any data source failure must not crash the entire report. Mark offline sources at report footer

## Review Non-Goals
- Style/formatting nitpicks (low priority)
- Performance optimization (unless causing timeouts)
- Test coverage (no test framework in this project)

## Coding Standards
- Python 3.10+, minimal dependencies. Core modules use only stdlib (`urllib`, `json`, `re`, `os`)
- Claude Sonnet API calls use Anthropic SDK (`anthropic` package) with model `claude-sonnet-4-20250514` — this is the only allowed external dependency
- All print statements use Chinese for operational logs
