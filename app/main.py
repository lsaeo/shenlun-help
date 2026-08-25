"""应用入口：PySide6 窗口 + 内嵌浏览器 + 系统托盘 + 每日调度。

启动流程：
  1. 建数据层（data/ + seed 初始化）
  2. 起 FastAPI 本地服务（127.0.0.1 随机端口，后台线程）
  3. 起 Qt 窗口，QWebEngineView 加载本地服务
  4. 挂托盘图标（打开主界面 / 立即生成今日 / 退出）
  5. 调度器：到点自动跑流水线；启动时补拉缺失天数
"""
from __future__ import annotations

import logging
import socket
import sys
import threading
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QAction, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon, QWidget
from PySide6.QtWebEngineWidgets import QWebEngineView

from .llm import DeepSeekClient
from .pipeline import Pipeline
from .server import create_app
from .store import JsonStore

log = logging.getLogger(__name__)

APP_NAME = "公考申论素材助手"
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
SEED_DIR = BASE_DIR / "seed"
LOG_FILE = BASE_DIR / "app.log"


def _setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _tray_icon() -> QIcon:
    """画一个简单的"文"字托盘图标，避免依赖图片资源。"""
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setPen(Qt.white)
    p.setBrush(Qt.darkBlue)
    p.drawRoundedRect(4, 4, 56, 56, 12, 12)
    p.setPen(Qt.white)
    font = p.font()
    font.setPointSize(26)
    font.setBold(True)
    p.setFont(font)
    p.drawText(pm.rect(), Qt.AlignCenter, "申")
    p.end()
    return QIcon(pm)


class MainWindow(QWidget):
    def __init__(self, store: JsonStore, port: int):
        super().__init__()
        self.store = store
        self.setWindowTitle(APP_NAME)
        self.resize(1280, 820)
        self.view = QWebEngineView(self)
        self.view.setUrl(f"http://127.0.0.1:{port}/")
        self.setCentralWidgetLayout()

    def setCentralWidgetLayout(self):
        from PySide6.QtWidgets import QVBoxLayout
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.view)

    def closeEvent(self, event):
        """点关闭按钮 → 隐藏到托盘而不是退出。"""
        event.ignore()
        self.hide()
        if self.parent() and hasattr(self.parent(), "notify"):
            self.parent().notify("已最小化到托盘", "程序仍在后台运行，每日自动更新不会中断。")
        else:
            log.info("窗口隐藏到托盘")


class App:
    def __init__(self):
        self.store = JsonStore(str(DATA_DIR), str(SEED_DIR))
        cfg = self.store.get_config()
        self.llm = DeepSeekClient(cfg.get("api_key", ""), cfg.get("api_base", ""), cfg.get("model", ""))
        self.pipeline = Pipeline(self.store, self.llm)
        self.port = _find_free_port()
        self.server_thread: threading.Thread | None = None
        self.window: MainWindow | None = None
        self.tray: QSystemTrayIcon | None = None
        self._pipe_lock = threading.Lock()

    # ---------- 本地服务 ----------
    def start_server(self):
        import uvicorn
        app = create_app(self.store, self.pipeline)
        config = uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="warning")
        server = uvicorn.Server(config)

        def _run():
            server.run()

        self.server_thread = threading.Thread(target=_run, daemon=True, name="fastapi")
        self.server_thread.start()
        # 等待服务就绪
        import time
        import httpx
        for _ in range(50):
            try:
                httpx.get(f"http://127.0.0.1:{self.port}/api/health", timeout=1)
                return
            except Exception:
                time.sleep(0.1)
        raise RuntimeError("本地服务启动失败")

    # ---------- 托盘 ----------
    def setup_tray(self, app: QApplication):
        tray = QSystemTrayIcon(_tray_icon(), app)
        tray.setToolTip(APP_NAME)
        menu = QMenu()
        act_open = QAction("打开主界面", menu)
        act_open.triggered.connect(self.show_window)
        act_run = QAction("立即生成今日", menu)
        act_run.triggered.connect(self.run_now)
        act_catch = QAction("补拉缺失天数", menu)
        act_catch.triggered.connect(self.catchup_now)
        act_quit = QAction("退出", menu)
        act_quit.triggered.connect(app.quit)
        menu.addAction(act_open)
        menu.addSeparator()
        menu.addAction(act_run)
        menu.addAction(act_catch)
        menu.addSeparator()
        menu.addAction(act_quit)
        tray.setContextMenu(menu)
        tray.activated.connect(lambda reason: self.show_window() if reason == QSystemTrayIcon.Trigger else None)
        tray.show()
        self.tray = tray

    def show_window(self):
        if self.window:
            self.window.showNormal()
            self.window.raise_()
            self.window.activateWindow()

    def notify(self, title: str, message: str):
        if self.tray and self.tray.isVisible():
            self.tray.showMessage(title, message, QSystemTrayIcon.Information, 6000)

    # ---------- 流水线触发（后台线程，避免卡 UI） ----------
    def run_now(self):
        if self.pipeline.running:
            self.notify("正在生成", "流水线已在运行，请稍候。")
            return
        self.notify("开始生成今日内容", "抓取新闻并调用 AI 生成草稿…")

        def _job():
            result = self.pipeline.run_daily()
            self._announce(result)

        threading.Thread(target=_job, daemon=True).start()

    def catchup_now(self):
        if self.pipeline.running:
            self.notify("正在生成", "流水线已在运行，请稍候。")
            return
        self.notify("开始补拉", "正在补拉缺失天数…")

        def _job():
            result = self.pipeline.run_catchup()
            self._announce(result, catchup=True)

        threading.Thread(target=_job, daemon=True).start()

    def _announce(self, result: dict, catchup: bool = False):
        if result.get("ok"):
            title = "补拉完成" if catchup else "今日内容已生成"
            msg = (f"热点 {result.get('hotspots', 0)} 条 / 话题卡 {result.get('cards', 0)} 张，"
                   f"已进入「待审核」，请到应用内确认入库。")
            if result.get("errors"):
                msg += f"\n（部分失败：{'；'.join(result['errors'][:2])}）"
        else:
            title = "生成失败"
            msg = "；".join(result.get("errors", ["未知错误"])[:3]) or "流水线异常"
        self.notify(title, msg)
        log.info("流水线结果: %s", result)

    # ---------- 调度：到点自动跑 + 启动补拉 ----------
    def setup_scheduler(self):
        timer = QTimer()
        timer.timeout.connect(self._check_schedule)
        timer.start(30_000)  # 每 30 秒检查一次
        self._scheduler_timer = timer
        self._checked_today = False

    def _check_schedule(self):
        if self._checked_today:
            return
        self._checked_today = True
        cfg = self.store.get_config()
        # 启动补拉
        last = cfg.get("last_update_date")
        from datetime import date
        today = date.today().isoformat()
        if last != today:
            self.catchup_now()
            return
        # 到点自动跑：检查时间是否 >= update_time
        now = datetime.now().strftime("%H:%M")
        if now >= cfg.get("update_time", "07:00"):
            self.run_now()

    def run(self) -> int:
        app = QApplication(sys.argv)
        app.setApplicationName(APP_NAME)
        app.setQuitOnLastWindowClosed(False)  # 关窗口不退出，保持托盘
        self.window = MainWindow(self.store, self.port)
        self.setup_tray(app)
        self.setup_scheduler()
        self.window.show()
        self.notify("已启动", "每日自动更新已就绪（默认 07:00）。")
        return app.exec()


def main():
    _setup_logging()
    log.info("===== 启动 %s =====", APP_NAME)
    app = App()
    try:
        app.start_server()
    except Exception as e:  # noqa: BLE001
        log.exception("本地服务启动失败")
        # 无 GUI 环境下用 QMessageBox 提示
        from PySide6.QtWidgets import QApplication, QMessageBox
        qapp = QApplication(sys.argv)
        QMessageBox.critical(None, APP_NAME, f"本地服务启动失败：{e}")
        return 1
    log.info("本地服务已就绪: http://127.0.0.1:%s", app.port)
    return app.run()


if __name__ == "__main__":
    sys.exit(main())
