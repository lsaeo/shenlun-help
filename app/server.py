"""FastAPI 本地服务：JSON API + 前端静态托管。

所有 API 都在 127.0.0.1 随机端口上，仅供本机浏览器（内嵌 QWebEngineView）访问。
前端零构建：static/ 目录原样托管。
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .pipeline import Pipeline
from .store import THEMES, JsonStore

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
