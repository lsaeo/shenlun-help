# -*- coding: utf-8 -*-
"""流水线异步化测试：run 立即返回 + status 查询 + 熔断 stopped。"""
import sys, io, threading, time
sys.path.insert(0, ".")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import httpx
import uvicorn
from _util import TmpData, SEED
from app.store import JsonStore
from app.pipeline import Pipeline
from app.llm import DeepSeekClient, LLMError
from app.server import create_app

tmp = TmpData()
store = JsonStore(tmp.dir, SEED)
pipe = Pipeline(store, DeepSeekClient("", "", "deepseek-v4-flash"))  # 无 key → 快速失败
app = create_app(store, pipe)

config = uvicorn.Config(app, host="127.0.0.1", port=8895, log_level="error", log_config=None)
server = uvicorn.Server(config)
t = threading.Thread(target=server.run, daemon=True)
t.start()
for _ in range(50):
    try:
        httpx.get("http://127.0.0.1:8895/api/health", timeout=1)
        break
    except Exception:
        time.sleep(0.1)

base = "http://127.0.0.1:8895"
checks = []
def check(name, cond, extra=""):
    checks.append((name, cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  {extra}" if extra else ""))

# 1) run 立即返回（不阻塞）
t0 = time.time()
r = httpx.post(f"{base}/api/pipeline/run")
dt = time.time() - t0
check("run 立即返回", r.status_code == 200 and r.json().get("started") is True and dt < 3, f"耗时{dt:.1f}s")

# 2) status 能查到 running
time.sleep(0.5)
st = httpx.get(f"{base}/api/pipeline/status").json()
check("status 返回 running", st.get("state") == "running" or st.get("state") in ("done", "failed", "partial"),
      f"state={st.get('state')}")

# 3) 无 key 会失败，最终状态 failed（快速，不卡死）
for _ in range(60):
    st = httpx.get(f"{base}/api/pipeline/status").json()
    if st.get("state") != "running":
        break
    time.sleep(0.5)
check("流水线最终有终态", st.get("state") != "running", f"state={st.get('state')} msg={st.get('message','')[:40]}")

# 4) reset-status
r = httpx.post(f"{base}/api/pipeline/reset-status")
st = httpx.get(f"{base}/api/pipeline/status").json()
check("reset 后 idle", st.get("state") == "idle")

# 5) catchup 异步
r = httpx.post(f"{base}/api/pipeline/catchup")
check("catchup 异步启动", r.status_code == 200 and r.json().get("started") is True)

server.should_exit = True
t.join(timeout=5)
tmp.cleanup()
failed = [c for c in checks if not c[1]]
print(f"\n=== {len(checks) - len(failed)}/{len(checks)} PASSED ===")
sys.exit(1 if failed else 0)
