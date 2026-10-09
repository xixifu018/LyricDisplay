"""LRC 歌词解析器"""

import re

# 匹配时间标签: [mm:ss] / [mm:ss.x] / [mm:ss.xx] / [mm:ss.xxx]，分隔符允许 . 或 :
TIME_TAG_RE = re.compile(r"\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]")
# 元数据标签: [ar:xxx] [ti:xxx] [al:xxx] [offset:xxx] 等
META_TAG_RE = re.compile(r"\[([a-zA-Z]+):(.+)\]")


class LyricLine:
    """一行歌词：时间戳（秒） + 文本"""
    __slots__ = ("time", "text")

    def __init__(self, time: float, text: str):
        self.time = time
        self.text = text


def parse_lrc(lrc_text: str) -> list[LyricLine]:
    """解析 LRC 歌词文本，返回按时间排序的 LyricLine 列表"""
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
            frac_str = match.group(3) or "0"
            # 将小数部分归一化为秒（1 位=十分之一，2 位=百分之一，3 位=毫秒）
            frac = int(frac_str) / (10 ** len(frac_str))

            time_sec = minutes * 60 + seconds + frac + offset
            lines.append(LyricLine(time_sec, text))

    # 按时间排序
    lines.sort(key=lambda x: x.time)
    return lines


def get_line_at(lyric_lines: list[LyricLine], progress: float) -> str:
    """
    根据播放进度（秒）返回当前歌词文本。
    返回当前时间戳 <= progress 的最后一行歌词文本。
    如果还没有到第一行歌词，返回空字符串。
    """
    if not lyric_lines or progress < 0:
        return ""

    current = ""
    for line in lyric_lines:
        if line.time <= progress:
            current = line.text
        else:
            break

    return current


def get_current_and_next(lyric_lines: list[LyricLine], progress: float) -> tuple[str, str]:
    """
    返回 (当前歌词, 下一句歌词)
    """
    if not lyric_lines or progress < 0:
        return ("", "")

    current = ""
    next_text = ""
    found_current = False

    for line in lyric_lines:
        if line.time <= progress:
            current = line.text
            found_current = True
        elif found_current:
            next_text = line.text
            break

    return (current, next_text)
