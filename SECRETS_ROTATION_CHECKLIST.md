# Secrets Rotation Checklist

## 密钥清单

| 密钥类别 | 环境变量名 | 用途 | 存储位置 | 轮换方式 |
|---------|-----------|------|---------|---------|
| Anthropic API Key | `ANTHROPIC_API_KEY` | Claude Sonnet LLM 调用 | GitHub Secrets | console.anthropic.com > API Keys > 创建新 Key > 删除旧 Key |
| Server酱 SendKey | `SERVERCHAN_KEY` | 微信推送通知 | GitHub Secrets | sct.ftqq.com > 设置 > 重置 SendKey |
| Supabase URL | `SUPABASE_URL` | 数据库连接 | GitHub Secrets | 不需要轮换（项目标识符，非密钥） |
| Supabase JWT | `SUPABASE_KEY` | 数据库 service_role 认证 | GitHub Secrets | Supabase Dashboard > Settings > API > Regenerate |
| GitHub Token | `GH_TOKEN` | 审核员查询 Actions 状态 | GitHub Secrets | GitHub Settings > Developer Settings > Tokens > Regenerate |

## 轮换建议

- **立即轮换**: 如果密钥曾被提交到 git 历史（即使已删除，历史中仍可见）
- **定期轮换**: 每 90 天轮换一次 Anthropic API Key 和 Supabase JWT
- **事件驱动**: 团队成员变动时轮换所有密钥

## 轮换后需同步更新的位置

1. GitHub Secrets（helloworldoccupied/news-secretary 仓库）
2. 本地 `.env` 文件（如果有）
3. 其他引用同一密钥的系统（如交易Bot引用了同一个 Supabase Key）

## 注意事项

- 不要在 commit message 中包含密钥
- 不要在日志输出中打印完整密钥
- 不要在 `.env.example` 中放入真实值
