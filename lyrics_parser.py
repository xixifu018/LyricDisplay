"""歌词解析器 —— 支持标准 LRC 与洛雪逐字歌词（AWLRC）

两种格式：

1. 标准 LRC
       [00:12.34]落叶随风将要去何方
   一行一个时间戳，没有字级时间信息。

2. 洛雪逐字歌词（AWLRC，开放 API 的 `lxlyric` 字段）
       [00:32.210]<0,450>Corrupt <450,1035>binary <1485,373>codes
   行时间戳 + 若干 `<相对行首偏移ms,时长ms>文字`。
   实测（2026-10，洛雪 v2.x / 两首曲目）粒度由上游决定：
     - 中文按**字**切：`<0,561>丽<561,623>都`
     - 拉丁按**整词**切：`<0,513>Cyberangel`
   因此消费方不应再做分词。

解析这个格式有三个坑（都是实测踩出来的，测试里逐条守着）：
  a. 逐字正则的文字部分必须用 `[^<]+` 而不是 `[^<]*`：
     `*` 允许空串，会在行尾多匹配出一个空音节。
  b. 重建行文本必须**拼接捕获组**，不能用 `re.sub(pattern, "", line)`：
     模式里含 `<`，从行首起匹配不上，结果是文字被删掉、标签留下。
  c. 时间戳小数部分要除以 1000 后相加，不能当整数直接加到秒上
     （`[00:32.210]` 是 32.210 秒，不是 242 秒）。
"""

import re
from typing import Optional

# ---------------------------------------------------------------- 正则

# 标准 LRC 时间标签: [mm:ss] / [mm:ss.x] / [mm:ss.xx] / [mm:ss.xxx]，分隔符 . 或 :
TIME_TAG_RE = re.compile(r"\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]")
# 元数据标签: [ar:xxx] [ti:xxx] [al:xxx] [offset:xxx] 等
META_TAG_RE = re.compile(r"\[([a-zA-Z]+):(.+)\]")

# AWLRC 行: [mm:ss.xxx] 或 [hh:mm:ss.xxx]，小数位实测恒为 3 位，但放宽到 1~3
AWLRC_LINE_RE = re.compile(r"^\[(\d{1,3}(?::\d{1,3}){0,2})\.(\d{1,3})\](.*)$")
# AWLRC 音节: <偏移ms,时长ms>文字。第三字段可选（洛雪把 KRC 的三字段归一成两字段，
# 但容忍原始写法）。文字用 + ：见上面坑 a。
AWLRC_WORD_RE = re.compile(r"<(\d+),(\d+)(?:,\d+)?>([^<]+)")

# 只有元数据标签、没有时间戳的行（用于过滤 [offset:0] 这类）
_META_ONLY_RE = re.compile(r"^\[[a-zA-Z]+:.*\]$")


# ---------------------------------------------------------------- 数据结构


class Syllable:
    """一个逐字单元：绝对起止时间（秒） + 文字"""

    __slots__ = ("start", "end", "text")

    def __init__(self, start: float, end: float, text: str):
        self.start = start
        self.end = end
        self.text = text

    @property
    def duration(self) -> float:
        return self.end - self.start

    def __repr__(self) -> str:  # 便于测试输出
        return f"Syllable({self.start:.3f}, {self.end:.3f}, {self.text!r})"


class LyricLine:
    """一行歌词

    `time` / `text` 与旧版保持一致（外部只依赖这两个字段），
    `end` 与 `syllables` 是逐字支持新增：
      - 纯 LRC 行：`end` 由下一行时间戳推出，`syllables` 为空元组
      - AWLRC 行：`end` 取下一行首（防越界），`syllables` 为 Syllable 元组
    """

    __slots__ = ("time", "text", "end", "syllables")

    def __init__(self, time: float, text: str,
                 end: Optional[float] = None,
                 syllables: tuple = ()):
        self.time = time
        self.text = text
        self.end = end if end is not None else time
        self.syllables = syllables

    @property
    def has_syllables(self) -> bool:
        return len(self.syllables) > 0

    def __repr__(self) -> str:
        return f"LyricLine({self.time:.3f}, {self.text!r}, {len(self.syllables)} 音节)"


# ---------------------------------------------------------------- 时间解析


def _frac_to_seconds(frac_str: Optional[str]) -> float:
    """把小数位字符串按位值换算成秒

    '5' -> 0.5（十分位）  '50' -> 0.5（百分位）  '500' -> 0.5（毫秒）
    要点见坑 c：不能把 '210' 直接当 210 秒。
    """
    if not frac_str:
        return 0.0
    # 补到 3 位再当毫秒，等价于按位值换算，且对 '210' 这类更直观
    return int(frac_str.ljust(3, "0")[:3]) / 1000.0


def _awlrc_timestamp(fields: str, frac: str) -> float:
    """AWLRC 行时间戳 -> 秒。fields 可能是 mm:ss 或 hh:mm:ss"""
    parts = [int(p) for p in fields.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    hours, minutes, seconds = parts
    return hours * 3600 + minutes * 60 + seconds + _frac_to_seconds(frac)


# ---------------------------------------------------------------- 格式探测


def looks_like_awlrc(text: str) -> bool:
    """判断文本是否为洛雪逐字歌词（AWLRC）

    只看是否出现「行时间戳 + 紧跟 <偏移,时长>」，避免把普通 LRC 误判为逐字。
    """
    if not text:
        return False
    for raw in text.splitlines():
        line = raw.strip()
        if not line or _META_ONLY_RE.match(line):
            continue
        m = AWLRC_LINE_RE.match(line)
        if m and AWLRC_WORD_RE.match(m.group(3)):
            return True
    return False


# ---------------------------------------------------------------- 解析


def parse_awlrc(text: str, offset_seconds: Optional[float] = None) -> list[LyricLine]:
    """解析洛雪逐字歌词

    offset_seconds：
      - None（默认）时自动判断 —— 逐字轨的行时间戳与标准 LRC 轨同源，
        而标准 LRC 的 offset 已在 `parse_lrc` 里加过；若这里再加一次就会
        **双重计入**。实测两首曲目的 `[offset:0]`，无法据此判断，
        因此默认**不额外应用** offset，只把它当作元数据保留。
      - 显式传入数值时才应用（供调用方发现时间戳确实离谱时使用）。
    """
    if not text:
        return []

    offset = float(offset_seconds) if offset_seconds is not None else 0.0
    drafts: list[tuple] = []

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        # [offset:0] 这类元数据行跳过（它们没有逐字标签）
        if _META_ONLY_RE.match(line) and not AWLRC_LINE_RE.match(line):
            continue

        m = AWLRC_LINE_RE.match(line)
        if not m:
            continue

        start_time = _awlrc_timestamp(m.group(1), m.group(2)) + offset
        syllables: list[Syllable] = []
        # 游标修复：酷狗偶尔吐出零时长或倒序的音节标记
        cursor_ms = 0
        for off_str, dur_str, word_text in AWLRC_WORD_RE.findall(m.group(3)):
            offset_ms = max(int(off_str), cursor_ms)
            # 时长允许为 0：标点/间隔的时长实测可能为 0（如 `<200,0>：`），
            # 表示"瞬时"。不能钳成最小值，否则零时长标点会凭空占用时间。
            # 游标机制（offset >= cursor）已经能保证不重叠、不倒退。
            duration_ms = max(int(dur_str), 0)
            syllables.append(Syllable(
                start_time + offset_ms / 1000.0,
                start_time + (offset_ms + duration_ms) / 1000.0,
                word_text,
            ))
            cursor_ms = offset_ms + duration_ms

        if not syllables:
            continue

        # 文本重建：拼接捕获组（见坑 b）
        full_text = "".join(s.text for s in syllables)
        drafts.append((start_time, full_text, tuple(syllables)))

    if not drafts:
        return []

    # 某些导出按小数位而非数值排序（.79 排在 .181 前），必须重新排序
    drafts.sort(key=lambda d: d[0])

    lines: list[LyricLine] = []
    for i, (start_time, full_text, syllables) in enumerate(drafts):
        if i + 1 < len(drafts):
            # 用下一行首当本行尾，天然防止逐字时间越界
            end_time = drafts[i + 1][0]
        else:
            end_time = syllables[-1].end if syllables else start_time
        # 兜底：行尾不得早于本行起点，也不得早于最后一个音节的结束
        last_end = syllables[-1].end if syllables else start_time
        end_time = max(end_time, last_end, start_time)
        lines.append(LyricLine(start_time, full_text, end_time, syllables))

    return lines


def parse_lrc(lrc_text: str, apply_offset: bool = True) -> list[LyricLine]:
    """解析标准 LRC 歌词文本，返回按时间排序的 LyricLine 列表

    `apply_offset=False` 时不应用 `[offset:]`（供逐字轨对齐时对比使用）。
    """
    lines: list[LyricLine] = []

    if not lrc_text:
        return lines

    offset = 0.0

    for raw_line in lrc_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        # 检查是否为元数据标签
        meta_match = META_TAG_RE.match(line)
        if meta_match:
            key = meta_match.group(1).lower()
            value = meta_match.group(2)
            if key == "offset":
                try:
                    offset = int(value) / 1000.0  # offset 单位是毫秒
                except ValueError:
                    pass
            continue

        # 查找所有时间标签
        time_tags = list(TIME_TAG_RE.finditer(line))
        if not time_tags:
            continue

        # 提取歌词文本（最后一个时间标签之后的内容）
        last_end = time_tags[-1].end()
        text = line[last_end:].strip()

        for match in time_tags:
            minutes = int(match.group(1))
            seconds = int(match.group(2))
            frac = _frac_to_seconds(match.group(3))

            time_sec = minutes * 60 + seconds + frac
            if apply_offset:
                time_sec += offset
            lines.append(LyricLine(time_sec, text))

    # 按时间排序
    lines.sort(key=lambda x: x.time)
    for i, line in enumerate(lines):
        if i + 1 < len(lines):
            line.end = lines[i + 1].time
        else:
            # 末行没有下一行可借，给一个保守时长
            line.end = line.time + 5.0
    return lines


def parse_lyrics(text: str) -> tuple[list[LyricLine], bool]:
    """解析歌词文本，自动识别逐字格式

    返回 (行列表, 是否为逐字歌词)。
    """
    if not text:
        return [], False
    if looks_like_awlrc(text):
        lines = parse_awlrc(text)
        if lines:
            return lines, True
    return parse_lrc(text), False


# ---------------------------------------------------------------- 查询


def get_line_at(lyric_lines: list[LyricLine], progress: float) -> str:
    """
    根据播放进度（秒）返回当前歌词文本。
    返回当前时间戳 <= progress 的最后一行歌词文本。
    如果还没有到第一行歌词，返回空字符串。
    """
    idx = find_line_index(lyric_lines, progress)
    return lyric_lines[idx].text if idx >= 0 else ""


def get_current_and_next(lyric_lines: list[LyricLine], progress: float) -> tuple[str, str]:
    """
    返回 (当前歌词, 下一句歌词)
    """
    if not lyric_lines or progress < 0:
        return ("", "")

    idx = find_line_index(lyric_lines, progress)
    if idx < 0:
        # 还没到第一行：把第一行当作"下一句"
        return ("", lyric_lines[0].text)
    next_text = lyric_lines[idx + 1].text if idx + 1 < len(lyric_lines) else ""
    return (lyric_lines[idx].text, next_text)


def find_line_index(lyric_lines: list[LyricLine], progress: float) -> int:
    """二分查找当前行下标；没有匹配返回 -1

    与 `get_line_at` 的区别：这里返回下标，便于上层进一步取 syllables。
    用二分而不是线性扫，因为每帧都要调用。
    """
    if not lyric_lines or progress < 0:
        return -1
    low, high = 0, len(lyric_lines) - 1
    found = -1
    while low <= high:
        mid = (low + high) // 2
        if lyric_lines[mid].time <= progress:
            found = mid
            low = mid + 1
        else:
            high = mid - 1
    return found


def find_active_syllable(line: LyricLine, progress: float) -> tuple[int, float]:
    """返回 (当前音节下标, 该音节内的进度 0~1)；无逐字或未开始返回 (-1, 0.0)

    逐字上色（卡拉OK 扫过）就靠这个：进度滑过字身宽度，就是这个字被唱的过程。
    最后一个音节之后到行尾之间返回 (len-1, 1.0)，表示整行已唱完。
    """
    syllables = line.syllables
    if not syllables:
        return -1, 0.0
    if progress < syllables[0].start:
        return -1, 0.0
    if progress >= syllables[-1].end:
        return len(syllables) - 1, 1.0

    low, high = 0, len(syllables) - 1
    idx = 0
    while low <= high:
        mid = (low + high) // 2
        if syllables[mid].start <= progress:
            idx = mid
            low = mid + 1
        else:
            high = mid - 1

    syl = syllables[idx]
    span = syl.end - syl.start
    if span <= 0:
        # 零时长音节（标点）视为瞬时完成
        return idx, 1.0
    return idx, min(1.0, max(0.0, (progress - syl.start) / span))
