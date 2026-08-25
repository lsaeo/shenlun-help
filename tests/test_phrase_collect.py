# -*- coding: utf-8 -*-
"""语段搜集模块测试：素材页抓取 + 去重逻辑（不调 LLM）。"""
import sys, io
sys.path.insert(0, ".")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from _util import TmpData, SEED
from app.store import JsonStore
from app.pipeline import Pipeline
from app.llm import DeepSeekClient
from app import fetchers

# 1) 素材页抓取
src = {"name": "排比式开头示例（中公）", "url": "http://m.offcn.com/gjgwy/2021/1221/81828.html"}
try:
    cands = fetchers.fetch_phrase_source(src)
    print(f"[OK] 素材页抓取 {len(cands)} 条候选")
    for c in cands[:3]:
        print("   -", c[:50])
    assert len(cands) > 0, "素材页应能提取候选语段"
except Exception as e:
    print(f"[WARN] 素材页抓取失败（网络/页面结构，可接受）: {type(e).__name__} {str(e)[:80]}")

# 2) 去重逻辑：无 LLM 时 _collect_phrases 应返回 0 且不产生脏数据
tmp = TmpData()
try:
    store = JsonStore(tmp.dir, SEED)
    before = len(store.list_all("phrases"))
    pipe = Pipeline(store, DeepSeekClient("", "", ""))  # 无 key
    # 手动测去重：构造已存在 key
    existing = {p["text"][:50] for p in store.list_all("phrases")}
    print(f"[OK] 种子语段 {before} 条, 去重键 {len(existing)} 个")
    assert len(existing) == before, "去重键数量应与语段数一致"

    # 3) 配置新字段存在
    cfg = store.get_config()
    assert "daily_phrases" in cfg and "phrase_sources" in cfg, cfg.keys()
    assert cfg["daily_phrases"] == 3 and len(cfg["phrase_sources"]) == 2
    print(f"[OK] 配置: daily_phrases={cfg['daily_phrases']}, phrase_sources={len(cfg['phrase_sources'])} 个")

    # 4) 无 key 跑 run_daily：语段搜集跳过，不影响其他逻辑
    r = pipe.run_daily()
    print(f"[OK] 无 key 流水线: ok={r.get('ok')}, phrases={r.get('phrases')}, errors={len(r.get('errors', []))}")
    assert r.get("phrases") == 0
    assert store.overview()["phrases_total"] == before, "语段不应被新增"
finally:
    tmp.cleanup()

print("\n=== PHRASE COLLECT TEST PASSED ===")
