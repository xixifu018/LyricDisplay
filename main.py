"""LX Music 桌面歌词显示 —— 入口"""

import sys
import os

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QIcon, QFont

from settings import load, save, get_api_url
from api_client import ApiClient
from main_window import LyricsWindow
from settings_dialog import UI_FONT_FAMILIES, UI_FONT_SIZE_PT
from single_instance import ensure_single_instance


def main():
    # 单实例限制：已有实例在跑就直接退出。
    # 放在最前面（QApplication 之前），这样第二实例连 Qt 都不用初始化，
    # 不会闪一下窗口，也不会去抢洛雪 API。
    if not ensure_single_instance():
        sys.exit(0)

    # 禁用 Qt 高 DPI 缩放（让窗口大小按像素计算）
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"

    app = QApplication(sys.argv)
    app.setApplicationName("LyricDisplay")
    app.setQuitOnLastWindowClosed(False)

    # 界面字体：不显式设置的话，Qt 5.15 在 Windows 上会用 DEFAULT_GUI_FONT，
    # 本机实测是「SimSun 12px」→ 宋体 7pt，小到看不清。
    from PyQt5.QtGui import QFontDatabase
    families = set(QFontDatabase().families())
    family = next((f for f in UI_FONT_FAMILIES if f in families), None)
    ui_font = QFont(family) if family else QFont()
    ui_font.setPointSize(UI_FONT_SIZE_PT)
    app.setFont(ui_font)

    # 图标
    icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lyrics-display-logo.png")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    # 加载配置
    settings = load()

    # 创建 API 客户端
    api_url = get_api_url(settings)
    client = ApiClient(api_url)

    # 创建歌词窗口
    window = LyricsWindow(settings)

    # 连接信号
    client.status_changed.connect(window.update_status)
    client.connection_changed.connect(window.set_api_connected)

    def on_window_closed():
        """窗口关闭时保存配置并退出"""
        client.stop()
        save(settings)
        app.quit()

    window.closed.connect(on_window_closed)

    # 启动
    client.start()
    window.show()
    window._do_dock()  # 初始吸附

    print(f"[LyricDisplay] 已启动，连接 {api_url}")
    print(f"[LyricDisplay] 吸附边: {settings.get('dock_edge', 'top')}")
    print(f"[LyricDisplay] 右键窗口可切换吸附边 / 调整字体 / 退出")

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
