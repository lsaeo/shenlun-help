# -*- coding: utf-8 -*-
"""重复生成防护测试：同一天内多次运行流水线不应产生重复草稿。"""
import sys, io
sys.path.insert(0, ".")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from _util import TmpData, SEED
from app.store import JsonStore
from app.pipeline import Pipeline
from app.llm import DeepSeekClient, LLMError


class FakeLLM:
    """模拟 LLM：返回固定内容，带计数。"""
    configured = True

    def __init__(self):
        self.hot_calls = 0
        self.card_calls = 0
        self.pick_calls = 0

    def pick_hotspots(self, candidates):
        self.pick_calls += 1
        return candidates[:2]

    def analyze_hotspot(self, title, summary, source=""):
        self.hot_calls += 1
        return {"重点提炼": ["要点"], "可背金句": "金句", "意义": f"意义-{title}",
                "角度": ["角度1"], "对策": ["对策1"], "金句": "金句", "angles": ["可用方向"]}

    def generate_topic_card(self, theme):
        self.card_calls += 1
        return {"topic": f"{theme}话题", "背景": "背景", "意义": "意义",
                "问题": "问题", "对策": ["对策"], "金句": "金句", "angles": ["可用方向"]}

    def format_phrase(self, raw_text):
        return {"text": f"整理后-{raw_text[:20]}", "template": "____模板____",
                "examples": ["例句"], "position": ["开头"], "theme": ["民生"],
                "technique": ["排比"], "usage": "测试用"}


class FakeFetcher:
    """模拟抓取：固定返回两条新闻。"""
    @staticmethod
    def fetch_news(sources, limit=5, keywords=None):
        return [
            {"title": "新闻A", "url": "http://a", "source": "测试", "date": "2026-08-26", "summary": "摘要A"},
            {"title": "新闻B", "url": "http://b", "source": "测试", "date": "2026-08-26", "summary": "摘要B"},
        ]


tmp = TmpData()
try:
    store = JsonStore(tmp.dir, SEED)
    llm = FakeLLM()
    pipe = Pipeline(store, llm)
    # 把 fetchers.fetch_news 换成假的
    import app.pipeline as pipeline_mod
    pipeline_mod.fetchers.fetch_news = FakeFetcher.fetch_news

    # 第一次运行
    r1 = pipe.run_daily()
    ov1 = store.overview()
    print(f"第一次: 热点{ov1['hotspots_total']}(草稿{ov1['hotspots_draft']}) 卡{ov1['cards_total']}(草稿{ov1['cards_draft']})")

    # 第二次运行（同一天）→ 不应新增
    r2 = pipe.run_daily()
    ov2 = store.overview()
    print(f"第二次: 热点{ov2['hotspots_total']}(草稿{ov2['hotspots_draft']}) 卡{ov2['cards_total']}(草稿{ov2['cards_draft']})")

    assert ov2["hotspots_draft"] == ov1["hotspots_draft"], "同日重复运行不应新增热点草稿"
    assert ov2["cards_draft"] == ov1["cards_draft"], "同日重复运行不应新增话题卡草稿"
    # 热点按标题去重
    titles = [it["title"] for it in store.list_all("hotspots")]
    assert len(set(titles)) == len(titles), "热点标题不应重复"
    # 话题卡当日按主题去重
    today_cards = [it["theme"] for it in store.list_all("topic_cards") if it.get("date") == "2026-08-26"]
    assert len(set(today_cards)) == len(today_cards), "当日话题卡主题不应重复"
    print(f"LLM 调用: 热点{llm.hot_calls}次 / 卡{llm.card_calls}次（第二次运行应明显减少）")
finally:
    tmp.cleanup()

print("\n=== DEDUP TEST PASSED ===")
