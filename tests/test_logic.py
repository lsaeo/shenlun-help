# -*- coding: utf-8 -*-
"""临时冒烟测试：数据层 + 纯逻辑（隔离临时数据目录，不碰真实 data/）"""
import sys, io
sys.path.insert(0, ".")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from _util import TmpData, SEED
from app.llm import _strip_code_fence
from app.pipeline import _dates_since_last, Pipeline
from app.store import JsonStore

# 1) JSON 清洗
cases = [
    ('{"意义": "x"}', '{"意义": "x"}'),
    ('```json\n{"意义": "y"}\n```', '{"意义": "y"}'),
    ('好的，结果如下：\n{"意义": "z"}\n希望有帮助', '{"意义": "z"}'),
    ('{bad json', '{bad json'),
]
for src, want in cases:
    got = _strip_code_fence(src)
    assert got == want, f"{src!r} -> {got!r}, want {want!r}"
print("[OK] _strip_code_fence 4 cases")

# 2) 补拉日期
from datetime import date as _date, timedelta as _td
_today = _date.today()
d1 = _dates_since_last(None, 3)
assert d1 and len(d1) >= 1, d1
d2 = _dates_since_last(_today.isoformat(), 3)  # 今天无缺失
assert d2 == [], d2
d3 = _dates_since_last((_today - _td(days=5)).isoformat(), 3)  # 缺 5 天，上限 3
assert len(d3) == 3, d3
print("[OK] _dates_since_last")

# 3) 主题轮转
th = Pipeline._pick_themes(5, _today.isoformat())
assert len(th) == 5 and len(set(th)) == 5, th
print("[OK] _pick_themes:", th)

# 4) store 全链路（隔离目录）
tmp = TmpData()
try:
    store = JsonStore(tmp.dir, SEED)
    assert len(store.list_all("phrases")) == 56
    assert len(store.list_all("topic_cards")) == 10
    assert store.overview()["hotspots_total"] == 0

    item = store.create("hotspots", {"date": _today.isoformat(), "title": "t", "source": "s", "summary": "m"})
    assert item["status"] == "草稿"
    assert store.review("hotspots", item["id"], "publish")["status"] == "已入库"
    assert store.delete("hotspots", item["id"]) is True
    assert store.get("hotspots", item["id"]) is None

    cfg = store.set_config({"update_time": "08:30"})
    assert cfg["update_time"] == "08:30"
    print("[OK] store CRUD + config")

    # 5) 语段模板化字段：全部种子语段必须带 template + examples
    phrases = store.list_all("phrases")
    for it in phrases:
        assert it.get("template"), f"{it['id']} 缺 template"
        assert "____" in it["template"], f"{it['id']} 框架缺 ____ 占位符"
        assert it.get("examples"), f"{it['id']} 缺 examples"
    print(f"[OK] 语段模板化: {len(phrases)} 条全部带框架+例句")
finally:
    tmp.cleanup()

print("\n=== ALL LOGIC TESTS PASSED ===")
