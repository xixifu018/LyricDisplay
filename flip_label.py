"""歌词标签 —— 单行升起 / 双行滚动 + 逐字点亮

逐字效果（默认）：**唱到哪个字，哪个字点亮，然后就一直亮着**
  - 已唱的字：亮色，常驻
  - 未唱的字：默认完全不显示（`DIM_UNSUNG=True` 时可画成暗字原地等待）
  - **没有入场动画**：点亮是瞬时的，不位移、不淡入

为什么不做位移/淡入：浮窗高度只比一行文字多几个像素，任何纵向位移都会让字
跑到控件外被裁掉，表现为"残缺的字在闪"。要保持"出现后一直显示"的干净观感，
就不能让字在动画期间离开自己的位置。

关于位置度量（踩过的坑）：
  字素边界必须用 `QFontMetrics.horizontalAdvance` 逐字累加，**不能**用
  `boundingRect` —— 后者带左右 bearing，累加后与 `drawText` 的实际推进量不一致，
  误差随字数线性累积，越长的行越偏。
"""

from PyQt5.QtCore import Qt, QVariantAnimation, QEasingCurve, QSize
from PyQt5.QtWidgets import QWidget, QSizePolicy
from PyQt5.QtGui import (
    QPainter, QFont, QColor, QFontMetrics, QPen, QPixmap, QLinearGradient,
)

# 未唱的字：True = 画成"弱化色"原地等待；False = 完全不画，整行逐字长出来
DIM_UNSUNG = True
# 弱化比例：0.42 = 已唱色向背景靠拢 42%
DIM_FACTOR = 0.42


def luminance(color: QColor) -> float:
    """感知亮度 0~255（Rec.601 权重）"""
    return (0.299 * color.red() + 0.587 * color.green()
            + 0.114 * color.blue())


def blend(a: QColor, b: QColor, t: float) -> QColor:
    """a 向 b 混合 t（0=全 a，1=全 b），保留 a 的 alpha"""
    t = max(0.0, min(1.0, t))
    c = QColor(
        int(round(a.red() + (b.red() - a.red()) * t)),
        int(round(a.green() + (b.green() - a.green()) * t)),
        int(round(a.blue() + (b.blue() - a.blue()) * t)),
    )
    c.setAlpha(a.alpha())
    return c


def dim_color(color: QColor, factor: float = DIM_FACTOR,
              bg: QColor = None) -> QColor:
    """亮色 -> 未唱时的"弱化色"

    关键是**往背景方向退让**，而不是一味变暗：
      - 深色背景（白字）：向黑靠拢 → 变灰
      - 亮色背景（黑字）：向白靠拢 → 变浅
    只乘系数在亮色背景上会失效：`#000000 × 0.42` 还是 `#000000`，
    未唱的字与已唱的字一样实，完全没有层次（实测就是这个现象）。

    没给背景色时退回"只压明度"，保持旧的深色背景行为。
    """
    if bg is None:
        return QColor(
            int(color.red() * factor),
            int(color.green() * factor),
            int(color.blue() * factor),
            color.alpha(),
        )
    # 背景相对文字是亮还是暗，决定往哪边退
    toward = QColor("#FFFFFF") if luminance(bg) >= luminance(color) else QColor("#000000")
    return blend(color, toward, factor)
# 正在被唱的那个字上，亮色显现前沿的柔化宽度（相对该字宽度的比例）。
# 0 = 硬切（整字瞬间点亮）；0.9 ≈ 该字几乎整个宽度都是渐变。
# 这个渐变只改 alpha、不改位置，所以不会把字挤出控件。
REVEAL_FADE = 0.9
# 柔化边的实际宽度 = 音节宽度 × 该比例（并保证至少 REVEAL_EDGE_MIN_PX 像素）。
# 取 0.45 的实测理由：取满 1.0 时当前字右半几乎透明，看起来"缺一块/发黑"；
# 取 0.35 已经接近硬切；0.45 兼顾"有柔边"和"当前字看得清"。
REVEAL_EDGE_RATIO = 0.45
REVEAL_EDGE_MIN_PX = 8.0


class FlipLabel(QWidget):
    """歌词标签，支持单行（升起）/ 双行（滚动），以及逐字点亮"""

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

        # --- 逐字状态 ---
        self._words = ()            # 当前行的 Syllable 元组（空 = 无逐字数据）
        self._position = 0.0        # 当前播放位置（秒），由主窗口推进
        self._line_active = True    # 当前行是否正在唱
        self._label_width = 0       # 文本可用宽度，与主窗口的省略计算保持一致
        self._lit_px = 0.0          # 已点亮的像素宽度（测试/诊断用）
        # 实际背景色（由主窗口按 bg_color × bg_opacity 合成后告知）。
        # 用于决定"未唱的字"往哪个方向退让，见 dim_color()。
        self._bg_color = QColor("#000000")

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

    def set_font_and_color(self, font: QFont, color: str, bg_color: str = None):
        """字体与颜色一起设置（避免两次重排）

        `bg_color` 是**合成后的实际背景色**（bg_color × bg_opacity 叠在桌面上），
        只用来决定未唱的字往哪个方向弱化。
        """
        self._font = font
        self._color = QColor(color)
        if bg_color is not None:
            self._bg_color = QColor(bg_color)
        self.update()
        self.updateGeometry()

    def set_bg_color(self, bg_color: str):
        c = QColor(bg_color)
        if c.isValid() and c != self._bg_color:
            self._bg_color = c
            self.update()

    def set_lyric_data(self, words, position: float, active: bool):
        """设置逐字数据

        words：当前行的 Syllable 元组；空表示不是逐字歌词（走普通绘制）
        position：播放位置（秒）
        active：这一行是否正在被唱
        """
        changed = (
            words is not self._words
            or abs(position - self._position) > 1e-4
            or active != self._line_active
        )
        self._words = words if words else ()
        self._position = position
        self._line_active = active
        if changed:
            self.update()

    def set_label_width(self, width: int):
        """与主窗口的省略宽度保持一致（外部用同一数字计算 elidedText）"""
        self._label_width = max(0, int(width))

    @property
    def label_width(self) -> int:
        return self._label_width

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
    #  动画（整行的升起 / 滚动，与逐字无关）
    # ============================================================

    def _on_anim(self, value):
        if self._mode == "single":
            self._offset_y = self.height() * (1.0 - value)
        else:
            self._offset_y = -self.lineHeight() * value
        self.update()

    def _on_anim_done(self):
        self._offset_y = 0.0
        self._old_text = ""
        self._old_next = ""
        self.update()

    # ============================================================
    #  逐字几何
    # ============================================================

    def _syllable_spans(self, text: str, words) -> tuple:
        """把音节时间轴映射到显示文本的像素区间

        返回 ((左px, 右px, 音节) ...)。

        音节文字在 display 里顺序查找；中间夹着的未覆盖字素（空格、标点）会被
        并入前一个音节的宽度，这样点亮到它们时不会卡住。

        找不到的音节直接跳过（防御：正常数据不会出现）。
        """
        if not text or not words:
            return ()

        fm = QFontMetrics(self._font)
        offsets = []          # 每个字素的左边界
        pos = 0
        for ch in text:
            offsets.append(pos)
            pos += fm.horizontalAdvance(ch)
        offsets.append(pos)   # 末尾哨兵 = 整行宽度

        result = []
        cursor = 0
        for w in words:
            wt = getattr(w, "text", "")
            if not wt:
                continue
            found = -1
            for i in range(cursor, len(text) - len(wt) + 1):
                if text[i:i + len(wt)] == wt:
                    found = i
                    break
            if found < 0:
                found = min(cursor, max(0, len(text) - 1))
            end = min(found + len(wt), len(text))
            result.append((offsets[found], offsets[end], w))
            cursor = end
        return tuple(result)

    def _lit_width(self, text: str) -> float:
        """已经点亮的像素宽度

        判据是**音节的开始时间**：唱到就亮，不需要等这个字唱完。
        这直接对应"出现后就一直显示"——点亮区间只增不减，永不复位。
        """
        spans = self._syllable_spans(text, self._words)
        if not spans:
            return 0.0
        t = self._position
        lit = 0.0
        for left, right, w in spans:
            start = getattr(w, "start", 0.0)
            if t < start:
                break
            lit = float(right)
        return lit

    def _reveal(self, text: str) -> tuple:
        """返回 (亮色完全不透明的位置, 亮色完全消失的位置, 该音节左边界)

        用一个**持续向右推进的柔化前沿**来显现亮色：
          - `[0, solid)`      完全实心的亮色（之前唱过的部分）
          - `[solid, fade)`   亮色从实心平滑淡出到 0

        `solid` 按**当前音节内的时间进度**在字身里滑动，所以前沿是连续扫过去的，
        不是整字硬切——这就是消除"打字机感"的关键。

        淡出区取 stage 起点之后**一个音节宽度**，而不是 stage 内剩余宽度：
        后者会让 frontier 处的 alpha 恰好为 0，"当前字"只在极窄一条里淡淡出现
        （实测 8px 宽、alpha 不足半，视觉上几乎没有）。

        只改 alpha、**不做位移**：浮窗高度只比一行文字多几像素，
        任何纵向位移都会让字跑到控件外被裁掉（实测表现为残字闪烁）。
        """
        spans = self._syllable_spans(text, self._words)
        if not spans:
            return 0.0, 0.0, 0.0
        t = self._position
        # 跳过零宽度的音节（`<start,0>` 标点）：它们只该被顺带亮起，不驱动前沿
        sung = -1
        for i, (left, right, w) in enumerate(spans):
            if t < getattr(w, "start", 0.0):
                break
            if float(right) > float(left):
                sung = i
        if sung < 0:
            return 0.0, 0.0, 0.0

        left, right, w = spans[sung]
        solid = float(spans[sung - 1][1]) if sung >= 1 else 0.0

        span_t = max(0.0, getattr(w, "end", w.start) - getattr(w, "start", 0.0))
        if span_t <= 0:
            p = 1.0                     # 零时长音节：瞬时完成
        else:
            p = (t - getattr(w, "start", 0.0)) / span_t
        p = min(1.0, max(0.0, p))

        width = float(right) - float(left)
        frontier = float(left) + width * p
        frontier = max(solid, frontier)

        # 柔化边宽度：取音节宽度的 0.45（至少 8px）。
        # ⚠️ 不能取满一个音节宽度 —— 那样"正在唱的字"右半几乎透明，
        # 看上去像缺了半块（用户反馈："正在唱的好像是黑色"）。
        # 但也不能太窄，否则退化成硬切、有"打字机感"。
        # 注意：渐变的起点是 frontier（不是音节起点），所以 frontier 处 alpha 恒为 1。
        reach = max(REVEAL_EDGE_MIN_PX, width * REVEAL_EDGE_RATIO) if width > 0 else 12.0
        fade = max(frontier + reach, float(right))
        return solid, frontier, fade

    # 兼容旧调用名（测试/诊断脚本用过 _sweep_fill_width）
    _sweep_fill_width = _lit_width

    # ============================================================
    #  绘制
    # ============================================================

    def _draw_reveal(self, painter, text, cx, baseline, frontier, fade, alpha):
        """亮色从行首实到 `frontier`，并在 [frontier, fade] 内淡出

        为什么要离屏合成（四个都是实测结论）：
          1. `painter.setBrush(gradient)` **对 drawText 无效** —— 文字只吃 pen 颜色。
          2. Qt 没有"只乘 alpha、不动 RGB"的合成模式，只能 `DestinationIn` 乘整个
             RGBA；直接作用在控件画布上会把同区域的封面/频谱一起抠掉。放进透明
             pixmap 里做，乘 RGB 就不产生影响。
          3. ⚠️ **`drawText` 的 x 远超绘图设备宽度时会直接放弃绘制** ——
             clip 和 `painter.translate` 都救不了。实测：41×34 的图层上
             `drawText(326, ...)` 输出 maxA=0；只有把图层加宽到 350 才有像素。
             所以离屏层里必须用**层内局部坐标**，不能沿用整行的绝对坐标。
          4. 因此分两段画，每段都把文字按局部坐标画进自己的层：
               - 实心段 [0, frontier]：层内 x 偏移 = -cx
               - 淡出段 [frontier, fade]：层内 x 偏移 = -x0
             层都很窄（通常几十 px），代价可忽略。
        """
        bright = QColor(self._color)
        bright.setAlpha(alpha)
        h = max(1, int(self.height()))

        # --- 实心段：裁到控件上的 [cx, cx+frontier]，直接画（无需离屏） ---
        if frontier > 0:
            painter.save()
            painter.setClipRect(int(cx), 0, int(frontier) + 1, h)
            painter.setPen(QPen(bright))
            painter.drawText(cx, baseline, text)
            painter.restore()

        # --- 淡出段：只把 [frontier, fade] 这一小段文字画进临时层，乘渐变后贴回 ---
        x0 = int(frontier)
        span = float(fade) - float(frontier)
        if span <= 0.5:
            return
        w = int(span) + 2
        layer = QPixmap(w, h)
        layer.fill(Qt.transparent)
        lp = QPainter(layer)
        lp.setRenderHint(QPainter.Antialiasing)
        lp.setRenderHint(QPainter.TextAntialiasing)
        lp.setFont(self._font)
        # 层内局部坐标：层的 x=0 对应控件上的 cx+x0
        lp.setClipRect(0, 0, w, h)
        lp.setPen(QPen(bright))
        lp.drawText(-x0, baseline, text)
        # 渐变遮罩：起点不透明，到层右端降为透明
        grad = QLinearGradient(0.0, 0.0, float(w), 0.0)
        grad.setColorAt(0.0, QColor(255, 255, 255, 255))
        grad.setColorAt(1.0, QColor(255, 255, 255, 0))
        lp.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        lp.fillRect(layer.rect(), grad)
        lp.end()

        painter.drawPixmap(int(cx) + x0, 0, layer)


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
            self._draw_line(painter, self._text, w, h, 0.0, 255, wbw=True)
            return

        progress = 1.0 - self._offset_y / h

        old_alpha = int(255 * (1.0 - progress))
        if old_alpha > 0 and self._old_text:
            self._draw_line(painter, self._old_text, w, h, 0.0, old_alpha, wbw=False)

        new_alpha = int(255 * progress)
        self._draw_line(painter, self._text, w, h, self._offset_y, new_alpha, wbw=True)

    def _paint_double(self, painter, w):
        """双行模式：上下两行，滚动切换"""
        line_h = self.lineHeight()

        if abs(self._offset_y) < 0.5:
            self._draw_line(painter, self._text, w, line_h, 0.0, 255, wbw=True)
            if self._next_text:
                self._draw_line(painter, self._next_text, w, line_h,
                                float(line_h), 140, wbw=False)
            return

        offset = self._offset_y
        progress = abs(offset) / line_h

        old_alpha = int(255 * (1.0 - progress))
        if self._old_text:
            self._draw_line(painter, self._old_text, w, line_h, offset,
                            old_alpha, wbw=False)
        if self._old_next:
            self._draw_line(painter, self._old_next, w, line_h, offset + line_h,
                            max(0, old_alpha - 60), wbw=False)

        new_alpha = int(255 * progress)
        if self._text:
            self._draw_line(painter, self._text, w, line_h, offset + line_h,
                            new_alpha, wbw=True)
        if self._next_text:
            self._draw_line(painter, self._next_text, w, line_h,
                            offset + line_h * 2, max(0, new_alpha - 60), wbw=False)

    def _draw_line(self, painter, text, w, line_h, offset_y, alpha, wbw=False):
        """居中画一行文字；wbw=True 且有逐字数据时按字点亮"""
        if alpha <= 0 or not text:
            return

        fm = QFontMetrics(self._font)
        tw = fm.horizontalAdvance(text)
        cx = int((w - tw) / 2.0)
        cy = (line_h - fm.height()) / 2.0
        baseline = int(cy + fm.ascent() + offset_y)

        bright = QColor(self._color)
        bright.setAlpha(alpha)

        # 是否走逐字路径：要求"这一行正在唱" + "有字级时间" + "开关打开"。
        # ⚠️ 不能用 self._line_active 作为唯一判据：非活动行（尚未开始唱、或已唱完
        # 待切行）也必须**整行正常显示**，否则会落到暗色分支上，屏幕上几乎看不见
        # （实测：DIM_UNSUNG=True 时非活动行渲染出 0 个亮像素）。
        # 行首之前不在这里拦 —— 交给 _reveal 返回 0，效果就是"还没开始唱，什么都不显示"。
        wbw_on = bool(wbw and self._words and self._line_active)
        if not wbw_on:
            self._lit_px = 0.0
            painter.setPen(QPen(bright))
            painter.drawText(cx, baseline, text)
            return

        solid, frontier, fade = self._reveal(text)
        self._lit_px = frontier

        # ① 先把**整行**铺成暗色（未唱等待色）。
        #    ⚠️ 必须整行垫底，不能只画 fade 之后：亮色在 [frontier, fade] 是
        #    淡出到**透明**的，那一段底下若没有暗字，露出的就是窗口背景
        #    （深色底 → 看得见透出来的壁纸/黑），视觉上"正在唱的那个字发黑"
        #    （用户实际反馈）。垫上暗字后，淡出露出的是灰，形成 白→灰 的过渡。
        if DIM_UNSUNG:
            painter.save()
            painter.setPen(QPen(dim_color(bright, bg=self._bg_color)))
            painter.drawText(cx, baseline, text)
            painter.restore()

        # ② 亮色层：从行首实心到 frontier，然后在 [frontier, fade] 内淡出。
        # **不用 CompositionMode_DestinationIn 直接作用在控件画布上** —— 那会把
        # 同一区域里已画好的封面/频谱一起抠掉。只在临时 pixmap 里用它。
        bright_pen = QPen(bright)
        if frontier > 0:
            if REVEAL_FADE and fade > frontier + 1.0:
                self._draw_reveal(painter, text, cx, baseline, frontier, fade, alpha)
            else:
                painter.save()
                painter.setClipRect(int(cx), 0, int(frontier) + 1, int(self.height()))
                painter.setPen(bright_pen)
                painter.drawText(cx, baseline, text)
                painter.restore()
