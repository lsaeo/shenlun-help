"""本地 JSON 数据层。

所有数据落在应用根目录的 data/ 下，四个文件：
  config.json      配置（API key、更新时间、每日数量、新闻源、last_update_date）
  hotspots.json    真实热点（草稿|已入库）
  topic_cards.json 高频考点话题卡（草稿|已入库）
  phrases.json     万能语段库

线程安全：所有读写经 self._lock 串行化；对外返回深拷贝。
首次运行：data/ 缺失的文件若 seed/ 下存在同名种子，自动复制初始化。
"""
from __future__ import annotations

import copy
import json
import os
import threading
import uuid
from datetime import date, datetime

COLLECTIONS = ("hotspots", "topic_cards", "phrases")
DEFAULT_CONFIG = {
    "api_key": "",
    "api_base": "https://api.deepseek.com",
    "model": "deepseek-chat",
    "update_time": "07:00",
    "daily_hotspots": 5,
    "daily_cards": 5,
    "daily_phrases": 3,
    "catchup_limit": 3,
    "sources": [
        {
            "name": "人民网时政",
            "kind": "rss",
            "url": "http://www.people.com.cn/rss/politics.xml",
            "keywords": ["民生", "生态", "法治", "经济", "创新", "文化", "乡村",
                         "基层", "就业", "养老", "教育", "医疗", "改革", "科技", "人才"],
        },
        {
            "name": "新华网时政",
            "kind": "rss",
            "url": "http://www.xinhuanet.com/politics/news_politics.xml",
            "keywords": ["民生", "生态", "法治", "经济", "创新", "文化", "乡村",
                         "基层", "就业", "养老", "教育", "医疗", "改革", "科技", "人才"],
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
    "last_update_date": None,
}
THEMES = ["民生", "生态", "法治", "文化", "创新", "经济", "基层治理", "青年担当"]


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
            self._cache["config"] = merged
            for name in COLLECTIONS:
                if not isinstance(self._cache[name], list):
                    self._cache[name] = []
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

    # ---------- 概览 ----------

    def overview(self) -> dict:
        with self._lock:
            def drafts(name: str) -> int:
                return sum(1 for it in self._coll(name) if it.get("status") == "草稿")
            return {
                "hotspots_total": len(self._coll("hotspots")),
                "hotspots_draft": drafts("hotspots"),
                "cards_total": len(self._coll("topic_cards")),
                "cards_draft": drafts("topic_cards"),
                "phrases_total": len(self._coll("phrases")),
                "last_update_date": self._cache["config"].get("last_update_date"),
            }
