"""
agents/tools.py — LangChain 工具层
全部调用 lite_server REST API，保持与 MCP server 同等接口。
"""
import json
import httpx
from langchain_core.tools import tool

LITE_URL = "http://localhost:8001"
_client = httpx.Client(timeout=15.0)


def _get(path: str, **params) -> dict:
    r = _client.get(f"{LITE_URL}{path}", params={k: v for k, v in params.items() if v is not None})
    r.raise_for_status()
    return r.json()


def _post(path: str, body: dict) -> dict:
    r = _client.post(f"{LITE_URL}{path}", json=body)
    r.raise_for_status()
    return r.json()


def _put(path: str, body: dict) -> dict:
    r = _client.put(f"{LITE_URL}{path}", json=body)
    r.raise_for_status()
    return r.json()


# ── 检索工具 ──────────────────────────────────────────────

@tool
def search_knowledge_base(query: str, limit: int = 10, days: int = None) -> str:
    """在本地 SQLite 知识库中搜索页面。支持 + 做 AND 联合检索（如 AI+RAG）。
    Args:
        query: 搜索关键词，支持 + 联合检索
        limit: 返回数量上限（默认10）
        days: 只搜最近N天（可选）
    """
    data = _get("/api/search", q=query, limit=limit, days=days)
    results = data.get("results", [])
    if not results:
        return f"未找到匹配「{query}」的页面。"
    lines = [f"找到 {len(results)} 条结果（{query}）：\n"]
    for i, r in enumerate(results, 1):
        tags = r.get("tags", [])
        tag_str = f"  🏷 {', '.join(tags)}" if tags else ""
        lines.append(f"{i}. **{r['title']}**")
        lines.append(f"   🔗 {r['url']}")
        lines.append(f"   📅 {r.get('saved_at','')[:10]} · {r.get('platform','')}{tag_str}")
        if r.get("snippet"):
            lines.append(f"   📝 {r['snippet'][:120]}...")
        lines.append("")
    return "\n".join(lines)


@tool
def get_page_content(url: str) -> str:
    """获取指定页面的完整正文内容（token 消耗较高，精读前调用）。
    Args:
        url: 页面完整 URL（来自 search_knowledge_base 结果）
    """
    # 调用 lite_server 的 search 接口精确匹配或 MCP 路径
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
    from db.sqlite_store import get_page
    page = get_page(url)
    if not page:
        return f"未找到该页面: {url}"
    title = page.get("title", "无标题")
    content = page.get("content", "")
    summary = page.get("summary", "")
    saved_at = page.get("saved_at", "")[:10]
    result = [f"# {title}", f"📅 {saved_at} · {page.get('platform','')}", ""]
    if summary:
        result.append(f"## 摘要\n{summary}\n")
    result.append(f"## 正文\n{content[:3000]}")  # 限制 3000 字符避免过长
    return "\n".join(result)


@tool
def get_library_overview() -> str:
    """获取知识库全景：平台分布、收藏数量、时间分布。每次对话第一步调用。"""
    data = _get("/api/stats")
    overview_data = _get("/api/pages", **{})
    pages = overview_data.get("pages", [])
    platform_count: dict = {}
    for p in pages:
        plat = p.get("platform") or "其他"
        platform_count[plat] = platform_count.get(plat, 0) + 1

    total = data.get("total_pages", 0)
    classified = sum(1 for p in pages if p.get("classified_at"))
    unclassified = total - classified

    lines = [
        f"📚 知识库共 **{total}** 篇（已分类 {classified}，待整理 {unclassified}）",
        "",
        "**平台分布**：",
    ]
    for plat, cnt in sorted(platform_count.items(), key=lambda x: -x[1]):
        lines.append(f"  • {plat}: {cnt} 篇")
    return "\n".join(lines)


@tool
def list_pages(platform: str = None, days: int = None, page: int = 1) -> str:
    """浏览收藏列表，支持按平台和时间筛选（不做关键词匹配）。"""
    data = _get("/api/pages")
    pages = data.get("pages", [])
    if platform:
        pages = [p for p in pages if p.get("platform") == platform]
    lines = [f"共 {len(pages)} 篇\n"]
    for i, p in enumerate(pages[:20], 1):
        tags = p.get("tags")
        if isinstance(tags, str):
            tags = json.loads(tags) if tags else []
        tag_str = f" 🏷{','.join(tags)}" if tags else ""
        lines.append(f"{i}. {p['title'][:50]}{tag_str}")
        lines.append(f"   {p.get('platform','')} · {p.get('saved_at','')[:10]}")
    return "\n".join(lines)


# ── 分类专家工具 ──────────────────────────────────────────

@tool
def get_unclassified_pages(limit: int = 50) -> str:
    """获取尚未分类的页面列表（classified_at IS NULL）。分类专家第一步调用。"""
    data = _get("/api/pages/unclassified", limit=limit)
    pages = data.get("pages", [])
    if not pages:
        return "✅ 所有页面都已完成分类。"
    lines = [f"📋 待分类 {len(pages)} 篇：\n"]
    for i, p in enumerate(pages, 1):
        lines.append(f"{i}. {p['title'][:60]}")
        lines.append(f"   {p.get('platform','')} · {p.get('saved_at','')[:10]}")
        if p.get("summary"):
            lines.append(f"   📝 {p['summary'][:100]}")
        lines.append("")
    return "\n".join(lines)


@tool
def get_classifier_memory() -> str:
    """读取分类专家的长期记忆：分类树和关键词绑定。分类前调用，避免创建重复类目。"""
    data = _get("/api/taxonomy")
    cats = data.get("categories", [])
    if not cats:
        return "📂 分类记忆为空，首次运行，你可以自由建立分类体系。"
    lines = ["## 当前分类体系\n"]
    for cat in cats:
        parent = f"（属于 {cat['parent_id']}）" if cat.get("parent_id") else "（顶级）"
        kws = ", ".join(k["keyword"] for k in cat.get("keywords", [])[:10])
        lines.append(f"**{cat['name']}** {parent}")
        if kws:
            lines.append(f"  关键词：{kws}")
        lines.append("")
    return "\n".join(lines)


@tool
def save_classification_results(updates_json: str) -> str:
    """用户确认后，批量将分类标签写入 SQLite。
    ⚠️ 必须在展示预览并获得用户确认后才能调用。
    Args:
        updates_json: JSON 字符串，格式：[{"url":"...","tags":["科技","AI"],"category":"科技"}]
    """
    try:
        updates = json.loads(updates_json)
    except Exception as e:
        return f"❌ JSON 格式错误：{e}"
    data = _post("/api/classify/batch", {"updates": updates})
    return f"✅ 已完成 {data.get('updated', 0)} 篇分类标注。"


@tool
def update_classifier_memory(changes_json: str) -> str:
    """更新分类专家的长期记忆。每次分类任务完成后调用。
    Args:
        changes_json: JSON 字符串，格式：
          {"upsert_categories": [{"name": "AI", "parent": "科技"}],
           "upsert_keywords": [{"keyword": "Agent", "category": "AI", "weight": 1.0, "source": "auto"}],
           "delete_keywords": []}
    """
    try:
        changes = json.loads(changes_json)
    except Exception as e:
        return f"❌ JSON 格式错误：{e}"
    data = _put("/api/taxonomy", changes)
    return f"✅ 记忆更新：类目 {data.get('categories_upserted',0)} 个，关键词 {data.get('keywords_upserted',0)} 个。"


# ── 存档工具 ──────────────────────────────────────────────

@tool
def save_new_page(url: str, title: str, content: str) -> str:
    """将外部页面存入知识库（Deep Researcher 存档时使用）。
    ⚠️ 必须在用户确认后才能调用。
    Args:
        url: 页面 URL
        title: 页面标题
        content: 页面正文纯文本（非 HTML）
    """
    data = _post("/api/save", {
        "url": url,
        "title": title,
        "content": content,
        "saved_at": None,
    })
    if data.get("success"):
        return f"✅ 已存入：{title}"
    return f"❌ 存档失败：{data.get('message', '未知错误')}"


# 工具组合（按角色分配）
COMMANDER_TOOLS    = [get_library_overview, search_knowledge_base, list_pages]
CLASSIFIER_TOOLS   = [get_unclassified_pages, get_classifier_memory,
                      save_classification_results, update_classifier_memory]
REPORTER_TOOLS     = [get_library_overview, search_knowledge_base, get_page_content]
RESEARCHER_TOOLS   = [search_knowledge_base, save_new_page, get_library_overview]
ALL_TOOLS          = list({t.name: t for t in
    COMMANDER_TOOLS + CLASSIFIER_TOOLS + REPORTER_TOOLS + RESEARCHER_TOOLS}.values())
