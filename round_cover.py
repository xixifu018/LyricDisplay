"""圆形封面组件 —— 裁剪为圆形，支持旋转动画 + 点击切歌"""

from PyQt5.QtCore import Qt, QTimer, QRectF, pyqtSignal
from PyQt5.QtWidgets import QWidget
from PyQt5.QtGui import QPainter, QPixmap, QTransform, QPainterPath, QBrush, QPen, QColor


class RoundCover(QWidget):
    """圆形封面，点击切换播放/暂停，播放时旋转"""

    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap = QPixmap()
        self._angle = 0.0
        self._playing = False

        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)

        self.setCursor(Qt.PointingHandCursor)

    # ============================================================
    #  公共
    # ============================================================

    def setPixmap(self, pix: QPixmap):
        self._pixmap = pix
        self.update()

    def setPlaying(self, playing: bool):
        if playing and not self._playing:
            self._timer.start()
        elif not playing and self._playing:
            self._timer.stop()
        self._playing = playing

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    # ============================================================
    #  旋转
    # ============================================================

    def _tick(self):
        self._angle = (self._angle + 1.5) % 360.0
        self.update()

    # ============================================================
    #  绘制
    # ============================================================

    def paintEvent(self, event):
        if self._pixmap.isNull():
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        w = self.width()
        h = self.height()
        size = min(w, h)
        cx = (w - size) / 2.0
        cy = (h - size) / 2.0

        # 圆形裁剪路径
        path = QPainterPath()
        path.addEllipse(QRectF(cx, cy, size, size))
        painter.setClipPath(path)

        # 缩放并旋转绘制
        scaled = self._pixmap.scaled(
            size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )

        painter.save()
        painter.translate(w / 2.0, h / 2.0)
        painter.rotate(self._angle)
        painter.drawPixmap(-size // 2, -size // 2, scaled)
        painter.restore()

        # 圆形边框
        painter.setClipping(False)
        painter.setPen(QPen(QColor(255, 255, 255, 45), 1.5))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QRectF(cx + 0.5, cy + 0.5, size - 1, size - 1))

        painter.end()
