"""本地 JSON 数据层。

所有数据落在应用根目录的 data/ 下，文件：
  config.json      配置（API key、更新时间、每日数量、新闻源、字体、last_update_date）
  hotspots.json    真实热点（草稿|已入库）
  topic_cards.json 高频考点话题卡（草稿|已入库）
  phrases.json     万能语段库
  expressions.json 表达库（规范词/好词/平易词）
  cases.json       案例素材（AI 辅助拆解产物）
  topics.json      话题拆解树（8 主题 × 维度）
  review.json      复习池（记忆曲线排期 + 浏览进度）

线程安全：所有读写经 self._lock 串行化；对外返回深拷贝。
首次运行：data/ 缺失的文件若 seed/ 下存在同名种子，自动复制初始化。
"""
from __future__ import annotations

import copy
import json
import os
import threading
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

COLLECTIONS = ("hotspots", "topic_cards", "phrases", "expressions", "cases", "templates")
DEFAULT_CONFIG = {
    "api_key": "",
    "api_base": "https://api.deepseek.com",
    "model": "deepseek-v4-flash",  # 2026-07-24 起旧名 deepseek-chat 停用，迁移到 V4
    "ai_provider": "deepseek",
    "gemini_api_key": "",
    "gemini_model": "gemini-2.0-flash",
    "update_time": "07:00",
    "daily_hotspots": 5,
    "daily_cards": 5,
    "daily_phrases": 3,
    "daily_expressions": 3,
    "daily_cases": 2,
    "catchup_limit": 3,
    "daily_random": 3,
    "fanwen_interval_days": 3,
    "font_base": 14,
    "font_emphasis": 16,
    "sources": [
        {
            "name": "中国政府网要闻",
            "kind": "yaowen",
            "url": "https://www.gov.cn/",
            "keywords": [],
        },
        {
            "name": "新华网时政",
            "kind": "yaowen",
            "url": "https://www.news.cn/politics/",
            "keywords": [],
        },
        {
            "name": "人民日报要闻",
            "kind": "yaowen",
            "url": "https://www.people.com.cn/",
            "keywords": [],
        },
    ],
    "phrase_sources": [
        {
            "name": "人民日报金句模板（华图）",
            "url": "https://m.anshun.huatu.com/2026/0210/2016322.html",
        },
        {
            "name": "排比式开头示例（中公）",
            "url": "http://m.offcn.com/gjgwy/2021/1221/81828.html",
        },
    ],
    "expr_sources": [
        {
            "name": "申论规范词（中公）",
            "url": "http://www.offcn.com/gwy/2021/0716/77199.html",
        },
        {
            "name": "申论高频金句（华图）",
            "url": "https://www.huatu.com/gwy/ziliao/sl/slfw/",
        },
    ],
    "last_update_date": None,
    "last_fanwen_date": None,
}
THEMES = ["民生", "生态", "法治", "文化", "创新", "经济", "基层治理", "青年担当"]
# 记忆曲线间隔（天）：stage 0..7
REVIEW_INTERVALS = [1, 2, 4, 7, 15, 30, 60, 90]


def project_root() -> Path:
    """项目根目录（兼容 PyInstaller 打包）。

    开发: <root>/app/store.py -> <root>
    打包: <root>/_internal/app/store.py -> <root>（exe 旁，数据目录所在）
    """
    here = Path(__file__).resolve()
    if here.parent.name == "app" and here.parent.parent.name == "_internal":
        return here.parent.parent.parent
    return here.parent.parent


def sucai_dir() -> Path:
    """范文库目录（始终在 exe/项目根旁，可写）。"""
    return project_root() / "sucai"


def seed_dir() -> Path:
    """种子目录：打包时在 sys._MEIPASS/seed，开发时在项目根/seed。"""
    import sys as _sys
    if getattr(_sys, "frozen", False):
        meipass = Path(getattr(_sys, "_MEIPASS", project_root()))
        cand = meipass / "seed"
        if cand.is_dir():
            return cand
    return project_root() / "seed"


def today_str() -> str:
    return date.today().isoformat()


def new_id() -> str:
    return uuid.uuid4().hex[:12]


class JsonStore:
    """JSON 集合存取：list 型集合（hotspots/topic_cards/phrases）+ dict 型配置（config）。"""

    def __init__(self, data_dir: str, seed_dir: str | None = None):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self._lock = threading.RLock()
        self._files = {
            "config": os.path.join(data_dir, "config.json"),
            "hotspots": os.path.join(data_dir, "hotspots.json"),
            "topic_cards": os.path.join(data_dir, "topic_cards.json"),
            "phrases": os.path.join(data_dir, "phrases.json"),
            "expressions": os.path.join(data_dir, "expressions.json"),
            "cases": os.path.join(data_dir, "cases.json"),
            "templates": os.path.join(data_dir, "templates.json"),
            "topics": os.path.join(data_dir, "topics.json"),
            "review": os.path.join(data_dir, "review.json"),
            "fanwen": os.path.join(data_dir, "fanwen.json"),
            "fanwen_index": os.path.join(data_dir, "fanwen_index.json"),
        }
        self._cache: dict[str, object] = {}
        self._seed_dir = seed_dir
        self._load_all()

    # ---------- 内部：加载 / 保存 ----------

    def _load_all(self):
        with self._lock:
            for name, path in self._files.items():
                if os.path.exists(path):
                    try:
                        with open(path, encoding="utf-8") as f:
                            self._cache[name] = json.load(f)
                        continue
                    except Exception:
                        pass  # 文件损坏则回退到种子/默认
                # 缺失或损坏：尝试种子文件
                self._cache[name] = self._load_seed(name)
            if not isinstance(self._cache["config"], dict):
                self._cache["config"] = dict(DEFAULT_CONFIG)
            # 配置合并默认值（新增字段自动补齐）
            merged = dict(DEFAULT_CONFIG)
            merged.update(self._cache["config"])
            # 旧模型名自动迁移（deepseek-chat/deepseek-reasoner 2026-07-24 停用）
            old_model = merged.get("model", "")
            if old_model in ("deepseek-chat", "deepseek-reasoner"):
                merged["model"] = "deepseek-v4-flash"
            self._cache["config"] = merged
            for name in COLLECTIONS:
                if not isinstance(self._cache[name], list):
                    self._cache[name] = []
            # topics/review 为 dict 型结构
            if not isinstance(self._cache["topics"], list):
                self._cache["topics"] = []
            if not isinstance(self._cache["review"], dict):
                self._cache["review"] = {"items": [], "progress": {}}
            elif "items" not in self._cache["review"]:
                self._cache["review"]["items"] = []
            if not isinstance(self._cache["fanwen"], list):
                self._cache["fanwen"] = []
            if not isinstance(self._cache["fanwen_index"], dict):
                self._cache["fanwen_index"] = {"articles": []}
            elif "articles" not in self._cache["fanwen_index"]:
                self._cache["fanwen_index"]["articles"] = []
            self._save_all()

    def _load_seed(self, name: str):
        if not self._seed_dir:
            return copy.deepcopy(DEFAULT_CONFIG if name == "config" else [])
        path = os.path.join(self._seed_dir, f"{name}.json")
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return copy.deepcopy(DEFAULT_CONFIG if name == "config" else [])

    def _save_all(self):
        for name, path in self._files.items():
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._cache[name], f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)

    def _save(self, name: str):
        path = self._files[name]
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._cache[name], f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

    # ---------- 配置 ----------

    def get_config(self) -> dict:
        with self._lock:
            return copy.deepcopy(self._cache["config"])

    def set_config(self, patch: dict) -> dict:
        with self._lock:
            cfg = self._cache["config"]
            for k, v in patch.items():
                if k in DEFAULT_CONFIG:
                    cfg[k] = v
            self._save("config")
            return copy.deepcopy(cfg)

    # ---------- 列表集合通用 CRUD ----------

    def _coll(self, name: str) -> list[dict]:
        return self._cache[name]

    def list_all(self, name: str) -> list[dict]:
        with self._lock:
            return copy.deepcopy(self._coll(name))

    def get(self, name: str, item_id: str) -> dict | None:
        with self._lock:
            for it in self._coll(name):
                if it.get("id") == item_id:
                    return copy.deepcopy(it)
        return None

    def create(self, name: str, data: dict) -> dict:
        with self._lock:
            item = dict(data)
            item.setdefault("id", new_id())
            item.setdefault("created_at", datetime.now().isoformat(timespec="seconds"))
            item.setdefault("status", "草稿")
            self._coll(name).append(item)
            self._save(name)
            return copy.deepcopy(item)

    def update(self, name: str, item_id: str, data: dict) -> dict | None:
        with self._lock:
            for it in self._coll(name):
                if it.get("id") == item_id:
                    it.update({k: v for k, v in data.items() if k != "id"})
                    self._save(name)
                    return copy.deepcopy(it)
        return None

    def delete(self, name: str, item_id: str) -> bool:
        with self._lock:
            coll = self._coll(name)
            for i, it in enumerate(coll):
                if it.get("id") == item_id:
                    coll.pop(i)
                    self._save(name)
                    return True
        return False

    def review(self, name: str, item_id: str, action: str) -> dict | None:
        """action: publish(入库) / draft(退回草稿) / delete(删除)。"""
        with self._lock:
            for it in self._coll(name):
                if it.get("id") == item_id:
                    if action == "publish":
                        it["status"] = "已入库"
                    elif action == "draft":
                        it["status"] = "草稿"
                    elif action == "delete":
                        self._coll(name).remove(it)
                    else:
                        return None
                    self._save(name)
                    return copy.deepcopy(it)
        return None

    def publish_all_drafts(self, name: str) -> int:
        """一键入库：该集合所有草稿标记为已入库。返回入库条数。"""
        with self._lock:
            n = 0
            for it in self._coll(name):
                if it.get("status") == "草稿":
                    it["status"] = "已入库"
                    n += 1
            if n:
                self._save(name)
            return n

    # ---------- 语段库专属 ----------

    def toggle_collect(self, phrase_id: str) -> dict | None:
        with self._lock:
            for it in self._coll("phrases"):
                if it.get("id") == phrase_id:
                    it["collected"] = not bool(it.get("collected", False))
                    self._save("phrases")
                    return copy.deepcopy(it)
        return None

    def mark_copied(self, phrase_id: str) -> dict | None:
        with self._lock:
            for it in self._coll("phrases"):
                if it.get("id") == phrase_id:
                    it["used_count"] = int(it.get("used_count", 0)) + 1
                    self._save("phrases")
                    return copy.deepcopy(it)
        return None

    # ---------- 表达库专属 ----------

    def toggle_expr_collect(self, expr_id: str) -> dict | None:
        with self._lock:
            for it in self._coll("expressions"):
                if it.get("id") == expr_id:
                    it["collected"] = not bool(it.get("collected", False))
                    self._save("expressions")
                    return copy.deepcopy(it)
        return None

    # ---------- 话题拆解树 ----------

    def list_topics(self) -> list[dict]:
        with self._lock:
            return copy.deepcopy(self._cache["topics"])

    def get_topic(self, theme: str) -> dict | None:
        with self._lock:
            for t in self._cache["topics"]:
                if t.get("theme") == theme:
                    return copy.deepcopy(t)
        return None

    def upsert_topic(self, theme: str, dimensions: list[dict]) -> dict:
        """覆盖式更新某个主题的拆解维度。"""
        with self._lock:
            for t in self._cache["topics"]:
                if t.get("theme") == theme:
                    t["dimensions"] = dimensions
                    self._save("topics")
                    return copy.deepcopy(t)
            entry = {"theme": theme, "dimensions": dimensions}
            self._cache["topics"].append(entry)
            self._save("topics")
            return copy.deepcopy(entry)

    # ---------- 范文候选（3 选 1 审核流） ----------

    def list_fanwen_candidates(self) -> list[dict]:
        with self._lock:
            return copy.deepcopy(self._cache.get("fanwen", []))

    def save_fanwen_candidates(self, candidates: list[dict]):
        """保存范文候选（覆盖式，保留未审核的）。"""
        with self._lock:
            self._cache["fanwen"] = candidates
            self._save("fanwen")
            return copy.deepcopy(candidates)

    def confirm_fanwen(self, candidate_id: str) -> dict | None:
        """确认某篇候选：标记 confirmed，返回该候选供解析。"""
        with self._lock:
            for c in self._cache.get("fanwen", []):
                if c.get("id") == candidate_id:
                    c["confirmed"] = True
                    c["confirm_date"] = today_str()
                    self._save("fanwen")
                    return copy.deepcopy(c)
        return None

    def last_fanwen_date(self) -> str | None:
        with self._lock:
            return self._cache["config"].get("last_fanwen_date")

    # ---------- 范文索引（本地轮转解析） ----------

    def fanwen_index(self) -> list[dict]:
        """返回索引中的范文列表（含解析状态）。"""
        with self._lock:
            return copy.deepcopy(self._cache["fanwen_index"].get("articles", []))

    def save_fanwen_index(self, articles: list[dict]):
        """覆盖保存索引（合并状态：已解析/已跳过的保留，新篇加入）。"""
        with self._lock:
            old = {a.get("id"): a for a in self._cache["fanwen_index"].get("articles", [])}
            merged = []
            seen = set()
            for a in articles:
                aid = a.get("id") or f"{a.get('path')}#{a.get('index')}"
                # 保留旧状态
                if aid in old:
                    a["status"] = old[aid].get("status", "待解析")
                else:
                    a["status"] = "待解析"
                a["id"] = aid
                seen.add(aid)
                merged.append(a)
            self._cache["fanwen_index"]["articles"] = merged
            self._save("fanwen_index")
            return copy.deepcopy(merged)

    def next_fanwen_pending(self) -> dict | None:
        """取第一个待解析的范文（按顺序轮转）；无则返回 None。"""
        with self._lock:
            for a in self._cache["fanwen_index"].get("articles", []):
                if a.get("status") == "待解析":
                    return copy.deepcopy(a)
        return None

    def mark_fanwen_status(self, article_id: str, status: str):
        """标记范文状态：已解析 / 已跳过 / 待解析。"""
        with self._lock:
            for a in self._cache["fanwen_index"].get("articles", []):
                if a.get("id") == article_id:
                    a["status"] = status
                    a["resolved_date"] = today_str()
                    self._save("fanwen_index")
                    return True
        return False

    def fanwen_stats(self) -> dict:
        """轮转进度统计。"""
        with self._lock:
            arts = self._cache["fanwen_index"].get("articles", [])
            return {
                "total": len(arts),
                "pending": sum(1 for a in arts if a.get("status") == "待解析"),
                "resolved": sum(1 for a in arts if a.get("status") == "已解析"),
                "skipped": sum(1 for a in arts if a.get("status") == "已跳过"),
            }

    # ---------- 复习系统 ----------

    def review_all(self) -> list[dict]:
        with self._lock:
            return copy.deepcopy(self._cache["review"].get("items", []))

    def review_progress(self) -> dict:
        with self._lock:
            return copy.deepcopy(self._cache["review"].get("progress", {}))

    def set_review_progress(self, patch: dict):
        with self._lock:
            self._cache["review"]["progress"].update(patch)
            self._save("review")

    def is_in_review(self, item_type: str, item_id: str) -> bool:
        with self._lock:
            return any(r.get("type") == item_type and r.get("item_id") == item_id
                       for r in self._cache["review"].get("items", []))

    def add_to_review(self, item_type: str, item_id: str) -> dict:
        """点「背完了」→ 永久进入复习池，stage=0，明天首次到期。"""
        with self._lock:
            items = self._cache["review"].setdefault("items", [])
            for r in items:
                if r.get("type") == item_type and r.get("item_id") == item_id:
                    return copy.deepcopy(r)  # 已在池中
            entry = {
                "id": new_id(),
                "type": item_type,
                "item_id": item_id,
                "stage": 0,
                "next_review": (date.today() + timedelta(days=REVIEW_INTERVALS[0])).isoformat(),
                "last_review": None,
                "review_count": 0,
                "score": 3,
                "mastered": False,
            }
            items.append(entry)
            self._save("review")
            return copy.deepcopy(entry)

    def review_answer(self, item_type: str, item_id: str, result: str) -> dict:
        """闪卡自评：remember(记住了)/fuzzy(模糊)/forget(忘了)。

        remember → stage+1，间隔变长；fuzzy/forget → stage 回退 1 档，间隔缩短。
        连续到最高 stage 标记 mastered。
        """
        with self._lock:
            items = self._cache["review"].setdefault("items", [])
            for r in items:
                if r.get("type") == item_type and r.get("item_id") == item_id:
                    stage = int(r.get("stage", 0))
                    if result == "remember":
                        stage = min(stage + 1, len(REVIEW_INTERVALS) - 1)
                    elif result == "fuzzy":
                        stage = max(stage - 1, 0)
                    else:  # forget
                        stage = 0
                    r["stage"] = stage
                    r["last_review"] = today_str()
                    r["review_count"] = int(r.get("review_count", 0)) + 1
                    r["score"] = {"remember": 3, "fuzzy": 2, "forget": 1}.get(result, 3)
                    r["next_review"] = (date.today() + timedelta(days=REVIEW_INTERVALS[stage])).isoformat()
                    if stage >= len(REVIEW_INTERVALS) - 1:
                        r["mastered"] = True
                    self._save("review")
                    return copy.deepcopy(r)
        return None

    def remove_from_review(self, item_type: str, item_id: str) -> bool:
        with self._lock:
            items = self._cache["review"].setdefault("items", [])
            for i, r in enumerate(items):
                if r.get("type") == item_type and r.get("item_id") == item_id:
                    items.pop(i)
                    self._save("review")
                    return True
        return False

    def due_review(self, limit: int | None = None) -> list[dict]:
        """今日到期（next_review <= 今天 且未掌握）的复习项，附对应素材摘要。"""
        today = today_str()
        with self._lock:
            items = self._cache["review"].get("items", [])
            due = [r for r in items
                   if not r.get("mastered") and r.get("next_review", "9999") <= today]
            due.sort(key=lambda r: r.get("next_review", ""))
            # 附素材标题
            enriched = []
            for r in due[: limit or len(due)]:
                it = self.get(r["type"], r["item_id"])
                enriched.append({**r, "content": it})
            return enriched

    def random_review(self, n: int = 3) -> list[dict]:
        """每日随机抽查：从已入池未掌握的内容里随机抽 n 条（不重复今日已到期的）。"""
        import random
        today = today_str()
        with self._lock:
            items = [r for r in self._cache["review"].get("items", [])
                     if not r.get("mastered") and r.get("next_review", "9999") > today]
            picked = random.sample(items, min(n, len(items)))
            enriched = []
            for r in picked:
                it = self.get(r["type"], r["item_id"])
                enriched.append({**r, "content": it})
            return enriched

    # ---------- 概览 ----------

    def overview(self) -> dict:
        with self._lock:
            def drafts(name: str) -> int:
                return sum(1 for it in self._coll(name) if it.get("status") == "草稿")
            today = today_str()
            due_count = sum(1 for r in self._cache["review"].get("items", [])
                            if not r.get("mastered") and r.get("next_review", "9999") <= today)
            return {
                "hotspots_total": len(self._coll("hotspots")),
                "hotspots_draft": drafts("hotspots"),
                "cards_total": len(self._coll("topic_cards")),
                "cards_draft": drafts("topic_cards"),
                "phrases_total": len(self._coll("phrases")),
                "expressions_total": len(self._coll("expressions")),
                "review_pool": len(self._cache["review"].get("items", [])),
                "review_due": due_count,
                "last_update_date": self._cache["config"].get("last_update_date"),
            }
