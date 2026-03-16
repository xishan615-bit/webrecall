---
name: webrecall-retrieval
description: >
  在用户的 WebRecall 私人收藏库中高效检索信息。支持漏斗式检索
  （标签→筛选→确认→阅读）和平台感知深度读取（视频字幕提取、推文
  线程展开等）。当用户提到"我之前看过/收藏过/保存过"或需要调用
  个人知识库时使用此 Skill。
  Triggers: "我之前看过", "我收藏过", "帮我找之前", "我保存过",
  "我记得有篇", "我的收藏"
---

# WebRecall 收藏检索 Skill

## 何时使用

用户请求涉及以下场景时使用 WebRecall 工具：
- "我之前看过一篇…" / "我收藏过…" / "我保存过…"
- "帮我找之前那个…" / "我记得有篇文章讲…"
- "根据我收藏的内容，帮我总结/分析…"

**不使用**：搜全网新信息（用 web search）、与已保存内容无关的问题。

---

## 可用工具

| 工具 | 参数 | token 成本 | 用途 |
|------|------|-----------|------|
| `webrecall_get_tags()` | 无 | ~50 | 第1层：看知识库分类分布 |
| `webrecall_search(query, platform, days, limit)` | 全可选 | ~200 | 第2层：三维筛选 |
| `webrecall_get_content(url)` | url | ~1000-5000 | 第3层：读某篇完整原文 |
| `webrecall_list_pages(platform, days, page, page_size)` | 全可选 | ~300 | 浏览列表 |
| `webrecall_save_page(url, title, content)` | 全必填 | ~10 | 保存新页面 |
| `webrecall_delete_page(url)` | url | ~10 | 删除页面 |
| `webrecall_get_stats()` | 无 | ~30 | 统计概览 |

### search 参数详解

- `query`：关键词，匹配标题和摘要。不填则不限
- `platform`：精确匹配平台名。可选值：**X, 知乎, GitHub, Reddit, B站, 微博, 微信公众号, YouTube, Medium, 掘金, 少数派, 36氪, V2EX**
- `days`：最近 N 天。7=近一周，30=近一个月。不填则不限
- `limit`：返回数量上限（默认10）
- **参数可任意组合**，没传的维度不过滤

---

## 漏斗式检索策略

### 强制规则

1. **禁止一次性获取所有页面原文** — token 浪费
2. **禁止跳过筛选直接读原文** — 必须先 search
3. **结果超过 5 条时必须追问用户** — 让用户确认
4. **每次对话最多读取 3 篇原文** — 超过则分批

### 标准流程

```
第 1 步：理解用户意图
  ├─ 识别关键词（如 "RAG", "OpenClaw"）
  ├─ 识别平台暗示（"推特上" → platform="X"）
  ├─ 识别时间暗示（"上周" → days=7, "最近" → days=14）
  └─ 判断是"找一篇"还是"总结多篇"

第 2 步：调用 search，参数尽可能完整

第 3 步：根据结果数量决策
  ├─ 0 条 → 放宽条件重试
  ├─ 1-3 条 → 直接呈现，问要不要读详情
  ├─ 4-10 条 → 列标题分组，让用户选
  └─ 10+ 条 → 追问用户补充条件

第 4 步：确认后根据平台类型选择读取方式（见下文）
```

### 搜索为空时降级策略

1. 去掉 `platform`（也许用户记错来源）
2. 扩大 `days`（也许不是上周而是上个月）
3. 简化 `query`（也许关键词不精确）
4. 都找不到 → "收藏中没找到，要搜全网吗？"

---

## 平台感知深度读取

确认要读某篇收藏后，**根据 URL 域名判断使用哪种读取方式**：

### 决策树

```
域名是 bilibili.com / b23.tv       → B站视频深度读取
域名是 youtube.com / youtu.be       → YouTube 视频深度读取
域名是 x.com / twitter.com          → X/Twitter 深度读取
域名是 github.com                   → GitHub 深度读取
域名是 xiaohongshu.com / xhslink    → 小红书深度读取
域名是 douyin.com / v.douyin.com    → 抖音深度读取
其他（知乎、微信、Medium 等）        → webrecall_get_content(url) 即可
```

### B站视频

webrecall_get_content 只有标题和简介，**实际内容在字幕里**：

```bash
# 获取元数据
yt-dlp --dump-json "https://www.bilibili.com/video/BVxxx"

# 下载字幕
yt-dlp --write-sub --write-auto-sub --sub-lang "zh-Hans,zh,en" \
  --convert-subs vtt --skip-download -o "/tmp/%(id)s" "URL"

# 如果被拦截：
yt-dlp --cookies-from-browser chrome --dump-json "URL"
```

### YouTube 视频

```bash
# 推荐：使用 auto_download.sh
# 如果安装了 google-video-subtitle-recognition skill：
# bash /path/to/skills/google-video-subtitle-recognition/scripts/auto_download.sh \
#   "URL" --lang zh-Hans --format txt --output /tmp

# 通用方式：
yt-dlp --write-sub --write-auto-sub --sub-lang "zh-Hans,zh,en" \
  --skip-download -o "/tmp/%(id)s" "URL"

# 或直接 yt-dlp
yt-dlp --write-sub --write-auto-sub --sub-lang "zh-Hans,zh,en" \
  --skip-download -o "/tmp/%(id)s" "URL"
```

### X / Twitter

```bash
# 完整推文含回复数、转发数
xreach tweet https://x.com/user/status/123456 --json

# 某用户最近推文（看上下文）
xreach tweets @username --json -n 10
```

### GitHub

```bash
# 仓库概览
gh repo view owner/repo

# 最新 Issues
gh issue list -R owner/repo --state open --limit 5

# 搜索仓库内代码
gh search code "关键词" -R owner/repo
```

### 小红书

```bash
mcporter call 'xiaohongshu.get_feed_detail(feed_id: "xxx", xsec_token: "yyy")'
mcporter call 'xiaohongshu.get_feed_comments(feed_id: "xxx", xsec_token: "yyy")'
```

### 抖音

```bash
mcporter call 'douyin.parse_douyin_video_info(share_link: "https://v.douyin.com/xxx/")'
mcporter call 'douyin.extract_douyin_text(share_link: "https://v.douyin.com/xxx/")'
```

### 通用兜底（Jina Reader）

如果 webrecall_get_content 原文不完整：

```bash
curl -s "https://r.jina.ai/URL" -H "Accept: text/markdown"
```

---

## 场景模板

### A：找某一篇文章
```
用户："上周 X 上那篇讲 OpenClaw 理财的帖子"
→ search(query="OpenClaw 理财", platform="X", days=7)
→ 找到 → 确认 → get_content / xreach 读取
```

### B：B站视频回顾
```
用户："之前收藏了个B站视频讲 Agent 的"
→ search(query="Agent", platform="B站")
→ 选定 → yt-dlp 下载字幕 → 整理文字稿
```

### C：总结多篇
```
用户："总结收藏的 MCP 协议文章"
→ search(query="MCP 协议", limit=20)
→ 逐篇读取（文章用 get_content，视频用 yt-dlp）
→ 交叉对比 → 结构化总结
```

### D：浏览最新
```
用户："最近收藏了什么？"
→ get_tags() 看分布
→ list_pages(days=7) 列最近一周
```

### E：搜索为空
```
→ 放宽条件重试 → 还是空
→ "收藏中没找到，要我搜全网吗？"
→ 转 agent-reach 平台工具
```

---

## 输出格式

### 搜索结果（紧凑）
```
找到 5 篇相关收藏：

1. 📄 用 OpenClaw 自动监控美股组合
   🔗 x.com · 📅 3月12日
2. 🎬 Agent 开发入门（视频）
   🔗 bilibili.com · 📅 3月11日
```

> 视频标注 🎬，提醒需字幕提取

### 原文总结（要点式）
```
📄《标题》

核心内容：
- 要点 1
- 要点 2

关键数据：
- 数据 1
```
