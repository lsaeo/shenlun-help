# -*- coding: utf-8 -*-
"""V2 后端冒烟测试：复习/表达库/案例/拆解树/框架聚合 API。"""
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

config = uvicorn.Config(app, host="127.0.0.1", port=8877, log_level="error")
server = uvicorn.Server(config)
t = threading.Thread(target=server.run, daemon=True)
t.start()
for _ in range(50):
    try:
        httpx.get("http://127.0.0.1:8877/api/health", timeout=1)
        break
    except Exception:
        time.sleep(0.1)

base = "http://127.0.0.1:8877"
checks = []
def check(name, cond, extra=""):
    checks.append((name, cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  {extra}" if extra else ""))

# 复习：入池
r = httpx.post(f"{base}/api/review/phrases/p01/add")
check("复习入池", r.status_code == 200 and r.json()["stage"] == 0)
r = httpx.post(f"{base}/api/review/phrases/p01/add")
check("重复入池幂等", r.status_code == 200)
# 自评
r = httpx.post(f"{base}/api/review/phrases/p01/answer", json={"data": {"result": "remember"}})
check("自评remember", r.status_code == 200 and r.json()["stage"] == 1)
r = httpx.post(f"{base}/api/review/phrases/p01/answer", json={"data": {"result": "forget"}})
check("自评forget重置", r.status_code == 200 and r.json()["stage"] == 0)
# 非法自评
r = httpx.post(f"{base}/api/review/phrases/p01/answer", json={"data": {"result": "xxx"}})
check("非法自评拒绝", r.status_code == 400)
# 到期清单
r = httpx.get(f"{base}/api/review/due")
check("due+random 接口", r.status_code == 200 and "due" in r.json() and "random" in r.json())
# 进度
r = httpx.put(f"{base}/api/review/progress", json={"data": {"hotspots_scroll": 42}})
r = httpx.get(f"{base}/api/review")
check("进度保存", r.json()["progress"].get("hotspots_scroll") == 42)
# 移出
r = httpx.post(f"{base}/api/review/phrases/p01/remove")
r = httpx.get(f"{base}/api/review")
check("移出复习池", r.json()["items"] == [])

# 表达库
r = httpx.post(f"{base}/api/expressions", json={"data": {"text": "共建共治共享", "kind": ["好词"], "theme": ["基层治理"], "example": "示例"}})
eid = r.json()["id"]
check("表达库创建", bool(eid))
r = httpx.get(f"{base}/api/expressions/filter?kind=好词")
check("表达库筛选 kind", any(x["id"] == eid for x in r.json()["items"]))
r = httpx.post(f"{base}/api/expressions/{eid}/toggle-collect")
check("表达库收藏", r.json()["collected"] is True)

# 案例
r = httpx.post(f"{base}/api/cases", json={"data": {"title": "案例", "theme": "民生", "problems": ["a"]}})
cid = r.json()["id"]
check("案例创建", bool(cid))
r = httpx.get(f"{base}/api/cases")
check("案例列表", any(x["id"] == cid for x in r.json()["items"]))

# AI 拆解无 key → 400
r = httpx.post(f"{base}/api/cases/decompose", json={"data": {"description": "社区垃圾分类效果差"}})
check("AI拆解无key拒绝", r.status_code == 400)

# 拆解树
r = httpx.put(f"{base}/api/topics/民生", json={"data": {"dimensions": [{"name": "养老服务", "items": ["长期护理"]}]}})
check("拆解树更新", r.status_code == 200 and r.json()["dimensions"][0]["name"] == "养老服务")
r = httpx.get(f"{base}/api/topics")
check("拆解树列表", any(x["theme"] == "民生" for x in r.json()["items"]))

# 框架聚合
r = httpx.get(f"{base}/api/framework/民生")
check("框架聚合", r.status_code == 200 and r.json()["theme"] == "民生" and "phrases" in r.json())

# 概览新字段
r = httpx.get(f"{base}/api/overview")
ov = r.json()
check("概览新字段", "expressions_total" in ov and "review_pool" in ov)

server.should_exit = True
t.join(timeout=5)
tmp.cleanup()

failed = [c for c in checks if not c[1]]
print(f"\n=== {len(checks) - len(failed)}/{len(checks)} PASSED ===")
sys.exit(1 if failed else 0)
