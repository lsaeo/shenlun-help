# -*- coding: utf-8 -*-
"""V2 打磨后端冒烟测试：templates/范文候选/表达定位。"""
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

config = uvicorn.Config(app, host="127.0.0.1", port=8899, log_level="error")
server = uvicorn.Server(config)
t = threading.Thread(target=server.run, daemon=True)
t.start()
for _ in range(50):
    try:
        httpx.get("http://127.0.0.1:8899/api/health", timeout=1)
        break
    except Exception:
        time.sleep(0.1)

base = "http://127.0.0.1:8899"
checks = []
def check(name, cond, extra=""):
    checks.append((name, cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  {extra}" if extra else ""))

# 范文索引（本地轮转）
r = httpx.get(f"{base}/api/fanwen/index")
check("范文索引接口", r.status_code == 200 and "items" in r.json() and "stats" in r.json())
r = httpx.get(f"{base}/api/fanwen/list-files")
check("范文文件列表", r.status_code == 200 and "files" in r.json())

# 手动粘贴 → 模板（无 key 应拒绝）
r = httpx.post(f"{base}/api/templates/from-fanwen", json={"data": {"title": "t", "content": "c"}})
check("粘贴解析无key拒绝", r.status_code == 400)

# 手动解析本地文件（无 key 应拒绝；测试目录无文件也走 400 前）
r = httpx.post(f"{base}/api/fanwen/parse-file", json={"data": {"path": "D:\\不存在的文件.docx"}})
check("解析文件无key拒绝", r.status_code == 400)

# 模板库 CRUD
r = httpx.post(f"{base}/api/templates", json={"data": {"title": "模板A", "theme": ["民生"], "structure": [], "killer_sentences": []}})
tid = r.json()["id"]
check("模板创建", bool(tid))
r = httpx.get(f"{base}/api/templates")
check("模板列表", any(x["id"] == tid for x in r.json()["items"]))
r = httpx.put(f"{base}/api/templates/{tid}", json={"data": {"title": "模板A改"}})
check("模板更新", r.json()["title"] == "模板A改")
r = httpx.delete(f"{base}/api/templates/{tid}")
check("模板删除", r.status_code == 200)

# 表达定位
r = httpx.get(f"{base}/api/expressions/locate?q=共建共治共享")
check("表达定位命中", r.json().get("found") is True and r.json()["item"]["text"] == "共建共治共享")
r = httpx.get(f"{base}/api/expressions/locate?q=不存在的词")
check("表达定位未命中", r.json().get("found") is False)

# 框架聚合含 templates
r = httpx.get(f"{base}/api/framework/民生")
check("框架聚合含模板", "templates" in r.json())

# 拆解树更新（带 explain/cases 字段）
r = httpx.put(f"{base}/api/topics/民生", json={"data": {"dimensions": [
    {"name": "养老服务", "items": ["长期护理"], "explain": "养老是民生高频考点", "cases": ["真题：社区养老"]}]}})
check("拆解树带解释案例", r.json()["dimensions"][0].get("explain") == "养老是民生高频考点")

server.should_exit = True
t.join(timeout=5)
tmp.cleanup()

failed = [c for c in checks if not c[1]]
print(f"\n=== {len(checks) - len(failed)}/{len(checks)} PASSED ===")
sys.exit(1 if failed else 0)
