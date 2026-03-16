#!/usr/bin/env python3
"""
lite_server.py — WebRecall 轻量写入服务

纯 SQLite 读写，不需要 Ollama / ChromaDB / 任何 AI 模型。
内存占用 ~15MB，CPU 几乎为零。

插件保存网页时：完整后端(8000) → lite_server(8001) → chrome.storage
"""
import sys
import os

# 确保能导入 db.sqlite_store 和 utils.platform
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime
from typing import Optional
from db.sqlite_store import (
    init_sqlite, save_page, delete_page, list_pages,
    get_stats, search_pages, get_overview,
    get_unclassified_pages, batch_update_tags, get_taxonomy, update_taxonomy,
)
from utils.platform import extract_domain, domain_to_platform



# ── App ──────────────────────────────────────────────────────

init_sqlite()

app = FastAPI(title="WebRecall Lite", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class SaveRequest(BaseModel):
    url: str
    title: str = ""
    content: str = ""
    html: str = ""
    saved_at: Optional[str] = None


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0", "mode": "lite"}


@app.post("/api/save")
async def api_save(req: SaveRequest):
    content = req.content or ""
    if not content and not req.html:
        raise HTTPException(400, "需要 content 或 html")

    domain = extract_domain(req.url)
    platform = domain_to_platform(domain)
    now = datetime.now()
    saved_at = req.saved_at or now.isoformat()
    try:
        ts = datetime.fromisoformat(saved_at).timestamp()
    except Exception:
        ts = now.timestamp()

    save_page(
        url=req.url,
        title=req.title or req.url,
        domain=domain,
        platform=platform,
        content=content,
        saved_at=saved_at,
        saved_at_ts=ts,
    )
    return {"success": True, "message": "已保存到 SQLite（轻量模式）"}


@app.get("/api/pages")
async def api_pages():
    pages = list_pages(limit=200)
    return {"pages": pages, "total": len(pages)}


@app.get("/api/stats")
async def api_stats():
    stats = get_stats()
    overview = get_overview()
    return {
        "total_pages": stats["total_pages"],
        "total_chunks": 0,
        "top_platforms": list(overview.get("platforms", {}).keys())[:5],
        "platform_counts": overview.get("platforms", {}),
        "mode": "lite",
    }


@app.delete("/api/pages")
async def api_delete(url: str):
    if delete_page(url):
        return {"success": True, "deleted_chunks": 1}
    return {"success": False, "message": "未找到该页面"}


@app.get("/api/search")
async def api_search(q: str, limit: int = 10, days: Optional[int] = None):
    results = search_pages(query=q, limit=limit, days=days)
    import json as _json
    formatted = []
    for r in results:
        raw_tags = r.get("tags")
        tags = _json.loads(raw_tags) if isinstance(raw_tags, str) and raw_tags else (raw_tags or [])
        formatted.append({
            "url": r["url"],
            "title": r["title"],
            "domain": r.get("domain", ""),
            "platform": r.get("platform", ""),
            "saved_at": r.get("saved_at", ""),
            "snippet": (r.get("summary", "") or r.get("title", ""))[:200],
            "tags": tags,
        })
    return {"results": formatted}


# ── 分类专家接口 ──────────────────────────────────────────────

@app.get("/api/pages/unclassified")
async def api_unclassified(limit: int = 50):
    """返回尚未分类的页面（classified_at IS NULL）。"""
    pages = get_unclassified_pages(limit=limit)
    return {"pages": pages, "total": len(pages)}


class BatchTagsItem(BaseModel):
    url: str
    tags: list
    category: Optional[str] = None

class BatchTagsRequest(BaseModel):
    updates: list[BatchTagsItem]

@app.post("/api/classify/batch")
async def api_classify_batch(req: BatchTagsRequest):
    """批量写 tags + classified_at。分类专家用户确认后调用。"""
    updated = batch_update_tags([u.model_dump() for u in req.updates])
    return {"success": True, "updated": updated}


@app.get("/api/taxonomy")
async def api_get_taxonomy():
    """读取分类专家的长期记忆（分类树 + 关键词绑定）。"""
    return get_taxonomy()


class TaxonomyUpdateRequest(BaseModel):
    upsert_categories: Optional[list] = []
    upsert_keywords:   Optional[list] = []
    delete_keywords:   Optional[list] = []

@app.put("/api/taxonomy")
async def api_update_taxonomy(req: TaxonomyUpdateRequest):
    """更新分类专家记忆（类目和关键词绑定）。"""
    stats = update_taxonomy(req.model_dump())
    return {"success": True, **stats}


@app.post("/shutdown")
async def shutdown():
    """优雅关闭 Lite Server（供插件 Native Messaging Host 调用）"""
    import threading
    def _exit():
        import time, os, signal
        time.sleep(0.5)
        os.kill(os.getpid(), signal.SIGTERM)
    threading.Thread(target=_exit, daemon=True).start()
    return {"status": "shutting_down"}


if __name__ == "__main__":
    import uvicorn
    print("🚀 WebRecall Lite Server starting on port 8001...")
    print("   纯 SQLite 模式，不需要 Ollama")
    uvicorn.run(app, host="0.0.0.0", port=8001)
