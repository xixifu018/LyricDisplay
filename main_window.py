"""主窗口 —— 紧凑浮窗、屏幕边缘吸附、单行歌词 + 封面"""

import os
import subprocess
import webbrowser

from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QUrl
from PyQt5.QtWidgets import (
    QMainWindow, QMenu, QWidget,
    QGridLayout, QHBoxLayout, QGraphicsDropShadowEffect, QPushButton,
    QApplication, QSizePolicy,
)
from PyQt5.QtGui import QFont, QColor, QFontMetrics, QPixmap
from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkRequest

import threading

from lyrics_parser import parse_lrc, get_line_at, get_current_and_next
from spectrum_widget import SpectrumWidget
from audio_capture import AudioCapture
from flip_label import FlipLabel
from settings_dialog import SettingsDialog
from settings import save as save_settings
from round_cover import RoundCover

SNAP_THRESHOLD = 20

LXMUSIC_WEBSITE = "https://lxmusic.toside.cn/"
LXMUSIC_PATHS = [
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\lx-music-desktop\lx-music-desktop.exe"),
    os.path.expandvars(r"%ProgramFiles%\lx-music-desktop\lx-music-desktop.exe"),
    os.path.expandvars(r"%ProgramFiles(x86)%\lx-music-desktop\lx-music-desktop.exe"),
    r"D:\lx-music-desktop\lx-music-desktop.exe",
    r"C:\lx-music-desktop\lx-music-desktop.exe",
]


class LyricsWindow(QMainWindow):
    """歌词显示浮窗"""

    closed = pyqtSignal()

    def __init__(self, settings: dict):
        super().__init__()
        self._settings = settings
        self._lyric_lines = []
        self._current_lyric_text = ""
        self._next_lyric_text = ""
        self._display_mode = settings.get("display_mode", "single")
        self._last_raw_lyric = ""
        self._last_song_name = ""
        self._last_pic_url = ""
        self._cover_pixmap = QPixmap()
        self._dragging = False
        self._drag_pos = None
        self._docked = True
        self._dock_edge = settings.get("dock_edge", "top")
        self._local_progress = 0.0
        self._is_playing = False
        self._api_connected = False

        self._init_ui()
        self._apply_style()
        self._current_lyric_text = "启动中..."
        self._update_display()

    # ============================================================
    #  初始化
    # ============================================================

    def _init_ui(self):
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)

        central = QWidget(self)
        central.setObjectName("centralWidget")
        self.setCentralWidget(central)

        # 根布局：频谱底层 + 上层内容
        root = QGridLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 频谱背景
        self._spectrum = SpectrumWidget(central)
        self._spectrum.hide()

        # 上层：封面 + 歌词（水平排列）
        top_widget = QWidget(central)
        top_widget.setAttribute(Qt.WA_TranslucentBackground)
        top_row = QHBoxLayout(top_widget)
        top_row.setContentsMargins(4, 1, 10, 1)
        top_row.setSpacing(6)

        # 圆形封面（点击切换播放/暂停）
        self._cover = RoundCover(central)
        self._cover.setFixedSize(0, 0)
        self._cover.clicked.connect(self._toggle_play_pause)
        top_row.addWidget(self._cover)

        # 歌词标签
        self._lyric_label = FlipLabel(central)
        self._lyric_label.setMode(self._display_mode)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(12)
        shadow.setOffset(0, 0)
        shadow.setColor(QColor(0, 0, 0, 200))
        self._lyric_label.setGraphicsEffect(shadow)
        top_row.addWidget(self._lyric_label, 1)

        # 频谱在下，内容在上
        root.addWidget(self._spectrum, 0, 0)
        root.addWidget(top_widget, 0, 0)

        # 封面异步加载
        self._net = QNetworkAccessManager(self)
        self._net.finished.connect(self._on_cover_loaded)

        # 洛雪音乐按钮（悬停显示）
        self._lx_btn = QPushButton("♫")
        self._lx_btn.setFixedSize(16, 16)
        self._lx_btn.setFlat(True)
        self._lx_btn.setObjectName("lxBtn")
        self._lx_btn.setToolTip("打开洛雪音乐")
        self._lx_btn.clicked.connect(self._launch_lxmusic)
        self._lx_btn.hide()
        self._lx_btn.setParent(self)
        self._lx_btn.raise_()

        # 关闭按钮
        self._close_btn = QPushButton("✕")
        self._close_btn.setFixedSize(16, 16)
        self._close_btn.setFlat(True)
        self._close_btn.setObjectName("closeBtn")
        self._close_btn.clicked.connect(self.close)
        self._close_btn.hide()
        self._close_btn.setParent(self)
        self._close_btn.raise_()

        # 定时器
        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.timeout.connect(self._hide_buttons)

        self._progress_timer = QTimer(self)
        self._progress_timer.setInterval(200)
        self._progress_timer.timeout.connect(self._tick_progress)

        # 音频捕获
        self._audio = AudioCapture(self)
        self._audio.spectrum_data.connect(self._spectrum.set_levels)

        # 启动检测：3 秒后仍未连接则检查状态
        self._startup_timer = QTimer(self)
        self._startup_timer.setSingleShot(True)
        self._startup_timer.setInterval(3000)
        self._startup_timer.timeout.connect(self._check_startup_state)
        self._startup_timer.start()

    # ============================================================
    #  公共方法
    # ============================================================

    def update_status(self, data: dict):
        status = data.get("status", "stoped")
        self._is_playing = (status == "playing")
        name = data.get("name", "")
        singer = data.get("singer", "")
        progress = data.get("progress", 0.0)
        lyric_text = data.get("lyric", "")
        lyric_line_text = data.get("lyricLineText", "")

        self._local_progress = progress

        # 歌曲切换：清空残留歌词
        if name and name != self._last_song_name:
            self._last_song_name = name
            self._lyric_lines = []
            self._current_lyric_text = ""
            self._next_lyric_text = ""
            self._last_raw_lyric = ""

        if lyric_text and lyric_text != self._last_raw_lyric:
            self._lyric_lines = parse_lrc(lyric_text)
            self._last_raw_lyric = lyric_text

        if self._lyric_lines:
            current_text, next_text = get_current_and_next(self._lyric_lines, progress)
            if current_text != self._current_lyric_text or next_text != self._next_lyric_text:
                self._current_lyric_text = current_text
                self._next_lyric_text = next_text
            elif not current_text and lyric_line_text:
                self._current_lyric_text = lyric_line_text
                self._next_lyric_text = ""
        elif lyric_line_text:
            self._current_lyric_text = lyric_line_text
            self._next_lyric_text = ""

        if not self._current_lyric_text:
            if name:
                self._current_lyric_text = f"{name}  —  {singer}" if singer else name
            elif not self._api_connected:
                self._current_lyric_text = "启动中..."
            else:
                self._current_lyric_text = "等待播放..."

        # 封面图：URL 变化时异步加载
        pic_url = data.get("picUrl", "")
        if pic_url and pic_url != self._last_pic_url:
            self._last_pic_url = pic_url
            self._net.get(QNetworkRequest(QUrl(pic_url)))

        self._update_display()

        # 封面旋转：播放中旋转，暂停停止
        self._cover.setPlaying(self._is_playing)

        # 频谱 + 音频捕获：播放中 + 设置开启 → 启动
        show_spec = self._settings.get("show_spectrum", True)
        if self._is_playing and show_spec:
            self._spectrum.start()
            self._audio.start()
        else:
            self._spectrum.stop()
            self._audio.stop()

        if self._is_playing and self._lyric_lines:
            self._progress_timer.start()
        else:
            self._progress_timer.stop()

    def set_api_connected(self, connected: bool):
        self._api_connected = connected
        self._startup_timer.stop()
        if connected:
            if self._current_lyric_text in ("启动中...", "等待启动洛雪音乐...", "等待连接洛雪音乐API..."):
                self._current_lyric_text = "等待播放..."
                self._update_display()
        else:
            self._update_startup_text()

    def _check_startup_state(self):
        """启动超时，检查实际状态"""
        if not self._api_connected:
            self._update_startup_text()

    def _update_startup_text(self):
        running = self._is_lxmusic_running()
        text = "等待启动洛雪音乐..." if not running else "等待连接洛雪音乐API..."
        if self._current_lyric_text in ("启动中...", "等待播放...", "等待启动洛雪音乐...", "等待连接洛雪音乐API..."):
            self._current_lyric_text = text
            self._update_display()

    def _is_lxmusic_running(self):
        try:
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = subprocess.SW_HIDE
            result = subprocess.run(
                ['tasklist', '/FI', 'IMAGENAME eq lx-music-desktop.exe'],
                capture_output=True, text=True,
                startupinfo=si,
            )
            return 'lx-music-desktop.exe' in result.stdout
        except Exception:
            return False

    def showEvent(self, event):
        """首次显示时居中，然后吸附"""
        super().showEvent(event)
        self._center_horizontally()
        self._do_dock()

    def update_settings(self, settings: dict):
        self._settings = settings
        self._apply_style()
        self._update_display()
        if self._docked:
            self._clamp_x()

    # ============================================================
    #  内部
    # ============================================================

    def _tick_progress(self):
        if not self._is_playing or not self._lyric_lines:
            return
        self._local_progress += 0.2
        current_text, next_text = get_current_and_next(self._lyric_lines, self._local_progress)
        if current_text != self._current_lyric_text:
            self._current_lyric_text = current_text
            self._next_lyric_text = next_text
            self._update_display()
        elif next_text != self._next_lyric_text:
            self._next_lyric_text = next_text
            self._update_display()

    def _update_display(self):
        """刷新标签文字 + 封面尺寸"""
        font_size = self._settings.get("font_size", 8)
        text_color = self._settings.get("text_color", "#FFFFFF")
        win_width = self._settings.get("window_width", 600)

        font = QFont("Microsoft YaHei", font_size)
        font.setWeight(QFont.DemiBold)
        font.setStyleStrategy(QFont.PreferAntialias)
        self._lyric_label.setFont(font)
        self._lyric_label.setColor(text_color)

        fm = QFontMetrics(font)

        # 封面尺寸：最小值 40px
        line_h = fm.height() + 4
        text_h = (line_h * 2 + 2) if self._display_mode == "double" else (line_h + 2)
        cover_size = max(text_h, 40)

        # 更新封面（可配置开关）
        show_cover = self._settings.get("show_cover", True)
        has_cover = show_cover and self._cover_pixmap and not self._cover_pixmap.isNull()
        if has_cover:
            self._cover.setFixedSize(cover_size, cover_size)
            self._cover.setPixmap(self._cover_pixmap)
            self._cover.setEnabled(True)
        else:
            self._cover.setFixedSize(0, 0)
            self._cover.setEnabled(False)

        # 歌词可用宽度
        label_width = win_width - 24 - cover_size - 8 if has_cover else win_width - 24
        elided_current = fm.elidedText(self._current_lyric_text, Qt.ElideRight, max(10, label_width))
        elided_next = fm.elidedText(self._next_lyric_text, Qt.ElideRight, max(10, label_width))
        self._lyric_label.setTexts(elided_current, elided_next)

        total_h = max(text_h, cover_size + 2)
        self.resize(win_width, total_h)

    def _apply_style(self):
        bg_opacity = int(self._settings.get("bg_opacity", 0.45) * 255)
        bg = self._settings.get("bg_color", "#080808")
        bg = bg.lstrip("#")
        r, g, b = int(bg[0:2], 16), int(bg[2:4], 16), int(bg[4:6], 16)

        self.setStyleSheet(f"""
            #centralWidget {{
                background-color: rgba({r}, {g}, {b}, {bg_opacity});
                border-radius: 0px;
            }}
            #closeBtn, #lxBtn {{
                color: rgba(255, 255, 255, 100);
                background: rgba(255, 255, 255, 15);
                border: none;
                border-radius: 8px;
                font-size: 10px;
            }}
            #closeBtn:hover, #lxBtn:hover {{
                color: white;
                background: rgba(255, 255, 255, 50);
            }}
        """)

    # ============================================================
    #  吸附
    # ============================================================

    def _toggle_dock_edge(self):
        self._dock_edge = "bottom" if self._dock_edge == "top" else "top"
        self._settings["dock_edge"] = self._dock_edge
        self._docked = True
        self._do_dock()

    def _open_settings(self):
        """打开设置对话框"""
        dlg = SettingsDialog(self._settings, self)
        if dlg.exec_() == dlg.Accepted:
            self._settings.update(dlg.result())
            save_settings(self._settings)
            self._display_mode = self._settings.get("display_mode", "single")
            self._lyric_label.setMode(self._display_mode)
            self.update_settings(self._settings)
            # 封面/频谱开关立即生效
            if not self._settings.get("show_cover", True):
                self._cover.setPixmap(QPixmap())
            self._update_display()
            show_spec = self._settings.get("show_spectrum", True)
            if not show_spec:
                self._spectrum.stop()
                self._audio.stop()
            elif self._is_playing:
                self._spectrum.start()
                self._audio.start()

    def _do_dock(self):
        if not self._docked:
            return
        screen = QApplication.primaryScreen()
        if not screen:
            return
        geom = screen.availableGeometry()

        if self._dock_edge == "top":
            y = geom.top()
        else:
            y = geom.bottom() - self.height()

        self.move(self.x(), y)
        self._clamp_x()

    def _center_horizontally(self):
        """初始启动时水平居中"""
        screen = QApplication.primaryScreen()
        if not screen:
            return
        geom = screen.availableGeometry()
        x = geom.left() + (geom.width() - self.width()) // 2
        self.move(x, self.y())

    def _clamp_x(self):
        """限制 x 坐标不超出屏幕边界"""
        screen = QApplication.primaryScreen()
        if not screen:
            return
        geom = screen.availableGeometry()
        x = self.x()
        min_x = geom.left()
        max_x = geom.right() - self.width()
        if x < min_x:
            x = min_x
        elif x > max_x:
            x = max_x
        self.move(x, self.y())

    def _on_cover_loaded(self, reply):
        """封面图片下载完成"""
        err = reply.error()
        if err != reply.NoError:
            reply.deleteLater()
            return
        data = reply.readAll()
        pix = QPixmap()
        if pix.loadFromData(data):
            self._cover_pixmap = pix
            self._update_display()
        reply.deleteLater()

    def _toggle_play_pause(self):
        """点击封面 → 切换播放/暂停（通过 LX Music API）"""
        def do():
            try:
                import requests
                api = f"http://{self._settings['api_host']}:{self._settings['api_port']}"
                # 先查状态
                r = requests.get(f"{api}/status?filter=status", timeout=2)
                s = r.json().get("status", "")
                # 切换
                if s == "playing":
                    requests.get(f"{api}/pause", timeout=2)
                else:
                    requests.get(f"{api}/play", timeout=2)
            except Exception:
                pass
        threading.Thread(target=do, daemon=True).start()

    def _launch_lxmusic(self):
        """打开洛雪音乐：直接运行 exe"""
        exe_path = self._find_lxmusic_exe()
        if exe_path:
            try:
                si = subprocess.STARTUPINFO()
                si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                subprocess.Popen(
                    [exe_path],
                    startupinfo=si,
                    creationflags=subprocess.DETACHED_PROCESS,
                )
                return
            except Exception:
                pass

        webbrowser.open(LXMUSIC_WEBSITE)

    def _find_lxmusic_exe(self):
        """查找洛雪音乐可执行文件路径"""
        # 优先使用配置的安装目录
        cfg_path = self._settings.get("lxmusic_path", "")
        if cfg_path:
            cfg_exe = os.path.join(cfg_path, "lx-music-desktop.exe")
            if os.path.exists(cfg_exe):
                return cfg_exe
            # 也可能直接给的 exe 路径
            if os.path.exists(cfg_path) and cfg_path.endswith(".exe"):
                return cfg_path

        # 常见安装路径
        for path in LXMUSIC_PATHS:
            if os.path.exists(path):
                return path
        # where 命令
        try:
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            result = subprocess.run(
                ['where', 'lx-music-desktop'],
                capture_output=True, text=True, timeout=3,
                startupinfo=si,
            )
            if result.returncode == 0:
                p = result.stdout.strip().split('\n')[0].strip()
                if os.path.exists(p):
                    return p
        except Exception:
            pass
        return None

    def _layout_buttons(self):
        self._close_btn.move(self.width() - 22, (self.height() - 16) // 2)
        self._lx_btn.move(self.width() - 44, (self.height() - 16) // 2)

    # ============================================================
    #  事件
    # ============================================================

    def enterEvent(self, event):
        self._close_btn.show()
        self._lx_btn.show()
        self._hover_timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover_timer.start(1000)
        super().leaveEvent(event)

    def _hide_buttons(self):
        self._close_btn.hide()
        self._lx_btn.hide()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._drag_pos = event.globalPos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging and self._drag_pos:
            delta = event.globalPos() - self._drag_pos
            new_pos = self.pos() + delta
            self.move(new_pos)
            self._drag_pos = event.globalPos()

            screen = QApplication.primaryScreen()
            if screen:
                geom = screen.availableGeometry()
                dy_top = abs(new_pos.y() - geom.top())
                dy_bottom = abs(new_pos.y() - (geom.bottom() - self.height()))
                if min(dy_top, dy_bottom) > SNAP_THRESHOLD * 4:
                    self._docked = False

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = False
            self._drag_pos = None

            screen = QApplication.primaryScreen()
            if screen:
                geom = screen.availableGeometry()
                pos = self.pos()
                h = self.height()

                dy_top = abs(pos.y() - geom.top())
                dy_bottom = abs(pos.y() - (geom.bottom() - h))

                if dy_top < SNAP_THRESHOLD:
                    self._dock_edge = "top"
                    self._docked = True
                    self.move(pos.x(), geom.top())
                    self._clamp_x()
                elif dy_bottom < SNAP_THRESHOLD:
                    self._dock_edge = "bottom"
                    self._docked = True
                    self.move(pos.x(), geom.bottom() - h)
                    self._clamp_x()

        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._toggle_dock_edge()
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background: #1e1e1e;
                color: #bbb;
                border: 1px solid #3a3a3a;
                border-radius: 6px;
                padding: 6px;
                font-size: 13px;
            }
            QMenu::item {
                padding: 7px 28px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background: #3a3a3a;
                color: #fff;
            }
        """)

        toggle_action = menu.addAction(
            "吸附到底部" if self._dock_edge == "top" else "吸附到顶部"
        )
        mode_action = menu.addAction(
            "双行歌词" if self._display_mode == "single" else "单行歌词"
        )
        font_bigger = menu.addAction("字号 +")
        font_smaller = menu.addAction("字号 −")
        menu.addSeparator()
        lx_action = menu.addAction("打开洛雪音乐")
        settings_action = menu.addAction("设置...")
        menu.addSeparator()
        exit_action = menu.addAction("退出")

        action = menu.exec_(event.globalPos())

        if action == toggle_action:
            self._toggle_dock_edge()
        elif action == mode_action:
            self._display_mode = "double" if self._display_mode == "single" else "single"
            self._settings["display_mode"] = self._display_mode
            self._lyric_label.setMode(self._display_mode)
            self._update_display()
            save_settings(self._settings)
        elif action == font_bigger:
            self._settings["font_size"] = min(48, self._settings.get("font_size", 12) + 1)
            self._update_display()
            save_settings(self._settings)
        elif action == font_smaller:
            self._settings["font_size"] = max(6, self._settings.get("font_size", 12) - 1)
            self._update_display()
            save_settings(self._settings)
        elif action == lx_action:
            self._launch_lxmusic()
        elif action == settings_action:
            self._open_settings()
        elif action == exit_action:
            self.close()

    def resizeEvent(self, event):
        self._layout_buttons()
        super().resizeEvent(event)

    def closeEvent(self, event):
        self._progress_timer.stop()
        self._hover_timer.stop()
        self._startup_timer.stop()
        self._audio.stop()
        self._spectrum.stop()
        self.closed.emit()
        # 强制退出，避免子线程阻塞关闭流程
        import os as _os
        QTimer.singleShot(500, lambda: _os._exit(0))
        super().closeEvent(event)
