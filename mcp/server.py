#!/usr/bin/env python3
"""
WebRecall MCP Server — Agent 外挂知识脑

直接读写 ~/.webrecall/pages.db（SQLite），无需后端和 Ollama。
Agent 宿主（Cursor / Claude Desktop / OpenClaw）启动时自动拉起本进程。

工具列表（7 个）：
  webrecall_get_tags      — 知识库全景图（第 1 层漏斗）
  webrecall_search        — 三维筛选搜索（第 2 层漏斗）
  webrecall_get_content   — 读取单篇原文（第 3 层漏斗）
  webrecall_list_pages    — 带筛选的列表浏览
  webrecall_save_page     — 保存新页面
  webrecall_delete_page   — 删除页面
  webrecall_get_stats     — 统计概览
"""
import sys
import os

# 将 backend 目录加入 sys.path，复用 sqlite_store 模块
BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.insert(0, BACKEND_DIR)

from typing import Optional
from pydantic import BaseModel, Field, ConfigDict
from mcp.server.fastmcp import FastMCP
from db.sqlite_store import (
    init_sqlite, search_pages, list_pages, save_page,
    delete_page, get_page, get_stats, get_overview,
    get_unclassified_pages, batch_update_tags, get_taxonomy, update_taxonomy,
)
from utils.platform import extract_domain, domain_to_platform

# 确保 DB 已初始化
init_sqlite()

mcp = FastMCP("webrecall")


# ── 输入模型 ──────────────────────────────────────────────

class SearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: Optional[str] = Field(
        default=None,
        description="关键词，匹配标题和摘要。如 'OpenClaw', 'RAG'。不填则不做关键词过滤",
        max_length=500,
    )
    platform: Optional[str] = Field(
        default=None,
        description="平台名称，精确匹配。可选值：X, 知乎, GitHub, Reddit, B站, 微博, 微信公众号, YouTube, Medium, 掘金, 少数派, 36氪, V2EX",
    )
    days: Optional[int] = Field(
        default=None,
        description="时间范围：只搜最近 N 天内保存的页面。7=近一周, 30=近一个月。不填则不限时间",
        ge=1, le=365,
    )
    limit: Optional[int] = Field(
        default=10,
        description="返回数量上限",
        ge=1, le=50,
    )


class ListInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    platform: Optional[str] = Field(default=None, description="按平台筛选")
    days: Optional[int] = Field(default=None, description="最近 N 天内", ge=1, le=365)
    page: Optional[int] = Field(default=1, description="页码", ge=1)
    page_size: Optional[int] = Field(default=20, description="每页数量", ge=1, le=50)


class GetContentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(..., description="页面 URL，从 search 或 list_pages 结果中获取")


class SaveInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    url: str = Field(..., description="页面 URL", min_length=5)
    title: str = Field(..., description="页面标题")
    content: str = Field(..., description="页面正文内容（纯文本，非 HTML）", min_length=10, max_length=50000)


class DeleteInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    url: str = Field(..., description="要删除的页面 URL", min_length=5)


# ── 工具定义 ──────────────────────────────────────────────

@mcp.tool(
    name="webrecall_get_tags",
    annotations={
        "title": "知识库全景图",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
async def webrecall_get_tags() -> str:
    """获取知识库中所有平台标签及其文章数量，以及时间分布。

    Agent 应该在检索前**第一步**调用此工具，了解知识库结构后再定向搜索。

    Returns:
        str: 按平台和时间分布的知识库概览
    """
    overview = get_overview()
    total = overview["total_pages"]

    if total == 0:
        return "📚 知识库为空，还没有保存任何页面。"

    lines = [f"## 📂 知识库概览（共 {total} 篇）\n"]

    # 平台分布
    platforms = overview.get("platforms", {})
    if platforms:
        lines.append("**按平台：**")
        parts = [f"{name}: {count}篇" for name, count in platforms.items()]
        lines.append("  " + " | ".join(parts))
        lines.append("")

    # 时间分布
    time_dist = overview.get("time_distribution", {})
    if time_dist:
        lines.append("**按时间：**")
        parts = [f"{period}: {count}篇" for period, count in time_dist.items() if count > 0]
        lines.append("  " + " | ".join(parts))

    return "\n".join(lines)


@mcp.tool(
    name="webrecall_search",
    annotations={
        "title": "三维筛选搜索",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
async def webrecall_search(params: SearchInput) -> str:
    """在收藏库中搜索页面，支持关键词 × 平台 × 时间三维筛选，参数可任意组合。

    Args:
        params: query（关键词）、platform（平台名）、days（最近N天）、limit（数量）

    Returns:
        str: 匹配的页面列表，含标题、URL、平台、日期
    """
    results = search_pages(
        query=params.query,
        platform=params.platform,
        days=params.days,
        limit=params.limit or 10,
    )

    if not results:
        filters = []
        if params.query: filters.append(f"关键词「{params.query}」")
        if params.platform: filters.append(f"平台「{params.platform}」")
        if params.days: filters.append(f"近 {params.days} 天")
        hint = "、".join(filters) if filters else "所有条件"
        return f"没有找到匹配 {hint} 的收藏页面。试试放宽筛选条件？"

    # 构建筛选描述
    desc_parts = []
    if params.platform: desc_parts.append(params.platform)
    if params.days: desc_parts.append(f"近{params.days}天")
    if params.query: desc_parts.append(f"含「{params.query}」")
    desc = " · ".join(desc_parts) if desc_parts else "全部"

    lines = [f"🔍 找到 {len(results)} 条结果（{desc}）\n"]
    for i, r in enumerate(results, 1):
        title = r.get("title", "无标题")
        domain = r.get("domain", "")
        saved = r.get("saved_at", "")[:10]
        platform = r.get("platform", "")
        icon = "🎬" if platform in ("B站", "YouTube") else "📄"
        lines.append(f"{i}. {icon} {title}")
        lines.append(f"   🔗 {domain} · 📅 {saved}")
        if r.get("summary"):
            lines.append(f"   📝 {r['summary'][:80]}...")
        lines.append("")

    lines.append("需要我读取某篇的详细内容吗？告诉我序号或标题。")
    return "\n".join(lines)


@mcp.tool(
    name="webrecall_get_content",
    annotations={
        "title": "读取单篇原文",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
async def webrecall_get_content(params: GetContentInput) -> str:
    """获取某篇已保存页面的完整原文。这是 token 消耗最高的操作，应在确认目标后才调用。

    对于视频类页面（B站、YouTube），存储的内容可能只有标题和简介，
    需要配合 yt-dlp 等工具提取字幕获取完整内容。

    Args:
        params: url（页面 URL）

    Returns:
        str: 标题 + 完整正文
    """
    page = get_page(params.url)
    if not page:
        return f"未找到该页面: {params.url}"

    title = page.get("title", "无标题")
    content = page.get("content", "")
    platform = page.get("platform", "")
    domain = page.get("domain", "")
    saved_at = page.get("saved_at", "")[:10]

    lines = [
        f"# {title}",
        f"📅 保存于 {saved_at} · 🔗 {domain}",
        "",
    ]

    # 视频类提示
    if platform in ("B站", "YouTube"):
        lines.append("> ⚠️ 这是一个视频页面，以下内容可能只有标题和简介。")
        lines.append("> 如需完整内容，请使用 yt-dlp 提取字幕。")
        lines.append("")

    if page.get("summary"):
        lines.append(f"## 摘要\n{page['summary']}\n")

    lines.append(f"## 正文\n{content}")
    return "\n".join(lines)


@mcp.tool(
    name="webrecall_list_pages",
    annotations={
        "title": "浏览收藏列表",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
async def webrecall_list_pages(params: ListInput) -> str:
    """列出已保存的网页，支持按平台和时间筛选，按保存时间倒序，支持分页。

    与 search 的区别：list 不做关键词匹配，纯结构化浏览。

    Args:
        params: platform（平台）、days（天数）、page（页码）、page_size（每页数量）
    """
    # 计算分页
    page_num = params.page or 1
    page_size = params.page_size or 20
    offset = (page_num - 1) * page_size

    # 用 search_pages 的平台+时间筛选，但不传 query
    all_results = search_pages(
        platform=params.platform,
        days=params.days,
        limit=offset + page_size + 1,  # 多取一条判断是否有下一页
    )

    total_available = len(all_results)
    page_data = all_results[offset:offset + page_size]
    has_more = total_available > offset + page_size

    if not page_data:
        return "📚 没有找到匹配的页面。"

    desc_parts = []
    if params.platform: desc_parts.append(params.platform)
    if params.days: desc_parts.append(f"近{params.days}天")
    desc = " · ".join(desc_parts) if desc_parts else "全部"

    lines = [f"## 📚 已保存页面（{desc}，第 {page_num} 页）\n"]
    for p in page_data:
        title = p.get("title", "无标题")
        domain = p.get("domain", "")
        saved = p.get("saved_at", "")[:10]
        platform = p.get("platform", "")
        icon = "🎬" if platform in ("B站", "YouTube") else "📄"
        lines.append(f"- {icon} **{title}**")
        lines.append(f"  {domain} · {saved}")
        lines.append(f"  {p['url']}")
        lines.append("")

    if has_more:
        lines.append(f"> 还有更多页面，使用 page={page_num + 1} 查看下一页")

    return "\n".join(lines)


@mcp.tool(
    name="webrecall_save_page",
    annotations={
        "title": "保存网页到知识库",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
async def webrecall_save_page(params: SaveInput) -> str:
    """将一个网页保存到 WebRecall 知识库。自动根据域名打平台标签。

    Args:
        params: url、title、content（正文，非 HTML）
    """
    from datetime import datetime

    domain = extract_domain(params.url)
    platform = domain_to_platform(domain)
    now = datetime.now()

    save_page(
        url=params.url,
        title=params.title,
        domain=domain,
        platform=platform,
        content=params.content,
        saved_at=now.isoformat(),
        saved_at_ts=now.timestamp(),
    )

    return f"✅ 已保存「{params.title}」到知识库（{platform}）"


@mcp.tool(
    name="webrecall_delete_page",
    annotations={
        "title": "删除已保存页面",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
async def webrecall_delete_page(params: DeleteInput) -> str:
    """从知识库中删除指定 URL 的页面。此操作不可撤销。"""
    if delete_page(params.url):
        return f"✅ 已删除: {params.url}"
    return f"❌ 未找到该页面: {params.url}"


@mcp.tool(
    name="webrecall_get_stats",
    annotations={
        "title": "知识库统计",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
async def webrecall_get_stats() -> str:
    """获取知识库的基础统计信息。"""
    stats = get_stats()
    lines = [
        "## 📊 WebRecall 知识库统计",
        f"- **已保存页面**: {stats.get('total_pages', 0)} 个",
    ]
    domains = stats.get("top_domains", [])
    if domains:
        lines.append(f"- **Top 来源**: {', '.join(domains[:5])}")
    return "\n".join(lines)


# ── 分类专家工具 ──────────────────────────────────────────────

class ClassifyBatchItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(..., description="页面 URL")
    tags: list = Field(..., description="分类标签列表，如 ['科技', 'AI', 'Agent']")
    category: Optional[str] = Field(default=None, description="主分类名称")

class ClassifyBatchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    updates: list[ClassifyBatchItem] = Field(..., description="分类结果列表")

class TaxonomyUpdateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    upsert_categories: Optional[list] = Field(default=[], description="新增或更新的分类，每项含 name 和可选 parent")
    upsert_keywords:   Optional[list] = Field(default=[], description="新增或更新的关键词绑定，每项含 keyword/category/weight/source")
    delete_keywords:   Optional[list] = Field(default=[], description="要删除的关键词列表")


@mcp.tool(
    name="webrecall_get_unclassified",
    annotations={"title": "获取待分类页面", "readOnlyHint": True, "destructiveHint": False},
)
async def webrecall_get_unclassified(limit: Optional[int] = 50) -> str:
    """获取尚未被分类专家处理的页面列表（classified_at IS NULL）。

    分类专家工作流第一步：调用此工具获取待分类列表。
    每项只含 url/title/summary/platform/saved_at，不含全文（节省 token）。
    """
    pages = get_unclassified_pages(limit=limit or 50)
    if not pages:
        return "✅ 所有页面已完成分类，没有待整理的内容。"

    lines = [f"📋 共 {len(pages)} 篇待分类页面（按保存时间倒序）：\n"]
    for i, p in enumerate(pages, 1):
        title = p.get("title", "无标题")
        platform = p.get("platform", "")
        saved = p.get("saved_at", "")[:10]
        summary = (p.get("summary") or "")[:100]
        lines.append(f"{i}. {title}")
        lines.append(f"   🔗 {p['url']}")
        lines.append(f"   📅 {saved} · {platform}")
        if summary:
            lines.append(f"   📝 {summary}...")
        lines.append("")
    return "\n".join(lines)


@mcp.tool(
    name="webrecall_classify_batch",
    annotations={"title": "批量写入分类标签", "readOnlyHint": False, "destructiveHint": False},
)
async def webrecall_classify_batch(params: ClassifyBatchInput) -> str:
    """用户确认分类结果后，批量将 tags 写入 SQLite 并标记 classified_at。

    ⚠️ 必须在向用户展示分类预览并获得确认后才能调用此工具。

    Args:
        params.updates: 分类结果列表，每项含 url + tags + 可选 category
    """
    count = batch_update_tags([u.model_dump() for u in params.updates])
    return f"✅ 已完成 {count} 篇页面的分类标注。"


@mcp.tool(
    name="webrecall_get_taxonomy",
    annotations={"title": "读取分类记忆", "readOnlyHint": True, "destructiveHint": False},
)
async def webrecall_get_taxonomy() -> str:
    """读取分类专家的长期记忆：分类树结构和关键词→分类绑定。

    分类专家工作流第二步：了解已有分类体系，避免重复建立类目。
    若为空，说明是首次运行，需要从零建立分类树。
    """
    taxonomy = get_taxonomy()
    cats = taxonomy.get("categories", [])
    if not cats:
        return "📂 分类记忆为空，这是首次分类。你可以自由建立分类体系。"

    lines = ["## 📂 当前分类体系\n"]
    for cat in cats:
        parent = f"（属于 {cat['parent_id']}）" if cat["parent_id"] else "（顶级）"
        keywords = ", ".join(k["keyword"] for k in cat["keywords"][:10])
        lines.append(f"**{cat['name']}** {parent}")
        if keywords:
            lines.append(f"  关键词：{keywords}")
        lines.append("")
    return "\n".join(lines)


@mcp.tool(
    name="webrecall_update_taxonomy",
    annotations={"title": "更新分类记忆", "readOnlyHint": False, "destructiveHint": False},
)
async def webrecall_update_taxonomy(params: TaxonomyUpdateInput) -> str:
    """更新分类专家的长期记忆（分类树和关键词绑定）。

    在每次分类任务结束后调用，将新发现的类目和关键词写入记忆，
    供下次分类时参考，实现自我迭代。

    Args:
        params.upsert_categories: 新建或更新类目，如 [{"name": "AI", "parent": "科技"}]
        params.upsert_keywords:   关键词绑定，如 [{"keyword": "Agent", "category": "AI", "source": "user"}]
        params.delete_keywords:   要删除的关键词列表
    """
    stats = update_taxonomy(params.model_dump())
    parts = []
    if stats["categories_upserted"]: parts.append(f"类目 {stats['categories_upserted']} 个")
    if stats["keywords_upserted"]:   parts.append(f"关键词 {stats['keywords_upserted']} 个")
    if stats["keywords_deleted"]:    parts.append(f"删除旧词 {stats['keywords_deleted']} 个")
    summary = "、".join(parts) if parts else "无变更"
    return f"✅ 记忆已更新：{summary}"


if __name__ == "__main__":
    mcp.run()
