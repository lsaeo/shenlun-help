"""FastAPI 本地服务：JSON API + 前端静态托管。

所有 API 都在 127.0.0.1 随机端口上，仅供本机浏览器（内嵌 QWebEngineView）访问。
前端零构建：static/ 目录原样托管。
"""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .pipeline import Pipeline
from .store import THEMES, JsonStore, sucai_dir as _sucai_dir

log = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).parent / "static"


def _require(name: str, item_id: str, store: JsonStore):
    item = store.get(name, item_id)
    if item is None:
        raise HTTPException(404, f"记录不存在: {name}/{item_id}")
    return item


class ReviewBody(BaseModel):
    action: str = Field(..., description="publish | draft | delete")


class GenericBody(BaseModel):
    data: dict = Field(default_factory=dict)


def create_app(store: JsonStore, pipeline: Pipeline) -> FastAPI:
    app = FastAPI(title="公考申论素材助手", docs_url=None, redoc_url=None)

    # ---------- 系统 ----------
    @app.get("/api/health")
    def health():
        return {"ok": True}

    @app.get("/api/overview")
    def overview():
        return store.overview()

    @app.get("/api/themes")
    def themes():
        return {"themes": THEMES}

    # ---------- 通用 CRUD（hotspots / topic_cards / phrases 共用） ----------
    # 为避免重复，用工厂按集合名生成路由

    def register_crud(prefix: str, name: str, list_path: str):
        @app.get(list_path)
        def list_items(q: str = "", status: str = ""):
            items = store.list_all(name)
            if status:
                items = [it for it in items if it.get("status") == status]
            if q:
                ql = q.lower()
                items = [
                    it for it in items
                    if ql in " ".join(str(v) for v in it.values()).lower()
                ]
            # 热点/话题卡按日期倒序
            if name in ("hotspots", "topic_cards"):
                items.sort(key=lambda it: it.get("date", ""), reverse=True)
            return {"items": items}

        @app.get(f"{prefix}/{{item_id}}")
        def get_item(item_id: str):
            return _require(name, item_id, store)

        @app.post(prefix)
        def create_item(body: GenericBody):
            return store.create(name, body.data)

        @app.put(f"{prefix}/{{item_id}}")
        def update_item(item_id: str, body: GenericBody):
            _require(name, item_id, store)
            updated = store.update(name, item_id, body.data)
            if updated is None:
                raise HTTPException(404, "记录不存在")
            return updated

        @app.delete(f"{prefix}/{{item_id}}")
        def delete_item(item_id: str):
            _require(name, item_id, store)
            store.delete(name, item_id)
            return {"ok": True}

        @app.post(f"{prefix}/{{item_id}}/review")
        def review_item(item_id: str, body: ReviewBody):
            _require(name, item_id, store)
            updated = store.review(name, item_id, body.action)
            if updated is None:
                raise HTTPException(400, f"未知审核动作: {body.action}")
            return updated

        @app.post(f"{prefix}/publish-all")
        def publish_all():
            """一键入库：该库所有草稿 → 已入库。"""
            n = store.publish_all_drafts(name)
            return {"published": n}

    register_crud("/api/hotspots", "hotspots", "/api/hotspots")
    register_crud("/api/topic_cards", "topic_cards", "/api/topic_cards")
    # 注意：/api/phrases/filter 必须注册在 /api/phrases/{item_id} 之前，
    # 否则会被动态路由当作 item_id="filter" 捕获。
    @app.get("/api/phrases/filter")
    def filter_phrases(position: str = "", theme: str = "", technique: str = "",
                       q: str = "", collected: str = ""):
        items = store.list_all("phrases")
        if position:
            items = [it for it in items if position in it.get("position", [])]
        if theme:
            items = [it for it in items if theme in it.get("theme", [])]
        if technique:
            items = [it for it in items if technique in it.get("technique", [])]
        if collected == "1":
            items = [it for it in items if it.get("collected")]
        if q:
            ql = q.lower()
            items = [it for it in items if ql in str(it.get("text", "")).lower()
                     or ql in str(it.get("usage", "")).lower()]
        return {"items": items}

    register_crud("/api/phrases", "phrases", "/api/phrases")

    @app.post("/api/phrases/{item_id}/toggle-collect")
    def toggle_collect(item_id: str):
        _require("phrases", item_id, store)
        updated = store.toggle_collect(item_id)
        if updated is None:
            raise HTTPException(404, "记录不存在")
        return updated

    @app.post("/api/phrases/{item_id}/copy")
    def mark_copied(item_id: str):
        _require("phrases", item_id, store)
        updated = store.mark_copied(item_id)
        if updated is None:
            raise HTTPException(404, "记录不存在")
        return updated

    # ---------- 表达库 ----------
    # 注意：filter/locate 必须注册在 /api/expressions/{item_id} 之前
    @app.get("/api/expressions/filter")
    def filter_expressions(kind: str = "", theme: str = "", q: str = "", collected: str = ""):
        items = store.list_all("expressions")
        if kind:
            items = [it for it in items if kind in it.get("kind", [])]
        if theme:
            items = [it for it in items if theme in it.get("theme", [])]
        if collected == "1":
            items = [it for it in items if it.get("collected")]
        if q:
            ql = q.lower()
            items = [it for it in items if ql in str(it.get("text", "")).lower()
                     or ql in str(it.get("example", "")).lower()]
        # 新生成的（带 date）按日期倒序在前，种子（无 date）排后面
        items.sort(key=lambda it: (it.get("date") is None, it.get("date", "")), reverse=False)
        items = sorted(items, key=lambda it: it.get("date") is not None, reverse=True)
        items = sorted([it for it in items if it.get("date")], key=lambda it: it["date"], reverse=True) + \
                [it for it in items if not it.get("date")]
        return {"items": items}

    @app.get("/api/expressions/locate")
    def locate_expression(q: str = ""):
        """按词精确查找表达，返回 {found, item, index} 供前端定位高亮。"""
        if not q:
            raise HTTPException(400, "q 不能为空")
        items = store.list_all("expressions")
        for i, it in enumerate(items):
            if it.get("text") == q:
                return {"found": True, "item": it, "index": i}
        return {"found": False, "item": None, "index": -1}

    register_crud("/api/expressions", "expressions", "/api/expressions")

    @app.post("/api/expressions/{item_id}/toggle-collect")
    def toggle_expr_collect(item_id: str):
        _require("expressions", item_id, store)
        updated = store.toggle_expr_collect(item_id)
        if updated is None:
            raise HTTPException(404, "记录不存在")
        return updated

    # ---------- 案例库（AI 辅助拆解产物） ----------
    register_crud("/api/cases", "cases", "/api/cases")

    @app.post("/api/cases/decompose")
    def decompose_case(body: GenericBody):
        """AI 辅助拆解：粘贴现象描述 → 结构化拆解草稿。"""
        desc = str(body.data.get("description", "")).strip()
        if not desc:
            raise HTTPException(400, "描述不能为空")
        if not pipeline.llm.configured:
            raise HTTPException(400, "未配置 API Key，无法使用 AI 拆解")
        result = {}
        def _run():
            nonlocal result
            try:
                result = pipeline.llm.decompose_case(desc)
            except Exception as e:  # noqa: BLE001
                result = {"error": str(e)}
        t = threading.Thread(target=_run, daemon=True)
        t.start()
        t.join(timeout=180)
        if result.get("error"):
            raise HTTPException(502, result["error"])
        return result

    # ---------- 复习系统 ----------
    @app.get("/api/review")
    def review_list():
        items = store.review_all()
        # 附内容摘要
        enriched = []
        for r in items:
            it = store.get(r["type"], r["item_id"])
            enriched.append({**r, "content": it})
        return {"items": enriched, "progress": store.review_progress()}

    @app.post("/api/review/{item_type}/{item_id}/add")
    def review_add(item_type: str, item_id: str):
        _require(item_type, item_id, store)
        return store.add_to_review(item_type, item_id)

    @app.post("/api/review/{item_type}/{item_id}/answer")
    def review_answer(item_type: str, item_id: str, body: GenericBody):
        result = body.data.get("result", "")
        if result not in ("remember", "fuzzy", "forget"):
            raise HTTPException(400, "result 必须是 remember/fuzzy/forget")
        updated = store.review_answer(item_type, item_id, result)
        if updated is None:
            raise HTTPException(404, "该内容不在复习池中")
        return updated

    @app.post("/api/review/{item_type}/{item_id}/remove")
    def review_remove(item_type: str, item_id: str):
        store.remove_from_review(item_type, item_id)
        return {"ok": True}

    @app.get("/api/review/due")
    def review_due():
        due = store.due_review()
        rand = store.random_review(store.get_config().get("daily_random", 3))
        return {"due": due, "random": rand}

    @app.put("/api/review/progress")
    def review_progress_save(body: GenericBody):
        store.set_review_progress(body.data)
        return {"ok": True}

    # ---------- 话题拆解树 ----------
    @app.get("/api/topics")
    def list_topics():
        return {"items": store.list_topics()}

    @app.put("/api/topics/{theme}")
    def upsert_topic(theme: str, body: GenericBody):
        dims = body.data.get("dimensions", [])
        if not isinstance(dims, list):
            raise HTTPException(400, "dimensions 必须是数组")
        return store.upsert_topic(theme, dims)

    # ---------- 框架聚合：某主题下的全部素材 ----------
    @app.get("/api/framework/{theme}")
    def framework(theme: str):
        """聚合某主题下的：表达库、语段、热点、话题卡、案例、拆解维度。"""
        topic = store.get_topic(theme)
        expressions = [e for e in store.list_all("expressions")
                       if theme in e.get("theme", []) and e.get("status") != "草稿"]
        phrases = [p for p in store.list_all("phrases")
                   if theme in p.get("theme", [])]
        hotspots = [h for h in store.list_all("hotspots")
                    if h.get("status") == "已入库" and theme in (h.get("angles", []) or []) or
                    (h.get("theme") == theme)]
        cards = [c for c in store.list_all("topic_cards")
                 if c.get("status") == "已入库" and c.get("theme") == theme]
        cases = [c for c in store.list_all("cases")
                 if c.get("theme") == theme and c.get("status") != "草稿"]
        return {
            "theme": theme,
            "topic": topic,
            "expressions": expressions,
            "phrases": phrases,
            "hotspots": hotspots,
            "cards": cards,
            "cases": cases,
            "templates": [t for t in store.list_all("templates")
                          if theme in t.get("theme", [])],
        }

    # ---------- 范文模板库 ----------
    register_crud("/api/templates", "templates", "/api/templates")

    @app.post("/api/templates/from-fanwen")
    def template_from_fanwen(body: GenericBody):
        """手动粘贴范文 → AI 解析成模板。body.data: {title, content}。"""
        if not pipeline.llm.configured:
            raise HTTPException(400, "未配置 API Key，无法解析模板")
        data = body.data
        title = str(data.get("title", "")).strip()
        content = str(data.get("content", "")).strip()
        if not title or not content:
            raise HTTPException(400, "title/content 不能为空")
        result = {}
        def _run():
            nonlocal result
            try:
                result = pipeline.llm.parse_fanwen_template(title, content)
            except Exception as e:  # noqa: BLE001
                result = {"error": str(e)}
        t = threading.Thread(target=_run, daemon=True)
        t.start()
        t.join(timeout=240)
        if result.get("error"):
            raise HTTPException(502, result["error"])
        template = store.create("templates", {
            "title": result.get("title", title),
            "source": "手动粘贴",
            "date": None,
            "theme": result.get("theme", []),
            "structure": result.get("structure", []),
            "killer_sentences": result.get("killer_sentences", []),
        })
        return template

    # ---------- 本地范文文件解析（V2 打磨二） ----------
    @app.post("/api/fanwen/parse-file")
    def fanwen_parse_file(body: GenericBody):
        """解析本地范文文件（docx/txt/xml）为模板。body.data: {path, title?}。"""
        if not pipeline.llm.configured:
            raise HTTPException(400, "未配置 API Key，无法解析模板")
        path = str(body.data.get("path", "")).strip()
        if not path or not os.path.isfile(path):
            raise HTTPException(400, f"文件不存在: {path}")
        title = str(body.data.get("title", "")).strip() or os.path.basename(path)
        result = {}
        def _run():
            nonlocal result
            try:
                result = pipeline._resolve_fanwen_from_file(path, title)
            except Exception as e:  # noqa: BLE001
                result = {"error": str(e)}
        t = threading.Thread(target=_run, daemon=True)
        t.start()
        t.join(timeout=240)
        if result.get("error"):
            raise HTTPException(502, result["error"])
        return result

    @app.get("/api/fanwen/index")
    def fanwen_index():
        """返回本地范文轮转索引与进度。"""
        return {"items": store.fanwen_index(), "stats": store.fanwen_stats()}

    @app.get("/api/fanwen/list-files")
    def fanwen_list_files():
        """列出 sucai 下可解析的文件。

        in_index=True 的文件已在每日轮转索引中（灰色不可手动解析，
        由流水线自动逐日解析）；False 为新加入文件，可点击手动解析。
        """
        sucai_dir = _sucai_dir()
        indexed = {a.get("file") for a in store.fanwen_index()}
        files = []
        if sucai_dir.is_dir():
            for fn in sorted(sucai_dir.iterdir()):
                if fn.name.startswith("~$"):
                    continue
                if fn.suffix.lower() in (".docx", ".txt", ".xml", ".docm"):
                    files.append({
                        "name": fn.name,
                        "path": str(fn),
                        "in_index": fn.name in indexed,
                    })
        return {"files": files}

    # ---------- 配置 ----------
    @app.get("/api/config")
    def get_config():
        return store.get_config()

    @app.put("/api/config")
    def put_config(body: GenericBody):
        return store.set_config(body.data)

    # ---------- 流水线 ----------
    @app.post("/api/pipeline/run")
    def run_pipeline():
        if pipeline.running:
            raise HTTPException(409, "流水线正在运行")
        result = {}
        def _run():
            nonlocal result
            result = pipeline.run_daily()
        t = threading.Thread(target=_run, daemon=True)
        t.start()
        t.join(timeout=600)
        return result

    @app.post("/api/pipeline/catchup")
    def catchup():
        if pipeline.running:
            raise HTTPException(409, "流水线正在运行")
        result = pipeline.run_catchup()
        return result

    # 静态托管必须最后挂载
    if STATIC_DIR.exists():
        app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
    else:
        @app.get("/")
        def index():
            return {"error": "前端目录缺失"}

    return app
