"""设置对话框 —— 字号 / 颜色 / 透明度"""

import webbrowser

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QSlider, QSpinBox, QColorDialog,
    QGroupBox, QWidget, QCheckBox, QLineEdit, QFileDialog,
)
from PyQt5.QtGui import QColor

LXMUSIC_WEBSITE = "https://lxmusic.toside.cn/"


TEXT_COLORS = [
    "#FFFFFF", "#FFD700", "#00FF88", "#00D4FF",
    "#FF6B9D", "#FF9500", "#C0C0C0", "#B8A0FF",
]

BG_COLORS = [
    "#000000", "#0A0A0A", "#111111", "#1A1A2E",
    "#16213E", "#0F0F0F", "#1B1B2F", "#0D1117",
]

OPACITY_STEPS = [10, 20, 30, 40, 50, 60, 75, 90]


class _ColorPicker(QWidget):
    """一排圆形颜色按钮"""

    def __init__(self, colors: list[str], current: str, is_bg: bool, parent=None):
        super().__init__(parent)
        self._colors = colors
        self._selected = current
        self._is_bg = is_bg
        self._btns: list[QPushButton] = []

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(6)

        for c in colors:
            btn = QPushButton()
            btn.setFixedSize(24, 24)
            border = "2px solid #fff" if c == current else "1px solid #555"
            btn.setStyleSheet(
                f"background: {c}; border-radius: 12px; border: {border};"
            )
            btn.clicked.connect(lambda _, cl=c: self._select(cl))
            layout.addWidget(btn)
            self._btns.append((btn, c))

        # 自定义...
        picker = QPushButton("…")
        picker.setFixedSize(24, 24)
        picker.setStyleSheet(
            "color: #aaa; background: #222; border: 1px solid #555; "
            "border-radius: 12px; font-size: 14px; font-weight: bold;"
        )
        picker.clicked.connect(self._pick)
        layout.addWidget(picker)

        layout.addStretch()

    @property
    def selected(self) -> str:
        return self._selected

    def _select(self, color: str):
        self._selected = color
        for btn, c in self._btns:
            border = "2px solid #fff" if c == color else "1px solid #555"
            btn.setStyleSheet(
                f"background: {c}; border-radius: 12px; border: {border};"
            )

    def _pick(self):
        c = QColorDialog.getColor(QColor(self._selected), self, "选择颜色")
        if c.isValid():
            self._select(c.name())


class SettingsDialog(QDialog):
    """设置弹窗"""

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._result = dict(settings)
        self._dragging = False
        self._drag_pos = None

        self.setWindowTitle("歌词设置")
        self.setWindowFlags(Qt.Tool | Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)
        self.setFixedSize(340, 600)

        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(12)

        # ---- 标题栏 ----
        title_row = QHBoxLayout()
        title = QLabel("⚙ 歌词显示设置")
        title.setStyleSheet("color: #eee; font-size: 14px; font-weight: bold;")
        title_row.addWidget(title)
        title_row.addStretch()
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(22, 22)
        close_btn.setStyleSheet(
            "color: #888; background: transparent; border: none; font-size: 14px;"
        )
        close_btn.clicked.connect(self.accept)
        title_row.addWidget(close_btn)
        layout.addLayout(title_row)

        # ---- 字号 ----
        size_row = QHBoxLayout()
        size_row.addWidget(QLabel("字号"))
        size_row.addStretch()
        spin = QSpinBox()
        spin.setRange(6, 48)
        spin.setValue(self._result.get("font_size", 8))
        spin.setFixedWidth(60)
        spin.valueChanged.connect(lambda v: self._update("font_size", v))
        size_row.addWidget(spin)
        layout.addLayout(size_row)

        # ---- 文字颜色 ----
        layout.addWidget(QLabel("文字颜色"))
        text_color = self._result.get("text_color", "#FFFFFF")
        self._text_picker = _ColorPicker(TEXT_COLORS, text_color, False, self)
        layout.addWidget(self._text_picker)

        # ---- 背景颜色 ----
        layout.addWidget(QLabel("背景颜色"))
        bg_color = self._result.get("bg_color", "#000000")
        self._bg_picker = _ColorPicker(BG_COLORS, bg_color, True, self)
        layout.addWidget(self._bg_picker)

        # ---- 背景透明度 ----
        layout.addWidget(QLabel("背景透明度"))
        opacity_row = QHBoxLayout()

        self._slider = QSlider(Qt.Horizontal)
        self._slider.setRange(5, 95)
        self._slider.setValue(int(self._result.get("bg_opacity", 0.45) * 100))
        self._slider.valueChanged.connect(
            lambda v: self._update("bg_opacity", v / 100.0)
        )

        self._pct_label = QLabel(f"{int(self._result.get('bg_opacity', 0.45) * 100)}%")
        self._pct_label.setFixedWidth(36)
        self._pct_label.setAlignment(Qt.AlignCenter)
        self._slider.valueChanged.connect(lambda v: self._pct_label.setText(f"{v}%"))

        opacity_row.addWidget(QLabel("透"))
        opacity_row.addWidget(self._slider)
        opacity_row.addWidget(QLabel("实"))
        opacity_row.addWidget(self._pct_label)
        layout.addLayout(opacity_row)

        # ---- 快速不透明度 ----
        quick_row = QHBoxLayout()
        quick_row.setSpacing(4)
        for v in OPACITY_STEPS:
            btn = QPushButton(f"{v}%")
            btn.setFixedSize(36, 22)
            btn.clicked.connect(lambda _, val=v: self._slider.setValue(val))
            quick_row.addWidget(btn)
        quick_row.addStretch()
        layout.addLayout(quick_row)

        # ---- 显示频谱 ----
        self._cover_check = QCheckBox("显示歌曲封面")
        self._cover_check.setChecked(self._result.get("show_cover", True))
        self._cover_check.toggled.connect(
            lambda v: self._update("show_cover", v)
        )
        layout.addWidget(self._cover_check)

        self._spectrum_check = QCheckBox("显示频谱背景")
        self._spectrum_check.setChecked(self._result.get("show_spectrum", True))
        self._spectrum_check.toggled.connect(
            lambda v: self._update("show_spectrum", v)
        )
        layout.addWidget(self._spectrum_check)

        # ---- 洛雪音乐路径 ----
        lx_label = QLabel("洛雪音乐安装目录")
        layout.addWidget(lx_label)
        lx_row = QHBoxLayout()
        self._lx_path_edit = QLineEdit()
        self._lx_path_edit.setText(self._result.get("lxmusic_path", ""))
        self._lx_path_edit.setPlaceholderText("留空=自动检测")
        self._lx_path_edit.textChanged.connect(
            lambda v: self._update("lxmusic_path", v)
        )
        lx_row.addWidget(self._lx_path_edit)
        browse_btn = QPushButton("...")
        browse_btn.setFixedWidth(32)
        browse_btn.clicked.connect(self._browse_lxmusic)
        lx_row.addWidget(browse_btn)
        layout.addLayout(lx_row)

        # ---- 官网链接 ----
        web_btn = QPushButton("洛雪音乐官网 →")
        web_btn.setObjectName("webBtn")
        web_btn.setCursor(Qt.PointingHandCursor)
        web_btn.clicked.connect(lambda: webbrowser.open(LXMUSIC_WEBSITE))
        layout.addWidget(web_btn)

        # ---- 使用说明 ----
        help_group = QGroupBox("使用说明")
        help_layout = QVBoxLayout(help_group)
        tips = [
            "双击窗口 → 切换吸附边（顶部/底部）",
            "点击封面 → 播放/暂停",
            "悬停 ♫ → 打开洛雪音乐",
            "右键菜单 → 更多快捷操作",
            "拖拽窗口 → 靠近边缘自动吸附",
        ]
        for t in tips:
            tip_label = QLabel(t)
            tip_label.setStyleSheet("color: #888; font-size: 11px; padding: 1px 0;")
            help_layout.addWidget(tip_label)
        layout.addWidget(help_group)

        layout.addStretch()

        self.setStyleSheet("""
            QDialog { background-color: #000; border: 1px solid #333; border-radius: 8px; }
            QGroupBox {
                color: #aaa; font-size: 12px; border: 1px solid #333;
                border-radius: 6px; margin-top: 8px; padding-top: 16px;
            }
            QGroupBox::title {
                color: #ccc; subcontrol-origin: margin; left: 10px; padding: 0 4px;
            }
            QLabel { color: #aaa; font-size: 12px; background: transparent; }
            QSpinBox {
                background: #111; color: #ddd; border: 1px solid #333;
                border-radius: 4px; padding: 3px 6px; font-size: 13px;
            }
            QSpinBox:hover { border-color: #555; }
            QSlider::groove:horizontal {
                height: 5px; background: #222; border-radius: 2px;
            }
            QSlider::handle:horizontal {
                width: 12px; height: 12px; margin: -3px 0;
                background: #777; border-radius: 6px;
            }
            QSlider::handle:horizontal:hover { background: #aaa; }
            QCheckBox { color: #aaa; font-size: 12px; spacing: 6px; }
            QCheckBox::indicator { width: 14px; height: 14px; }
            QPushButton {
                color: #999; background: #111; border: 1px solid #333;
                border-radius: 3px; font-size: 11px; padding: 2px 4px;
            }
            QLineEdit {
                color: #ddd; background: #111; border: 1px solid #333;
                border-radius: 4px; padding: 4px 6px; font-size: 11px;
            }
            QLineEdit:focus { border-color: #555; }
            QPushButton:hover { background: #333; color: #fff; }
            #webBtn {
                color: #6af; background: transparent; border: 1px solid #333;
                font-size: 12px; padding: 5px;
            }
            #webBtn:hover { background: #1a2a3a; color: #8cf; }
        """)

    def showEvent(self, event):
        """显示时定位到父窗口旁边，避免遮挡"""
        super().showEvent(event)
        p = self.parent()
        if p:
            pg = p.geometry()
            screen = p.screen()
            if screen:
                sg = screen.availableGeometry()
                # 优先放父窗口右侧
                x = pg.right() + 8
                y = pg.top()
                # 右侧不够放左边
                if x + self.width() > sg.right():
                    x = pg.left() - self.width() - 8
                # 左右都不够就放下方
                if x < sg.left():
                    x = pg.left()
                    y = pg.bottom() + 8
                # 确保不超出屏幕
                if y + self.height() > sg.bottom():
                    y = sg.bottom() - self.height()
                if x < sg.left():
                    x = sg.left()
                self.move(x, y)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._drag_pos = event.globalPos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging and self._drag_pos:
            self.move(self.pos() + event.globalPos() - self._drag_pos)
            self._drag_pos = event.globalPos()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._dragging = False
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def result(self) -> dict:
        return self._result

    def accept(self):
        self._result["text_color"] = self._text_picker.selected
        self._result["bg_color"] = self._bg_picker.selected
        super().accept()

    def _browse_lxmusic(self):
        path = QFileDialog.getExistingDirectory(self, "选择洛雪音乐安装目录")
        if path:
            self._lx_path_edit.setText(path)
            self._result["lxmusic_path"] = path

    def _update(self, key, value):
        self._result[key] = value
