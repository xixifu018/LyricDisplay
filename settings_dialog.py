"""设置对话框 —— 字号 / 颜色 / 透明度 / 窗口锁定"""

import webbrowser

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QSlider, QSpinBox, QColorDialog,
    QGroupBox, QWidget, QCheckBox, QLineEdit, QFileDialog,
    QKeySequenceEdit, QTabWidget, QTabBar, QSizePolicy, QApplication,
)
from PyQt5.QtGui import (
    QColor, QKeySequence, QFont, QFontDatabase, QPalette, QFontMetrics,
)

import hotkey

LXMUSIC_WEBSITE = "https://lxmusic.toside.cn/"

# 界面字体必须显式指定，不能靠系统默认。
# Qt 5.15 在 Windows 上把 DEFAULT_GUI_FONT 当成默认 UI 字体，而本机的
# DEFAULT_GUI_FONT 是「SimSun 12px」，于是整个对话框被渲染成宋体 7pt（≈9px），
# 小到看不清 —— 尽管系统 MessageFont 其实是「Microsoft YaHei UI」。
# 这里优先用系统 UI 字体，逐个回退。
UI_FONT_FAMILIES = ["Microsoft YaHei UI", "Microsoft YaHei", "微软雅黑", "SimHei", "SimSun"]
UI_FONT_SIZE_PT = 10          # 10pt ≈ 13px，比原来的 7pt 大一圈
HINT_FONT_PX = 11             # 说明小字（比正文小一号；用 px 不用 pt，便于精确控制）

LABEL_FG = "#dddddd"          # 标签正文
LABEL_FG_DIM = "#999999"      # 说明性小字
FIELD_BG = "#1a1a1a"          # 输入类控件底色
HEIGHT_SLACK = 24             # 定高时给最高那页留的余量（px）
SPIN_WIDTH = 88               # 两个数字框统一宽度（px）


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

    def __init__(self, settings: dict, parent=None, own_hotkeys=None):
        super().__init__(parent)
        self._settings = settings
        self._result = dict(settings)
        self._dragging = False
        self._drag_pos = None
        # 用户点了「立即锁定窗口」：交给主窗口在对话框关闭后再执行
        self.lock_request = False
        # 主窗口当前**真正注册成功**的热键：用来把"本程序自己的热键"
        # 从"被别人占用"里区分出来（否则打开面板会看到两个键都报占用）
        self._own_hotkeys = list(own_hotkeys or [])

        self.setWindowTitle("歌词设置")
        self.setWindowFlags(Qt.Tool | Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)
        # 分页后高度只需容纳**最高的一页**，不是三页之和。
        # 这里不写死数值：先按各页的 sizeHint 量出所需高度（见 _fit_height），
        # 避免手填魔数在换字体/DPI 后把"使用说明"最后一行裁掉。
        self.setFixedSize(340, 400)      # 占位，紧接着由 _fit_height 覆盖

        self._apply_font()
        self._apply_dark_palette()
        self._init_ui()
        # 统一给每个控件挂上自己的样式：不依赖对话框样式表的层叠，
        # 也就不会因为某个全局规则被解析/继承的方式不同而丢样式。
        self._apply_widget_styles()
        self._fit_height()

    def _fit_height(self):
        """按最高的那一页定对话框高度（切换页签时窗口大小不变）

        只靠 page.sizeHint() 是不够的：对话框高度里还要加上标题栏、边距和
        **页签栏的真实高度**（这个值随样式变化，量出来比猜准）。做法是先用
        保守初值设一次尺寸，量出"页签栏占了多少"，再按 sizeHint 重算并迭代
        几次直到不再有页面被裁剪。
        """
        current = self._tabs.currentIndex()
        screen = QApplication.primaryScreen()
        limit = screen.availableGeometry().height() - 40 if screen else 9999

        needed = 0
        for i in range(self._tabs.count()):
            self._tabs.setCurrentIndex(i)
            page = self._tabs.widget(i)
            page.adjustSize()
            needed = max(needed, page.sizeHint().height())
        self._tabs.setCurrentIndex(current)

        # 初值给足，便于量出页签栏与边距的真实开销
        self.setFixedSize(340, min(max(320, needed + 200), limit))
        self.layout().activate()

        for _ in range(4):
            chrome = self.height() - self._tabs.height()
            target = int(needed + max(0, chrome) + HEIGHT_SLACK)
            target = max(320, min(target, limit))
            if target == self.height():
                break
            self.setFixedSize(340, target)
            self.layout().activate()

        # 兜底：若仍有页面被裁，按缺口补齐
        for _ in range(3):
            shortfall = 0
            for i in range(self._tabs.count()):
                self._tabs.setCurrentIndex(i)
                self.layout().activate()
                page = self._tabs.widget(i)
                shortfall = max(shortfall, page.sizeHint().height() - page.height())
            self._tabs.setCurrentIndex(current)
            if shortfall <= 0:
                break
            self.setFixedSize(340, min(self.height() + shortfall + 4, limit))
            self.layout().activate()

        # ⚠️ 再兜一层：wordWrap 标签在**实际宽度**下可能比 sizeHint 更高。
        # sizeHint 按它自己认为的宽度算，而对话框宽度固定为 340 → 实际更窄、
        # 折行更多，于是 sizeHint 低估高度，上面的 shortfall 判不出来，
        # 最后一行被裁（用户实际遇到："置顶与置底说明显示不全"）。
        # 这里直接问每个标签"在它当前的宽度下需要多高"，按真实缺口补。
        for _ in range(3):
            deficit = 0
            for i in range(self._tabs.count()):
                self._tabs.setCurrentIndex(i)
                self.layout().activate()
                page = self._tabs.widget(i)
                for lbl in page.findChildren(QLabel):
                    if not lbl.wordWrap():
                        continue
                    need = (lbl.heightForWidth(lbl.width())
                            if lbl.hasHeightForWidth() else lbl.sizeHint().height())
                    deficit = max(deficit, need - lbl.height())
            self._tabs.setCurrentIndex(current)
            if deficit <= 0:
                break
            self.setFixedSize(340, min(self.height() + deficit + 4, limit))
            self.layout().activate()

    # ============================================================
    #  字体与调色板
    # ============================================================

    def _apply_font(self):
        """显式设定界面字体，避免落到宋体 7pt"""
        available = set(QFontDatabase().families())
        family = next((f for f in UI_FONT_FAMILIES if f in available), None)
        font = QFont(family) if family else QFont()
        font.setPointSize(UI_FONT_SIZE_PT)
        self.setFont(font)
        self._ui_font_family = font.family()

    def _label(self, text: str) -> QLabel:
        """带显式字色的标签

        之前只靠对话框样式表里的 QLabel 规则给颜色。这里改成每个标签自己
        带样式：只要样式表里那条规则因任何原因没生效，标签就会去问调色板，
        一旦解析出纯黑就在黑底上完全看不见（用户遇到过整页标签消失）。
        """
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color: {LABEL_FG}; background: transparent;")
        return lbl

    def _hint_label(self, text: str) -> QLabel:
        """说明性小字：换行 + 比正文小一号 + 暗一档

        ⚠️ `keepHintStyle` 属性是给 `_apply_widget_styles()` 看的：
        那里会给所有 QLabel 统一挂 `color` 样式，**会把这里的 font-size 抹掉**，
        于是说明文字被放大到正文大小，在固定 340px 宽的对话框里撑高后被裁掉
        （用户实际遇到："说明文字显示不全"）。
        """
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setProperty("keepHintStyle", True)
        lbl.setStyleSheet(
            f"color: {LABEL_FG_DIM}; background: transparent;"
            f" font-size: {HINT_FONT_PX}px;"
        )
        return lbl

    def _dim_label(self, text: str) -> QLabel:
        """说明性小字（比正文暗一档）—— 与 `_hint_label` 同一套样式"""
        return self._hint_label(text)

    def _apply_widget_styles(self):
        """逐控件显式挂样式（字体、字色、底色都不再依赖层叠）

        注意：字体/字色一律用模块常量，不要用局部变量 ——
        这些字符串曾经被误留在 _size_spinbox 里，引用了不存在的局部名而报错。
        """
        for lbl in self.findChildren(QLabel):
            # 说明小字（`_hint_label`）自己带 font-size，这里不能覆盖：
            # 一覆盖就回到正文大小，窄对话框里会撑高并被裁。
            if lbl.property("keepHintStyle"):
                continue
            lbl.setStyleSheet(f"color: {LABEL_FG}; background: transparent;")

        for box in self.findChildren(QCheckBox):
            box.setStyleSheet(
                f"color: {LABEL_FG}; font-size: {UI_FONT_SIZE_PT}pt; spacing: 6px;"
            )

        for box in self.findChildren(QGroupBox):
            box.setStyleSheet(
                f"QGroupBox {{ color: {LABEL_FG}; font-size: {UI_FONT_SIZE_PT}pt;"
                f" border: 1px solid #333; border-radius: 6px;"
                f" margin-top: 8px; padding-top: 16px; }}"
                f"QGroupBox::title {{ color: #ddd; subcontrol-origin: margin;"
                f" left: 10px; padding: 0 4px; }}"
            )

        # 只改 QSpinBox 本体，**绝不碰 up-button/down-button/up-arrow/down-arrow**。
        # 实测（见下方注释）：一旦给按钮设了自定义样式，Qt 就不再画原生的三角指示，
        # 而 QSS 里用 CSS 的 border 三角技巧（border-left/right transparent +
        # border-bottom 实色）在 Qt 里**不生效** —— 结果就是两个实心方块。
        # 用原生箭头既有正确的三角，悬停高亮也由系统提供。
        spin_style = (
            f"QSpinBox {{ color: #e6e6e6; background: {FIELD_BG};"
            f" border: 1px solid #3a3a3a; border-radius: 4px;"
            f" padding: 3px 4px 3px 6px; font-size: {UI_FONT_SIZE_PT}pt; }}"
            f"QSpinBox:hover {{ border-color: #555; }}"
            f"QSpinBox:focus {{ border-color: #666; }}"
        )
        for spin in self.findChildren(QSpinBox):
            spin.setStyleSheet(spin_style)
            self._size_spinbox(spin)

        line_style = (
            f"QLineEdit {{ color: #e6e6e6; background: {FIELD_BG};"
            f" border: 1px solid #3a3a3a; border-radius: 4px;"
            f" padding: 4px 6px; font-size: {UI_FONT_SIZE_PT}pt; }}"
            f"QLineEdit:focus {{ border-color: #666; }}"
        )
        for edit in self.findChildren(QLineEdit):
            edit.setStyleSheet(line_style)

        slider_style = (
            "QSlider::groove:horizontal { height: 6px; background: #2a2a2a;"
            " border-radius: 3px; }"
            "QSlider::handle:horizontal { width: 12px; height: 12px; margin: -4px 0;"
            " background: #ccc; border-radius: 6px; }"
            "QSlider::handle:horizontal:hover { background: #fff; }"
        )
        for slider in self.findChildren(QSlider):
            slider.setStyleSheet(slider_style)

        for btn in self.findChildren(QPushButton):
            # 这些按钮自带样式，不能被统一涂改：
            #   _ColorPicker 的圆角色块（彩色 + 圆角，涂掉就成黑方块）
            #   pctBtn 百分比预设（故意用较小字号，否则一排放不下被裁字）
            #   webBtn / lockNowBtn / closeBtn 由 objectName 样式提供
            if btn.objectName() in ("webBtn", "lockNowBtn", "closeBtn", "pctBtn"):
                continue
            if btn.styleSheet():
                continue
            btn.setStyleSheet(
                f"QPushButton {{ color: {LABEL_FG}; background: {FIELD_BG};"
                f" border: 1px solid #3a3a3a; border-radius: 3px;"
                f" padding: 3px 4px; font-size: {UI_FONT_SIZE_PT}pt; }}"
                f"QPushButton:hover {{ background: #2a2a2a; color: #fff; }}"
            )

        for tab_bar in self._tabs.findChildren(QTabBar):
            tab_bar.setStyleSheet(
                f"QTabBar::tab {{ color: {LABEL_FG_DIM}; background: transparent;"
                f" border: none; padding: 8px 18px; margin-right: 2px;"
                f" font-size: {UI_FONT_SIZE_PT}pt; border-top-left-radius: 5px;"
                f" border-top-right-radius: 5px; }}"
                f"QTabBar::tab:hover {{ color: #ddd; background: #141414; }}"
                f"QTabBar::tab:selected {{ color: #fff; background: #1c1c1c;"
                f" font-weight: bold; }}"
            )

        # 热键状态标签统一由 `_hint_label` / `_set_status` 管样式（11px 小字）。
        # 这里**不要再单独给它们写死字号**：曾只对 lock/unlock 两个写死 10pt，
        # 后加的 top/bottom 漏了，于是四个状态行字号不一致。

        # 标题：上面的统一循环会把它也盖成普通标签，这里补回来
        title = self.findChild(QLabel, "dlgTitle")
        if title is not None:
            title.setStyleSheet("color: #eee; font-size: 15px; font-weight: bold;"
                                " background: transparent;")

    @staticmethod
    def _size_spinbox(spin: QSpinBox, width: int = SPIN_WIDTH, gap: int = 12):
        """统一为固定宽度，并保证"文字 + 箭头 + 余量"放得下

        这里踩过两个坑，都写下来避免以后重犯：
        1. 原来按内容算宽度，QSS 的 padding 加二位数后缀把"10 秒"撑到 226px，
           在 340px 宽的对话框里明显失衡 —— 改成两个框统一固定宽度。
        2. **绝不能用 subControlRect 去量箭头列**。它依赖控件*当前*矩形：
           实测同一份样式下，`SC_SpinBoxUp` 对宽框返回 160、对窄框返回 16，
           于是形成循环依赖 —— 框越宽"箭头列"越大，max(width, text+arrow+gap)
           越设越宽（秒框因此被推到 214px）。
        现在只用"控件在**无约束**下的固有宽度"（sizeHint），它是样式+字体决定的
        常量，不随控件当前尺寸变化。
        """
        fm = QFontMetrics(spin.font())
        texts = [spin.text(),
                 f"{spin.prefix()}{spin.maximum()}{spin.suffix()}",
                 f"{spin.prefix()}{spin.minimum()}{spin.suffix()}"]
        text_w = max(fm.boundingRect(t).width() for t in texts)

        # 固有宽度：样式 + 字体决定，与控件当前尺寸无关
        intrinsic = spin.sizeHint().width()
        if intrinsic <= 0:
            intrinsic = 80
        # 箭头列占固有宽度里的多少，按经验留出足够空间（原生箭头约 16~20px）
        arrow_w = max(20, intrinsic - text_w - 12)

        target = max(width, text_w + arrow_w + gap)
        spin.setFixedWidth(target)

    def _apply_dark_palette(self):
        """显式设定深色调色板

        否则未在样式表里写明颜色的控件会去问系统调色板：
        本机实测外观页的 QLabel 解析出 WindowText=(0,0,0) 纯黑，
        在黑色底上就是"看不见字"。这里把深浅两套角色都钉死，
        任何控件都不再依赖会话的浅色/深色主题。
        """
        pal = QPalette()
        pal.setColor(QPalette.Window, QColor("#000000"))
        pal.setColor(QPalette.WindowText, QColor("#cccccc"))
        pal.setColor(QPalette.Base, QColor("#111111"))
        pal.setColor(QPalette.AlternateBase, QColor("#1a1a1a"))
        pal.setColor(QPalette.Text, QColor("#dddddd"))
        pal.setColor(QPalette.Button, QColor("#111111"))
        pal.setColor(QPalette.ButtonText, QColor("#aaaaaa"))
        pal.setColor(QPalette.BrightText, QColor("#ffffff"))
        pal.setColor(QPalette.Highlight, QColor("#3a6ea5"))
        pal.setColor(QPalette.HighlightedText, QColor("#ffffff"))
        pal.setColor(QPalette.ToolTipBase, QColor("#1e1e1e"))
        pal.setColor(QPalette.ToolTipText, QColor("#dddddd"))
        pal.setColor(QPalette.Disabled, QPalette.WindowText, QColor("#666666"))
        pal.setColor(QPalette.Disabled, QPalette.Text, QColor("#666666"))
        pal.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#666666"))
        self.setPalette(pal)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 14)
        layout.setSpacing(10)

        # ---- 标题栏 ----
        title_row = QHBoxLayout()
        title = QLabel("⚙ 歌词显示设置")
        title.setObjectName("dlgTitle")
        title_row.addWidget(title)
        title_row.addStretch()
        close_btn = QPushButton("✕")
        close_btn.setObjectName("closeBtn")
        close_btn.setFixedSize(22, 22)
        # 自带样式：_apply_widget_styles 会统一给按钮挂样式，
        # 靠那里的 objectName 例外分支容易漏（曾经就漏过），这里直接写死
        close_btn.setStyleSheet(
            "color: #999; background: transparent; border: none; font-size: 15px;"
        )
        close_btn.clicked.connect(self.accept)
        title_row.addWidget(close_btn)
        layout.addLayout(title_row)

        # ---- 三个功能分页（原先是单页竖排，太高）----
        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_appearance_tab(), "外观")
        self._tabs.addTab(self._build_function_tab(), "功能")
        self._tabs.addTab(self._build_lock_tab(), "锁定")
        # 页面不纵向拉伸：否则每页会被拉满到对话框高度，
        # 于是 minimumSizeHint 反过来受当前尺寸影响，高度就没法客观测量了。
        for i in range(self._tabs.count()):
            page = self._tabs.widget(i)
            page.setSizePolicy(page.sizePolicy().horizontalPolicy(), QSizePolicy.Minimum)
        layout.addWidget(self._tabs)

        # 热键初始冲突检测
        self._refresh_hotkey_status("hotkey_lock", self._lock_hk_edit, self._lock_hk_status)
        self._refresh_hotkey_status(
            "hotkey_unlock", self._unlock_hk_edit, self._unlock_hk_status
        )
        self._refresh_hotkey_status(
            "hotkey_top", self._top_hk_edit, self._top_hk_status
        )
        self._refresh_hotkey_status(
            "hotkey_bottom", self._bottom_hk_edit, self._bottom_hk_status
        )

        self.setStyleSheet(self._style_sheet())

    # ============================================================
    #  分页内容
    # ============================================================

    def _build_appearance_tab(self) -> QWidget:
        """外观：字号 / 颜色 / 透明度"""
        page = self._new_page()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(4, 12, 4, 4)
        lay.setSpacing(10)

        # 字号
        size_row = QHBoxLayout()
        size_row.addWidget(self._label("字号"))
        size_row.addStretch()
        spin = QSpinBox()
        spin.setRange(6, 48)
        spin.setValue(self._result.get("font_size", 8))
        # 宽度不写死：由 _apply_widget_styles() 按字体量出来后设定
        spin.valueChanged.connect(lambda v: self._update("font_size", v))
        size_row.addWidget(spin)
        lay.addLayout(size_row)

        # 文字颜色
        lay.addWidget(self._label("文字颜色"))
        self._text_picker = _ColorPicker(
            TEXT_COLORS, self._result.get("text_color", "#FFFFFF"), False, self
        )
        lay.addWidget(self._text_picker)

        # 背景颜色
        lay.addWidget(self._label("背景颜色"))
        self._bg_picker = _ColorPicker(
            BG_COLORS, self._result.get("bg_color", "#000000"), True, self
        )
        lay.addWidget(self._bg_picker)

        # 背景透明度
        lay.addWidget(self._label("背景透明度"))
        opacity_row = QHBoxLayout()
        self._slider = QSlider(Qt.Horizontal)
        self._slider.setRange(5, 95)
        self._slider.setValue(int(self._result.get("bg_opacity", 0.45) * 100))
        self._slider.valueChanged.connect(
            lambda v: self._update("bg_opacity", v / 100.0)
        )
        self._pct_label = self._label(f"{int(self._result.get('bg_opacity', 0.45) * 100)}%")
        self._pct_label.setFixedWidth(36)
        self._pct_label.setAlignment(Qt.AlignCenter)
        self._slider.valueChanged.connect(lambda v: self._pct_label.setText(f"{v}%"))

        opacity_row.addWidget(self._label("透"))
        opacity_row.addWidget(self._slider)
        opacity_row.addWidget(self._label("实"))
        opacity_row.addWidget(self._pct_label)
        lay.addLayout(opacity_row)

        # 快捷百分比：分两行各 4 个。
        # 挤在一行时 8 个按钮共需约 384px，而页面只有约 300px，
        # 布局会把每个压到 34px（文字需要 44px），于是 "10%" 被裁成 "|0%"。
        # 两行后每行 4 个，宽度充裕，字号也能保持与界面一致。
        quick_style = (
            f"QPushButton {{ color: {LABEL_FG}; background: {FIELD_BG};"
            f" border: 1px solid #3a3a3a; border-radius: 3px;"
            f" padding: 3px 6px; font-size: {UI_FONT_SIZE_PT}pt; }}"
            f"QPushButton:hover {{ background: #2a2a2a; color: #fff; }}"
        )
        for row_values in (OPACITY_STEPS[:4], OPACITY_STEPS[4:]):
            quick_row = QHBoxLayout()
            quick_row.setSpacing(4)
            for v in row_values:
                btn = QPushButton(f"{v}%")
                btn.setObjectName("pctBtn")
                btn.setFixedHeight(max(24, self.fontMetrics().height() + 6))
                btn.setStyleSheet(quick_style)
                btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                btn.clicked.connect(lambda _, val=v: self._slider.setValue(val))
                quick_row.addWidget(btn)
            # 不加 addStretch：让 4 个按钮均分整行，避免右侧留白却把按钮挤窄
            lay.addLayout(quick_row)

        lay.addStretch()
        return page

    def _new_page(self) -> QWidget:
        """新建一个分页容器

        必须显式给深色（透明）背景：逐控件挂样式之后，页面的背景不再自动
        继承对话框的黑底，会退回系统默认的浅色，于是灰字叠在白底上很难看。
        """
        page = QWidget()
        page.setObjectName("tabPage")
        page.setAutoFillBackground(False)
        return page

    def _build_function_tab(self) -> QWidget:
        """功能：显示开关 / 洛雪音乐目录 / 使用说明"""
        page = self._new_page()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(4, 12, 4, 4)
        lay.setSpacing(10)

        self._cover_check = QCheckBox("显示歌曲封面")
        self._cover_check.setChecked(self._result.get("show_cover", True))
        self._cover_check.toggled.connect(lambda v: self._update("show_cover", v))
        lay.addWidget(self._cover_check)

        self._spectrum_check = QCheckBox("显示频谱背景")
        self._spectrum_check.setChecked(self._result.get("show_spectrum", True))
        self._spectrum_check.toggled.connect(lambda v: self._update("show_spectrum", v))
        lay.addWidget(self._spectrum_check)

        self._word_check = QCheckBox("逐字歌词（有逐字轨时按字扫过上色）")
        self._word_check.setChecked(self._result.get("show_word_by_word", True))
        self._word_check.toggled.connect(lambda v: self._update("show_word_by_word", v))
        lay.addWidget(self._word_check)

        lay.addWidget(self._label("洛雪音乐安装目录"))
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
        lay.addLayout(lx_row)

        web_btn = QPushButton("洛雪音乐官网 →")
        web_btn.setObjectName("webBtn")
        web_btn.setCursor(Qt.PointingHandCursor)
        web_btn.clicked.connect(lambda: webbrowser.open(LXMUSIC_WEBSITE))
        lay.addWidget(web_btn)

        help_group = QGroupBox("使用说明")
        help_layout = QVBoxLayout(help_group)
        help_layout.setSpacing(3)
        help_layout.setContentsMargins(10, 6, 10, 8)
        # 单行高度显式固定：标签在加入布局前就算好了 sizeHint（那时还不知道
        # 可用宽度），宽度偏窄时会被永久记成两行高度，把窗口高度顶到 530+。
        # 这些文案都保证不超过页内容宽，所以按单行锁死高度最稳。
        tip_h = max(16, self.fontMetrics().height())
        for text in [
            "双击窗口 → 切换吸附边（顶部/底部）",
            "点击封面 → 播放/暂停",
            "悬停 ♫ → 打开洛雪音乐",
            "右键菜单 → 更多快捷操作",
            "拖拽窗口 → 靠近边缘自动吸附",
            "锁定后 → 悬浮 / 热键 / 托盘菜单",
        ]:
            tip_label = self._dim_label(text)
            tip_label.setWordWrap(False)
            tip_label.setFixedHeight(tip_h)
            help_layout.addWidget(tip_label)
        lay.addWidget(help_group)

        lay.addStretch()
        return page

    def _build_lock_tab(self) -> QWidget:
        """锁定：解锁方式 / 热键 / 托盘 / 立即锁定"""
        page = self._new_page()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(4, 12, 4, 4)
        lay.setSpacing(8)

        # 悬浮解锁秒数
        hover_row = QHBoxLayout()
        hover_row.addWidget(self._label("鼠标悬浮解锁"))
        hover_row.addStretch()
        self._hover_spin = QSpinBox()
        self._hover_spin.setRange(1, 10)
        self._hover_spin.setSuffix(" 秒")
        # 宽度不写死（原来 70px，装不下 "10 秒"）：由 _size_spinbox 量算
        self._hover_spin.setValue(int(self._result.get("unlock_hover_seconds", 2)))
        self._hover_spin.valueChanged.connect(
            lambda v: self._update("unlock_hover_seconds", int(v))
        )
        hover_row.addWidget(self._hover_spin)
        lay.addLayout(hover_row)

        hint = self._dim_label(
            "锁定后窗口不响应点击与拖动，鼠标消息直接落到下面的程序；\n"
            "锁定状态不会保存，重启即恢复未锁定。"
        )
        lay.addWidget(hint)

        # 锁定热键
        lock_hk_row = QHBoxLayout()
        lock_hk_row.addWidget(self._label("锁定热键"))
        lock_hk_row.addStretch()
        self._lock_hk_edit = QKeySequenceEdit(
            QKeySequence(self._result.get("hotkey_lock", "Ctrl+Alt+L"))
        )
        self._lock_hk_edit.setFixedWidth(150)
        self._lock_hk_edit.keySequenceChanged.connect(
            lambda seq: self._on_hotkey_changed("hotkey_lock", seq, self._lock_hk_edit)
        )
        lock_hk_row.addWidget(self._lock_hk_edit)
        lay.addLayout(lock_hk_row)
        self._lock_hk_status = self._hint_label("")
        lay.addWidget(self._lock_hk_status)

        # 解锁热键
        unlock_hk_row = QHBoxLayout()
        unlock_hk_row.addWidget(self._label("解锁热键"))
        unlock_hk_row.addStretch()
        self._unlock_hk_edit = QKeySequenceEdit(
            QKeySequence(self._result.get("hotkey_unlock", "Ctrl+Alt+U"))
        )
        self._unlock_hk_edit.setFixedWidth(150)
        self._unlock_hk_edit.keySequenceChanged.connect(
            lambda seq: self._on_hotkey_changed(
                "hotkey_unlock", seq, self._unlock_hk_edit
            )
        )
        unlock_hk_row.addWidget(self._unlock_hk_edit)
        lay.addLayout(unlock_hk_row)
        self._unlock_hk_status = self._hint_label("")
        lay.addWidget(self._unlock_hk_status)

        # 窗口置顶热键
        top_hk_row = QHBoxLayout()
        top_hk_row.addWidget(self._label("窗口置顶热键"))
        top_hk_row.addStretch()
        self._top_hk_edit = QKeySequenceEdit(
            QKeySequence(self._result.get("hotkey_top", "Ctrl+Alt+T"))
        )
        self._top_hk_edit.setFixedWidth(150)
        self._top_hk_edit.keySequenceChanged.connect(
            lambda seq: self._on_hotkey_changed(
                "hotkey_top", seq, self._top_hk_edit
            )
        )
        top_hk_row.addWidget(self._top_hk_edit)
        lay.addLayout(top_hk_row)
        self._top_hk_status = self._hint_label("")
        lay.addWidget(self._top_hk_status)

        # 窗口置底热键
        bottom_hk_row = QHBoxLayout()
        bottom_hk_row.addWidget(self._label("窗口置底热键"))
        bottom_hk_row.addStretch()
        self._bottom_hk_edit = QKeySequenceEdit(
            QKeySequence(self._result.get("hotkey_bottom", "Ctrl+Alt+B"))
        )
        self._bottom_hk_edit.setFixedWidth(150)
        self._bottom_hk_edit.keySequenceChanged.connect(
            lambda seq: self._on_hotkey_changed(
                "hotkey_bottom", seq, self._bottom_hk_edit
            )
        )
        bottom_hk_row.addWidget(self._bottom_hk_edit)
        lay.addLayout(bottom_hk_row)
        self._bottom_hk_status = self._hint_label("")
        lay.addWidget(self._bottom_hk_status)

        # ---- 窗口层级：置顶 / 置底，互斥 ----
        # 与"锁定"是两件事：锁定管"能不能点"，层级管"被谁遮挡"。
        # 标签刻意写短：QCheckBox 不会换行，长文本会把对话框撑宽或被截断，
        # 细节放到下面会自动换行的提示里。
        self._top_check = QCheckBox("窗口置顶（盖住其它窗口）")
        self._top_check.setChecked(self._result.get("always_on_top", True))
        lay.addWidget(self._top_check)

        self._bottom_check = QCheckBox("窗口置底（让其它窗口盖住）")
        self._bottom_check.setChecked(self._result.get("bottom_mode", False))
        lay.addWidget(self._bottom_check)

        # 互斥：勾一个就取消另一个。_update 两边都写，主窗口据此应用。
        def _on_top_toggled(checked):
            self._update("always_on_top", bool(checked))
            if checked:
                self._bottom_check.blockSignals(True)
                self._bottom_check.setChecked(False)
                self._bottom_check.blockSignals(False)
                self._update("bottom_mode", False)

        def _on_bottom_toggled(checked):
            self._update("bottom_mode", bool(checked))
            if checked:
                self._top_check.blockSignals(True)
                self._top_check.setChecked(False)
                self._top_check.blockSignals(False)
                self._update("always_on_top", False)

        self._top_check.toggled.connect(_on_top_toggled)
        self._bottom_check.toggled.connect(_on_bottom_toggled)

        layer_hint = self._hint_label(
            "置顶与置底互斥，两个都不勾 = 正常层级。\n"
            "置底后窗口仍可拖动；想透出壁纸请调低背景不透明度（功能页）。"
        )
        lay.addWidget(layer_hint)

        # 托盘图标（锁定后的兜底出口）
        self._tray_check = QCheckBox("显示托盘图标（锁定后的兜底出口）")
        self._tray_check.setChecked(self._result.get("show_tray", True))
        self._tray_check.toggled.connect(lambda v: self._update("show_tray", v))
        lay.addWidget(self._tray_check)

        lock_now_btn = QPushButton("立即锁定窗口")
        lock_now_btn.setObjectName("lockNowBtn")
        lock_now_btn.setCursor(Qt.PointingHandCursor)
        lock_now_btn.clicked.connect(self._request_lock)
        lay.addWidget(lock_now_btn)

        lay.addStretch()
        return page

    # ============================================================
    #  样式
    # ============================================================

    def _style_sheet(self) -> str:
        return """
            QDialog { background-color: #000; border: 1px solid #333; border-radius: 8px; }
            QWidget { background: transparent; }
            /* 分页容器必须是透明的深色底：不写的话逐控件挂样式后
               页面会退回系统浅色底，灰字落在白底上 */
            QWidget#tabPage { background: transparent; }
            QTabWidget::pane { background: transparent; border: none;
                border-top: 1px solid #2a2a2a; margin-top: 2px; }
            QGroupBox {
                color: #ccc; font-size: 13px; border: 1px solid #333;
                border-radius: 6px; margin-top: 8px; padding-top: 16px;
            }
            QGroupBox::title {
                color: #ddd; subcontrol-origin: margin; left: 10px; padding: 0 4px;
            }
            /* 显式给字色：不能让 QLabel 去问系统调色板，
               本机实测外观页的 QLabel 会解析出纯黑，在黑底上就看不见了 */
            QLabel { color: #ccc; background: transparent; }
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
            QCheckBox { color: #ccc; font-size: 13px; spacing: 6px; }
            QCheckBox::indicator { width: 14px; height: 14px; }
            QPushButton {
                color: #bbb; background: #111; border: 1px solid #333;
                border-radius: 3px; font-size: 12px; padding: 3px 5px;
            }
            QLineEdit {
                color: #ddd; background: #111; border: 1px solid #333;
                border-radius: 4px; padding: 4px 6px; font-size: 12px;
            }
            QLineEdit:focus { border-color: #555; }
            QPushButton:hover { background: #333; color: #fff; }
            #webBtn {
                color: #6af; background: transparent; border: 1px solid #333;
                font-size: 13px; padding: 6px;
            }
            #webBtn:hover { background: #1a2a3a; color: #8cf; }
            #lockNowBtn {
                color: #ccc; background: #1a1a1a; border: 1px solid #3a3a3a;
                font-size: 13px; padding: 6px;
            }
            #lockNowBtn:hover { background: #2a2a2a; color: #fff; border-color: #555; }
            QKeySequenceEdit {
                background: #111; border: 1px solid #333; border-radius: 4px;
                color: #ddd; font-size: 12px; padding: 3px 5px;
            }
            QKeySequenceEdit:focus { border-color: #555; }
            QTabWidget::pane {
                border: none; border-top: 1px solid #2a2a2a; margin-top: 2px;
            }
            QTabBar::tab {
                color: #999; background: transparent; border: none;
                padding: 8px 18px; margin-right: 2px; font-size: 13px;
                border-top-left-radius: 5px; border-top-right-radius: 5px;
            }
            QTabBar::tab:hover { color: #ddd; background: #141414; }
            QTabBar::tab:selected {
                color: #fff; background: #1c1c1c; font-weight: bold;
            }
        """

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

    # ============================================================
    #  锁定 / 热键
    # ============================================================

    def _request_lock(self):
        """点「立即锁定窗口」：标记请求，等对话框关掉后再由主窗口加锁"""
        self.lock_request = True
        # 顺手把当前配置固化成结果，避免用户未点确定时配置丢失
        self._result["text_color"] = self._text_picker.selected
        self._result["bg_color"] = self._bg_picker.selected
        self.accept()

    def _set_status(self, label, text: str, color: str):
        """热键状态小字：统一字号（与说明小字一致）"""
        label.setText(text)
        label.setStyleSheet(
            f"color: {color}; background: transparent; font-size: {HINT_FONT_PX}px;"
        )

    def _refresh_hotkey_status(self, key, edit, label):
        """用 probe 试注册来检测冲突

        三种结果要分开显示，不能一律当冲突：
          free  —— 可用
          own   —— 本程序自己当前正用它（这是**正常**状态：打开设置面板时
                   锁/解锁热键本来就注册着，以前会误报"被其他程序占用"）
          taken —— 真的被别的程序占了
        """
        text = edit.keySequence().toString()
        if not text:
            self._set_status(label, "按一下想用的组合键即可录入", LABEL_FG_DIM)
            return
        if not hotkey.is_valid(text):
            self._set_status(label, "不支持该组合，至少需要一个主键（如 Ctrl+Alt+L）",
                             "#e67e22")
            return

        norm = hotkey.normalize(text)
        if norm and norm != text:
            edit.blockSignals(True)
            edit.setKeySequence(QKeySequence(norm))
            edit.blockSignals(False)

        # 自己的其它热键是否已占了这个组合。
        # probe() 排除不掉这种"两框互撞"：Windows 允许同一进程用不同 id
        # 注册同一个组合键，而 probe 用的是独立 id 去试注册。
        # 若两个框填成一样，先注册的那个会把后来者挤掉（锁定键会永远失效），必须挡住。
        others = [
            ("hotkey_lock", "锁定"),
            ("hotkey_unlock", "解锁"),
            ("hotkey_top", "窗口置顶"),
            ("hotkey_bottom", "窗口置底"),
        ]
        norm_own = hotkey.normalize(str(self._result.get(key, "")))
        for other_key, other_name in others:
            if other_key == key:
                continue
            other_norm = hotkey.normalize(str(self._result.get(other_key, "")))
            if other_norm and other_norm == norm:
                self._set_status(label, f"与{other_name}热键重复，请换一个", "#e74c3c")
                return
        status, detail = hotkey.probe(norm, own_hotkeys=self._own_hotkeys)
        if status == hotkey.STATUS_FREE:
            self._set_status(label, f"{norm} 可用", "#4caf50")
        elif status == hotkey.STATUS_OWN:
            # 不是错误：这正是当前生效的配置
            self._set_status(label, f"{norm}（当前已在用）", LABEL_FG_DIM)
        else:
            self._set_status(label, f"{norm} {detail}", "#e74c3c")

    def _on_hotkey_changed(self, key, seq, edit):
        text = seq.toString()
        # 只按住修饰键时先不写配置，等主键按下来
        if text and hotkey.is_valid(text):
            self._update(key, hotkey.normalize(text))
        elif not text:
            self._update(key, "")

        if key == "hotkey_lock":
            self._refresh_hotkey_status(key, edit, self._lock_hk_status)
        elif key == "hotkey_unlock":
            self._refresh_hotkey_status(key, edit, self._unlock_hk_status)
        elif key == "hotkey_top":
            self._refresh_hotkey_status(key, edit, self._top_hk_status)
        else:
            self._refresh_hotkey_status(key, edit, self._bottom_hk_status)
