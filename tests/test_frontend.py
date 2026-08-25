# -*- coding: utf-8 -*-
"""前端渲染冒烟测试 v2：轮询等待前端 JS 就绪后，验证渲染结果。"""
import sys, io
sys.path.insert(0, ".")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineWidgets import QWebEngineView

from app.main import App

app_obj = App()
app_obj.start_server()
print(f"[OK] 服务: http://127.0.0.1:{app_obj.port}")

qapp = QApplication(sys.argv)
view = QWebEngineView()
view.setUrl(QUrl(f"http://127.0.0.1:{app_obj.port}/"))
console_msgs = []
view.page().javaScriptConsoleMessage = lambda level, msg, line, src: console_msgs.append(msg)
view.show()

results = {}
probe_count = 0

def probe():
    """轮询检查前端 JS 是否就绪（app.js 的 init 完成）。"""
    global probe_count
    probe_count += 1
    if probe_count > 15:  # ~7.5s 上限
        print("[FAIL] 前端 JS 未就绪")
        finish()
        return
    view.page().runJavaScript(
        "typeof switchTab !== 'undefined' && document.getElementById('overview').innerText.length > 0",
        lambda ready: proceed(ready))

def proceed(ready):
    if not ready:
        QTimer.singleShot(500, probe)
        return
    print("[OK] 前端 JS 就绪")
    # 切到语段库页触发加载（loadPhrases 内部是 async fetch）
    view.page().runJavaScript("switchTab('phrases')", lambda _: QTimer.singleShot(2500, read_dom))

def read_dom():
    view.page().runJavaScript(
        "JSON.stringify({"
        "  n: document.querySelectorAll('#ph-list .item').length,"
        "  badges: document.getElementById('overview').innerText,"
        "  tmpl: document.querySelectorAll('.phrase-template').length,"
        "  ex: document.querySelectorAll('.pe-item').length,"
        "  copyBtn: document.querySelectorAll('button[data-act=copy-template]').length"
        "})", step3)

def step3(res):
    try:
        import json
        r = json.loads(res or "{}")
        results["n"] = r.get("n", 0)
        results["badges"] = r.get("badges", "")
        print(f"[{'OK' if results['n'] >= 10 else 'FAIL'}] 语段库渲染 {results['n']} 条")
        print(f"[{'OK' if '语段' in results['badges'] else 'FAIL'}] 概览徽章: {results['badges'][:80]}")
        print(f"[{'OK' if r.get('tmpl', 0) >= 10 else 'FAIL'}] 填空框架展示 {r.get('tmpl', 0)} 处")
        print(f"[{'OK' if r.get('ex', 0) >= 10 else 'FAIL'}] 改写例句展示 {r.get('ex', 0)} 条")
        print(f"[{'OK' if r.get('copyBtn', 0) >= 10 else 'FAIL'}] 复制框架按钮 {r.get('copyBtn', 0)} 个")
    except Exception as e:
        print("[FAIL] 解析失败:", e, "raw:", str(res)[:80])
        results["n"] = 0
    finish()

def finish():
    ok = results.get("n", 0) >= 10
    print("\n=== FRONTEND TEST", "PASSED" if ok else "FAILED", "===")
    qapp.quit()

QTimer.singleShot(1500, probe)
QTimer.singleShot(20000, qapp.quit)
qapp.exec()
sys.exit(0 if results.get("n", 0) >= 10 else 1)
