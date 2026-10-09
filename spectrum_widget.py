"""频谱可视化组件 —— 真实音频 FFT 数据驱动"""

from PyQt5.QtCore import Qt, QTimer, QRectF
from PyQt5.QtWidgets import QWidget
from PyQt5.QtGui import QPainter, QLinearGradient, QColor, QBrush


BAR_COUNT = 48
BAR_WIDTH_RATIO = 0.55
ANIM_SPEED = 0.7            # 过渡速度
PEAK_HOLD_FRAMES = 14       # 峰值保持帧数


class SpectrumWidget(QWidget):
    """频谱条背景 —— 接收音频 FFT 数据并绘制"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._active = False

        self._heights = [0.0] * BAR_COUNT
        self._targets = [0.0] * BAR_COUNT
        self._peaks = [0.0] * BAR_COUNT
        self._peak_frames = [0] * BAR_COUNT

        # ~50fps 平滑过渡
        self._timer = QTimer(self)
        self._timer.setInterval(20)
        self._timer.timeout.connect(self._tick)

        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    # ============================================================
    #  公共
    # ============================================================

    def start(self):
        if self._active:
            return
        self._active = True
        self._timer.start()
        self.show()

    def stop(self):
        self._active = False
        self._timer.stop()
        for i in range(BAR_COUNT):
            self._heights[i] = 0.0
            self._targets[i] = 0.0
            self._peaks[i] = 0.0
            self._peak_frames[i] = 0
        self.update()
        self.hide()

    def set_levels(self, levels: list[float]):
        """接收 FFT 频谱数据 (0.0~1.0)"""
        if not self._active:
            return
        for i in range(min(len(levels), BAR_COUNT)):
            self._targets[i] = max(0.0, min(1.0, levels[i]))

    # ============================================================
    #  每帧更新
    # ============================================================

    def _tick(self):
        changed = False
        for i in range(BAR_COUNT):
            old = self._heights[i]
            self._heights[i] += (self._targets[i] - old) * ANIM_SPEED

            # 峰值保持
            if self._heights[i] > self._peaks[i]:
                self._peaks[i] = self._heights[i]
                self._peak_frames[i] = PEAK_HOLD_FRAMES
            elif self._peak_frames[i] > 0:
                self._peak_frames[i] -= 1
                self._peaks[i] -= 0.012
            else:
                self._peaks[i] = max(0.0, self._peaks[i] - 0.025)

            if abs(self._heights[i] - old) > 0.0003:
                changed = True

        if changed:
            self.update()

    # ============================================================
    #  绘制
    # ============================================================

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        if w <= 0 or h <= 0:
            return

        bar_w = (w / BAR_COUNT) * BAR_WIDTH_RATIO
        gap = (w / BAR_COUNT) - bar_w

        # 七彩渐变：左→右 青蓝紫粉橙黄
        grad = QLinearGradient(0, 0, w, 0)
        grad.setColorAt(0.0, QColor(0, 240, 240))
        grad.setColorAt(0.2, QColor(60, 180, 255))
        grad.setColorAt(0.4, QColor(160, 100, 255))
        grad.setColorAt(0.6, QColor(255, 80, 200))
        grad.setColorAt(0.8, QColor(255, 120, 60))
        grad.setColorAt(1.0, QColor(255, 220, 60))

        painter.setPen(Qt.NoPen)

        for i in range(BAR_COUNT):
            x = gap / 2 + i * (bar_w + gap)
            bar_h = self._heights[i] * h * 0.9

            if bar_h < 0.5:
                continue

            y = h - bar_h

            t = i / (BAR_COUNT - 1)
            base = QColor(grad.stops()[min(int(t * 5), 4)][1])
            top_c = QColor(base.red(), base.green(), base.blue(), 170)
            bot_c = QColor(base.red(), base.green(), base.blue(), 45)

            bar_grad = QLinearGradient(0, y, 0, h)
            bar_grad.setColorAt(0.0, top_c)
            bar_grad.setColorAt(1.0, bot_c)
            painter.setBrush(QBrush(bar_grad))
            painter.drawRoundedRect(QRectF(x, y, bar_w, bar_h), 1.5, 1.5)

            # 峰值亮点
            peak_h = self._peaks[i] * h * 0.9
            if peak_h > 0.5 and self._peak_frames[i] > 0:
                peak_y = h - peak_h
                alpha = min(200, self._peak_frames[i] * 10)
                painter.setBrush(QBrush(QColor(255, 255, 255, alpha)))
                painter.drawRoundedRect(QRectF(x, peak_y, bar_w, 2.5), 1, 1)

        painter.end()
