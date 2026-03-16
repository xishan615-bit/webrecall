"""
agents/external_search_tools.py — 零配置外部搜索工具集

覆盖：
  🟢 Jina Reader  — 读任意网页 / 搜索全网（无需账号）
  🟢 GitHub       — 搜仓库 / 读 README（需要 gh CLI，gh auth login 扫码1分钟）
  🟢 Reddit       — 搜帖子 / 读帖子（无需账号，直接 JSON API）
"""
import json
import subprocess
from typing import Optional
import httpx
from langchain_core.tools import tool

_http = httpx.Client(timeout=20.0, follow_redirects=True)
_JINA_HEADERS = {"Accept": "text/markdown", "X-Return-Format": "markdown"}


# ─────────────────────────────────────────────────────────
# 1. DuckDuckGo（零配置全网搜索，完全免费）
# ─────────────────────────────────────────────────────────

@tool
def search_web(query: str, max_results: int = 8) -> str:
    """用 DuckDuckGo 搜索全网，返回最相关的结果摘要。零配置，无需任何 API Key。
    Args:
        query: 搜索关键词（中英文均可）
        max_results: 返回数量（默认8）
    """
    try:
        from ddgs import DDGS
        results = list(DDGS().text(query, max_results=max_results))
        if not results:
            return f"未找到「{query}」的搜索结果。"
        lines = [f"🔍 DuckDuckGo 搜索「{query}」（{len(results)} 条）：\n"]
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. **{r['title']}**")
            if r.get('body'):
                lines.append(f"   {r['body'][:150]}")
            lines.append(f"   🔗 {r['href']}")
            lines.append("")
        return "\n".join(lines)
    except Exception as e:
        return f"❌ 搜索失败：{e}"


# ─────────────────────────────────────────────────────────
# 2. Jina Reader（读任意单页，免费）
# ─────────────────────────────────────────────────────────

@tool
def read_web_page(url: str) -> str:
    """读取任意网页正文，转为 Markdown（免费，无需配置）。
    适合在搜索到目标 URL 后，深入阅读具体内容。
    Args:
        url: 要读取的网页完整 URL
    """
    try:
        jina_url = f"https://r.jina.ai/{url}"
        r = _http.get(jina_url, headers=_JINA_HEADERS, timeout=20)
        r.raise_for_status()
        return f"📄 页面内容（{url}）：\n\n{r.text[:5000]}"
    except Exception as e:
        return f"❌ 读取失败：{e}"


# ─────────────────────────────────────────────────────────
# 2. GitHub（需要 gh CLI，gh auth login 扫码即可）
# ─────────────────────────────────────────────────────────

def _gh(args: list[str]) -> tuple[bool, str]:
    """运行 gh CLI 命令，返回 (success, output)。"""
    try:
        r = subprocess.run(
            ["gh"] + args,
            capture_output=True, text=True, timeout=15
        )
        if r.returncode != 0:
            return False, r.stderr or "gh 命令失败"
        return True, r.stdout
    except FileNotFoundError:
        return False, "gh CLI 未安装。请运行：brew install gh && gh auth login"
    except subprocess.TimeoutExpired:
        return False, "GitHub 请求超时（15s）"


@tool
def github_search_repos(query: str, limit: int = 8) -> str:
    """在 GitHub 上搜索开源仓库，返回仓库名、描述、Stars 和链接。
    需要：brew install gh && gh auth login（扫码，1分钟）
    Args:
        query: 搜索词（如 LangGraph tutorial）
        limit: 返回数量（默认8）
    """
    ok, out = _gh([
        "search", "repos", query,
        "--sort", "stars",
        "--limit", str(limit),
        "--json", "name,fullName,description,stargazerCount,url"
    ])
    if not ok:
        return f"❌ GitHub 搜索失败：{out}"
    try:
        repos = json.loads(out)
        if not repos:
            return f"未找到与「{query}」相关的 GitHub 仓库。"
        lines = [f"🐙 GitHub 搜索「{query}」（{len(repos)} 个仓库）：\n"]
        for r in repos:
            stars = r.get("stargazerCount", 0)
            desc = (r.get("description") or "无描述")[:80]
            lines.append(f"⭐ {stars:,}  **{r['fullName']}**")
            lines.append(f"   {desc}")
            lines.append(f"   🔗 {r['url']}\n")
        return "\n".join(lines)
    except Exception:
        return out[:2000]


@tool
def github_read_repo(repo: str) -> str:
    """读取指定 GitHub 仓库的 README 和基本信息。
    需要：gh CLI 已登录
    Args:
        repo: 仓库名（如 langchain-ai/langgraph）
    """
    ok, out = _gh(["repo", "view", repo])
    if not ok:
        return f"❌ 读取失败：{out}"
    return f"📦 {repo} 仓库信息：\n\n{out[:4000]}"


# ─────────────────────────────────────────────────────────
# 3. Reddit（零配置，直接 JSON API）
# ─────────────────────────────────────────────────────────

_REDDIT_HEADERS = {"User-Agent": "WebRecall-Agent/1.0"}


@tool
def reddit_search(query: str, limit: int = 10, sort: str = "relevance") -> str:
    """在 Reddit 上搜索帖子，无需账号。
    Args:
        query: 搜索关键词
        limit: 返回数量（默认10）
        sort: 排序方式（relevance/new/top/hot）
    """
    try:
        url = f"https://www.reddit.com/search.json"
        r = _http.get(url, params={"q": query, "limit": limit, "sort": sort},
                      headers=_REDDIT_HEADERS)
        r.raise_for_status()
        data = r.json()
        posts = data.get("data", {}).get("children", [])
        if not posts:
            return f"Reddit 上未找到「{query}」相关帖子。"
        lines = [f"👾 Reddit 搜索「{query}」（{len(posts)} 条）：\n"]
        for post in posts:
            p = post["data"]
            score = p.get("score", 0)
            comments = p.get("num_comments", 0)
            title = p.get("title", "")[:100]
            sub = p.get("subreddit_name_prefixed", "")
            url_post = f"https://reddit.com{p.get('permalink','')}"
            lines.append(f"↑{score} 💬{comments}  **{title}**")
            lines.append(f"   {sub} · {url_post}\n")
        return "\n".join(lines)
    except Exception as e:
        return f"❌ Reddit 搜索失败（可能需要代理）：{e}"


@tool
def reddit_read_post(url: str) -> str:
    """读取 Reddit 帖子的内容和热门评论（无需账号）。
    Args:
        url: Reddit 帖子完整 URL（如 https://reddit.com/r/python/comments/xxx）
    """
    try:
        json_url = url.rstrip("/") + ".json?limit=10"
        r = _http.get(json_url, headers=_REDDIT_HEADERS)
        r.raise_for_status()
        data = r.json()
        # 帖子正文
        post_data = data[0]["data"]["children"][0]["data"]
        title = post_data.get("title", "")
        text = post_data.get("selftext", "")[:1000]
        sub = post_data.get("subreddit_name_prefixed", "")
        score = post_data.get("score", 0)
        # 热门评论
        comments = data[1]["data"]["children"][:5]
        comment_lines = []
        for c in comments:
            body = c["data"].get("body", "")[:200]
            cscore = c["data"].get("score", 0)
            if body:
                comment_lines.append(f"  ↑{cscore} {body}")

        lines = [
            f"📌 **{title}** ({sub}, ↑{score})",
            "",
            text or "(无正文，仅链接帖)",
            "",
            "**热门评论**：",
        ] + comment_lines
        return "\n".join(lines)
    except Exception as e:
        # 降级用 Jina Reader 读
        return read_web_page.invoke({"url": url})


# ─────────────────────────────────────────────────────────
# 对外导出：按用途分组
# ─────────────────────────────────────────────────────────

# Deep Researcher 默认工具集（优先级顺序）
EXTERNAL_SEARCH_TOOLS = [
    search_web,          # DuckDuckGo 全网搜索，首选
    read_web_page,       # Jina Reader 读具体页面
    github_search_repos, # GitHub 仓库搜索（需要 gh auth login）
    github_read_repo,    # GitHub 仓库详情
    reddit_search,       # Reddit 社区搜索
    reddit_read_post,    # Reddit 帖子阅读
]
