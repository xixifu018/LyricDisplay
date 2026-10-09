"""歌词标签 —— 单行升起 / 双行滚动"""

from PyQt5.QtCore import Qt, QVariantAnimation, QEasingCurve, QSize
from PyQt5.QtWidgets import QWidget, QSizePolicy
from PyQt5.QtGui import QPainter, QFont, QColor, QFontMetrics, QPen


class FlipLabel(QWidget):
    """歌词标签，支持单行（升起）/ 双行（滚动）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._text = ""        # 当前歌词
        self._next_text = ""   # 下一句歌词
        self._old_text = ""
        self._old_next = ""
        self._mode = "single"  # single / double
        self._font = QFont("Microsoft YaHei", 8)
        self._color = QColor("#FFFFFF")
        self._offset_y = 0.0

        self._anim = QVariantAnimation(self)
        self._anim.setDuration(280)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._on_anim)
        self._anim.finished.connect(self._on_anim_done)

        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)

    # ============================================================
    #  公共
    # ============================================================

    def setMode(self, mode: str):
        self._mode = mode
        self._offset_y = 0.0
        self._anim.stop()
        self._old_text = ""
        self._old_next = ""
        self.update()
        self.updateGeometry()

    def setTexts(self, current: str, next_line: str):
        """设置当前和下一句歌词；相同内容不触发动画"""
        if current == self._text and next_line == self._next_text:
            return
        self._old_text = self._text
        self._old_next = self._next_text
        self._text = current
        self._next_text = next_line
        self._anim.stop()
        self._anim.start()
        self.update()
        self.updateGeometry()

    def setFont(self, font: QFont):
        self._font = font
        self.update()
        self.updateGeometry()

    def setColor(self, color: str):
        self._color = QColor(color)
        self.update()

    def lineHeight(self) -> int:
        """单行高度（用于外部计算窗口尺寸）"""
        fm = QFontMetrics(self._font)
        return fm.height() + 4

    def minimumSizeHint(self):
        fm = QFontMetrics(self._font)
        if self._mode == "double":
            h = (fm.height() + 4) * 2 + 2
        else:
            h = fm.height() + 4
        return QSize(0, h)

    def sizeHint(self):
        return self.minimumSizeHint()

    # ============================================================
    #  动画
    # ============================================================

    def _on_anim(self, value):
        if self._mode == "single":
            # 升起：从下方偏移到 0
            self._offset_y = self.height() * (1.0 - value)
        else:
            # 双行滚动：整体上移一行高度
            line_h = self.lineHeight()
            self._offset_y = -line_h * value
        self.update()

    def _on_anim_done(self):
        self._offset_y = 0.0
        self._old_text = ""
        self._old_next = ""
        self.update()

    # ============================================================
    #  绘制
    # ============================================================

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)
        painter.setFont(self._font)

        w = self.width()

        if self._mode == "single":
            self._paint_single(painter, w)
        else:
            self._paint_double(painter, w)

    def _paint_single(self, painter, w):
        """单行模式：居中一行，带升起动画"""
        h = self.height()

        if self._offset_y <= 0.5:
            self._draw_line(painter, self._text, w, h, 0.0, 255)
            return

        progress = 1.0 - self._offset_y / h

        # 旧歌词渐隐
        old_alpha = int(255 * (1.0 - progress))
        if old_alpha > 0 and self._old_text:
            self._draw_line(painter, self._old_text, w, h, 0.0, old_alpha)

        # 新歌词从下方升入
        new_alpha = int(255 * progress)
        self._draw_line(painter, self._text, w, h, self._offset_y, new_alpha)

    def _paint_double(self, painter, w):
        """双行模式：上下两行，滚动切换"""
        line_h = self.lineHeight()

        if abs(self._offset_y) < 0.5:
            # 静止态
            self._draw_line(painter, self._text, w, line_h, 0.0, 255)
            if self._next_text:
                self._draw_line(painter, self._next_text, w, line_h, float(line_h), 140)
            return

        # 滚动中：offset_y 从 0 → -line_h
        offset = self._offset_y
        progress = abs(offset) / line_h  # 0→1

        # 旧两行向上移出
        old_alpha = int(255 * (1.0 - progress))
        if self._old_text:
            self._draw_line(painter, self._old_text, w, line_h, offset, old_alpha)
        if self._old_next:
            self._draw_line(painter, self._old_next, w, line_h, offset + line_h, max(0, old_alpha - 60))

        # 新两行从下方滚入
        new_alpha = int(255 * progress)
        if self._text:
            self._draw_line(painter, self._text, w, line_h, offset + line_h, new_alpha)
        if self._next_text:
            self._draw_line(painter, self._next_text, w, line_h, offset + line_h * 2, max(0, new_alpha - 60))

    def _draw_line(self, painter, text, w, line_h, offset_y, alpha):
        """居中画一行文字"""
        if alpha <= 0 or not text:
            return

        fm = QFontMetrics(self._font)
        tw = fm.horizontalAdvance(text)
        cx = (w - tw) / 2.0
        cy = (line_h - fm.height()) / 2.0

        c = QColor(self._color.red(), self._color.green(), self._color.blue(), alpha)
        painter.setPen(QPen(c))
        painter.drawText(int(cx), int(cy + fm.ascent() + offset_y), text)
