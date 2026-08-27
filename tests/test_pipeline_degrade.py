# -*- coding: utf-8 -*-
"""流水线降级测试：无 API key 时运行每日流水线（隔离临时数据目录）。

预期：抓取真实新闻成功（网络可用时）→ AI 挑选/分析报"未配置 API Key"错误被捕获 →
话题卡同样报错 → 语段搜集跳过 → 整体返回 ok=False + errors，不崩溃、不产生脏数据。
"""
import sys, io
sys.path.insert(0, ".")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from _util import TmpData, SEED
from app.store import JsonStore
from app.pipeline import Pipeline
from app.llm import DeepSeekClient

tmp = TmpData()
store = JsonStore(tmp.dir, SEED)
store.set_config({"last_update_date": None})  # 确保从干净状态测
llm = DeepSeekClient("", "", "deepseek-chat")  # 无 key
pipe = Pipeline(store, llm)

print("配置了 key?", llm.configured)

r = pipe.run_daily()
print("ok:", r.get("ok"))
print("hotspots:", r.get("hotspots"), "| cards:", r.get("cards"), "| phrases:", r.get("phrases"))
print("errors:", len(r.get("errors", [])))
for e in r.get("errors", [])[:4]:
    print("  -", e[:90])

# 断言：无 key 时任何 AI 生成项都为 0（热点可能因挑选降级取最新 N 条但分析失败为 0）
assert r.get("hotspots") == 0 and r.get("cards") == 0 and r.get("phrases") == 0, r
assert any("API Key" in e for e in r.get("errors", [])), r.get("errors")
# 且没有写入任何草稿脏数据
ov = store.overview()
assert ov["hotspots_draft"] == 0 and ov["cards_draft"] == 0 and ov["phrases_total"] == 56, ov
# last_update_date 不应被推进（因为没生成任何内容）
cfg = store.get_config()
print("last_update_date:", cfg.get("last_update_date"))
assert cfg.get("last_update_date") is None, "完全失败时不应推进 last_update_date"
tmp.cleanup()

print("\n=== PIPELINE DEGRADE TEST PASSED ===")
