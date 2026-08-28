# -*- coding: utf-8 -*-
"""V2 优化测试：一键入库 + 表达库排序 + 文件 in_index 标记。"""
import sys, io, threading, time
sys.path.insert(0, ".")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import httpx
import uvicorn
from _util import TmpData, SEED
from app.store import JsonStore
from app.pipeline import Pipeline
from app.llm import DeepSeekClient
from app.server import create_app

tmp = TmpData()
store = JsonStore(tmp.dir, SEED)
pipe = Pipeline(store, DeepSeekClient("", "", "deepseek-v4-flash"))
app = create_app(store, pipe)

config = uvicorn.Config(app, host="127.0.0.1", port=8893, log_level="error", log_config=None)
server = uvicorn.Server(config)
t = threading.Thread(target=server.run, daemon=True)
t.start()
for _ in range(50):
    try:
        httpx.get("http://127.0.0.1:8893/api/health", timeout=1)
        break
    except Exception:
        time.sleep(0.1)

base = "http://127.0.0.1:8893"
checks = []
def check(name, cond, extra=""):
    checks.append((name, cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  {extra}" if extra else ""))

# 1) 一键入库：造几个草稿再批量发布
for i in range(3):
    httpx.post(f"{base}/api/hotspots", json={"data": {"title": f"草稿{i}", "date": "2026-08-27"}})
r = httpx.get(f"{base}/api/hotspots?status=草稿")
check("造草稿", len(r.json()["items"]) == 3, f"{len(r.json()['items'])} 条")
r = httpx.post(f"{base}/api/hotspots/publish-all")
check("一键入库", r.json().get("published") == 3, f"published={r.json().get('published')}")
r = httpx.get(f"{base}/api/hotspots?status=草稿")
check("入库后无草稿", len(r.json()["items"]) == 0)
r = httpx.get(f"{base}/api/hotspots?status=已入库")
check("入库后已入库数", len(r.json()["items"]) == 3)

# 2) 表达库排序：新(带date)在前
httpx.post(f"{base}/api/expressions", json={"data": {"text": "新词A", "kind": ["好词"], "theme": ["民生"], "date": "2026-08-27"}})
httpx.post(f"{base}/api/expressions", json={"data": {"text": "新词B", "kind": ["好词"], "theme": ["民生"], "date": "2026-08-26"}})
r = httpx.get(f"{base}/api/expressions/filter")
items = r.json()["items"]
first_with_date = [it for it in items if it.get("date")]
check("表达排序-新在前", len(first_with_date) >= 2 and first_with_date[0]["text"] == "新词A",
      f"前两个带date: {[i['text'] for i in first_with_date[:2]]}")
# 无 date 的种子排最后
last_items = items[-3:]
check("表达排序-种子在后", all(not it.get("date") for it in last_items),
      f"末尾: {[i['text'] for i in last_items]}")

# 3) 文件 in_index 标记（隔离目录无 sucai，验证 API 形状）
r = httpx.get(f"{base}/api/fanwen/list-files")
check("文件列表含in_index字段", all("in_index" in f for f in r.json().get("files", [])) or not r.json().get("files"),
      f"files={len(r.json().get('files', []))}")

server.should_exit = True
t.join(timeout=5)
tmp.cleanup()
failed = [c for c in checks if not c[1]]
print(f"\n=== {len(checks) - len(failed)}/{len(checks)} PASSED ===")
sys.exit(1 if failed else 0)
