# -*- coding: utf-8 -*-
"""临时冒烟测试：FastAPI 服务端 + 静态托管（隔离临时数据目录）"""
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
llm = DeepSeekClient("", "", "")
pipe = Pipeline(store, llm)
app = create_app(store, pipe)

config = uvicorn.Config(app, host="127.0.0.1", port=8765, log_level="error")
server = uvicorn.Server(config)
t = threading.Thread(target=server.run, daemon=True)
t.start()
for _ in range(50):
    try:
        httpx.get("http://127.0.0.1:8765/api/health", timeout=1)
        break
    except Exception:
        time.sleep(0.1)

base = "http://127.0.0.1:8765"
checks = []

def check(name, cond, extra=""):
    checks.append((name, cond, extra))
    print(("PASS " if cond else "FAIL ") + name + (f"  {extra}" if extra else ""))

# 健康检查
r = httpx.get(f"{base}/api/health")
check("health", r.json()["ok"] is True)

# 概览
r = httpx.get(f"{base}/api/overview")
ov = r.json()
check("overview", ov["phrases_total"] == 56 and ov["cards_total"] == 10, str(ov))

# 语段三维筛选
r = httpx.get(f"{base}/api/phrases/filter?position=开头&theme=民生")
items = r.json()["items"]
check("filter 开头+民生", len(items) >= 2, f"{len(items)} 条")

r = httpx.get(f"{base}/api/phrases/filter?technique=排比")
items = r.json()["items"]
check("filter 排比", len(items) >= 5, f"{len(items)} 条")

r = httpx.get(f"{base}/api/phrases/filter?q=民生")
items = r.json()["items"]
check("search 民生", len(items) >= 5, f"{len(items)} 条")

# 收藏切换
r = httpx.get(f"{base}/api/phrases/p01")
col0 = r.json().get("collected", False)
r = httpx.post(f"{base}/api/phrases/p01/toggle-collect")
check("toggle-collect", r.json()["collected"] is not col0)
r = httpx.post(f"{base}/api/phrases/p01/toggle-collect")  # 还原
check("toggle back", r.json()["collected"] is col0)

# copy 计数（used_count 会跨测试累积，断言 >= 之前值）
r = httpx.post(f"{base}/api/phrases/p01/copy")
check("mark_copied", r.json()["used_count"] >= 1, f"used={r.json()['used_count']}")

# 热点 CRUD + 审核
r = httpx.post(f"{base}/api/hotspots", json={"data": {"date": "2026-08-25", "title": "测试热点", "source": "smoke"}})
hid = r.json()["id"]
check("create hotspot", bool(hid), f"id={hid}")
r = httpx.post(f"{base}/api/hotspots/{hid}/review", json={"action": "publish"})
check("review publish", r.json()["status"] == "已入库")
r = httpx.post(f"{base}/api/hotspots/{hid}/review", json={"action": "delete"})
r = httpx.get(f"{base}/api/hotspots/{hid}")
check("delete hotspot", r.status_code == 404)

# 话题卡按主题过滤
r = httpx.get(f"{base}/api/topic_cards?status=已入库")
items = r.json()["items"]
check("cards list", len(items) == 10, f"{len(items)} 条")
r = httpx.get(f"{base}/api/topic_cards")
items = r.json()["items"]
themes = {i["theme"] for i in items}
check("cards themes", len(themes) >= 8, str(themes))

# 静态首页
r = httpx.get(f"{base}/")
check("static index", r.status_code == 200 and "申论素材助手" in r.text)
r = httpx.get(f"{base}/app.js")
check("static app.js", r.status_code == 200 and "loadHotspots" in r.text)

# 配置读写
r = httpx.put(f"{base}/api/config", json={"data": {"update_time": "09:00"}})
check("config update", r.json()["update_time"] == "09:00")
r = httpx.get(f"{base}/api/config")
check("config read", r.json()["update_time"] == "09:00")

server.should_exit = True
t.join(timeout=5)
tmp.cleanup()

failed = [c for c in checks if not c[1]]
print(f"\n=== {len(checks) - len(failed)}/{len(checks)} PASSED ===")
sys.exit(1 if failed else 0)
