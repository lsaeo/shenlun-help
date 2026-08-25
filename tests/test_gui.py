# -*- coding: utf-8 -*-
"""GUI 冒烟测试：启动完整应用（窗口+托盘+服务），自检后自动退出。

注意：需要真实桌面会话；用 QTimer 在 8 秒后强制退出。
"""
import sys, io, threading, time
sys.path.insert(0, ".")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import httpx
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from app.main import App

results = {}

def main():
    app_obj = App()
    try:
        app_obj.start_server()
        results["server"] = f"http://127.0.0.1:{app_obj.port}"
        print(f"[OK] 本地服务就绪: {results['server']}")
    except Exception as e:
        results["server"] = f"FAIL: {e}"
        print(f"[FAIL] 服务启动: {e}")
        return 1

    qapp = QApplication(sys.argv)
    win = app_obj.window
    if win is None:
        app_obj.window = type("W", (), {"show": lambda s: None})()
        from app.main import MainWindow
        win = MainWindow(app_obj.store, app_obj.port)
        app_obj.window = win
    win.show()
    print("[OK] 窗口已创建:", win.windowTitle(), win.size().width(), "x", win.size().height())

    # 托盘
    app_obj.setup_tray(qapp)
    print("[OK] 托盘已创建")

    # 调度器
    app_obj.setup_scheduler()
    print("[OK] 调度器已初始化, 更新时间:", app_obj.store.get_config().get("update_time"))

    # 通过 HTTP 再验证一次 API 可达
    def check_api():
        try:
            r = httpx.get(f"http://127.0.0.1:{app_obj.port}/api/overview", timeout=3)
            ov = r.json()
            print(f"[OK] API 可达: 语段 {ov['phrases_total']} / 话题卡 {ov['cards_total']} / 热点 {ov['hotspots_total']}")
            results["api"] = "ok"
        except Exception as e:
            print(f"[FAIL] API 检查: {e}")
            results["api"] = f"FAIL: {e}"
        qapp.quit()

    QTimer.singleShot(3000, check_api)
    # 兜底：12 秒强制退出
    QTimer.singleShot(12000, qapp.quit)
    qapp.exec()

    print("\n=== GUI SMOKE TEST DONE ===")
    return 0 if results.get("api") == "ok" else 1

if __name__ == "__main__":
    sys.exit(main())
