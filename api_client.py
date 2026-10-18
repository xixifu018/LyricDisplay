"""LX Music API 客户端 —— 轮询 /status 获取播放状态，切歌时取歌词

歌词来源：`/lyric-all`，一次拿到四条轨
    { lyric, tlyric, rlyric, lxlyric }
其中 `lxlyric` 是洛雪逐字歌词（AWLRC），可用时优先使用，否则回退到 `lyric`。

线程模型：`/status` 轮询在后台线程里做（避免阻塞 UI），
因此这里用 threading.local 保存 requests.Session —— Session 不是线程安全的，
但每个轮询线程各持一个，连接池仍然生效。
**同时只允许一个轮询在跑**（`_polling`）：切歌时要同步取歌词（最长 3s），
若放任下一轮又起一个线程，两个线程会互相覆盖歌词缓存。

⚠️ **切歌时歌词有延迟**：`/status` 报告新歌名的瞬间，`/lyric-all` 常常还是
上一首的内容。所以取回后必须**校验归属**（见 `_looks_stale`），
发现是上一首的就丢弃并在下一轮重取（有次数上限）。
"""

import difflib
import re
import threading
from urllib.parse import urlencode

import requests
from PyQt5.QtCore import QObject, pyqtSignal, QTimer

from lyrics_parser import LyricLine, parse_lyrics, parse_lrc

# 歌词头部的标题标签：[ti:歌名]
_TITLE_RE = re.compile(r"^\[ti:(.*?)\]\s*$", re.MULTILINE)
# 归一化标题时去掉的字符：空白、中英文标点、常见分隔符
_TITLE_STRIP_RE = re.compile(r"[\s:：·・\-—_,，.。'\"“”‘’()（）\[\]【】!！?？/\\]+")


class ApiClient(QObject):
    """通过轮询 /status 接口获取播放状态，通过 Qt 信号通知"""

    # 状态变更信号: dict(status, name, singer, progress, duration,
    #                   lyricLineText, picUrl, lyric, lyric_lines, is_word_by_word)
    status_changed = pyqtSignal(dict)
    # 连接状态信号: bool
    connection_changed = pyqtSignal(bool)

    # 轮询时只取这些字段：整首歌词很大（数 KB），改由 /lyric-all 单独取一次
    STATUS_FILTER = (
        "status,name,singer,albumName,duration,progress,"
        "lyricLineText,picUrl,playbackRate"
    )

    def __init__(self, api_url: str, parent=None):
        super().__init__(parent)
        self._api_url = api_url
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._interval_ms = 500
        self._connected = False

        # 歌词缓存（切歌时失效）
        self._last_name = None
        self._last_lyric = ""            # 原始文本（回退用 / 对外兼容）
        self._last_lines: list[LyricLine] = []
        self._last_word_by_word = False
        self._last_has_lxlyric = False

        # 切歌后歌词可能还没就绪：记录重试次数，避免无限重取
        self._stale_tries = 0
        self._retrying = False
        # 同时只跑一个轮询（切歌时取歌词会阻塞最长 3s）
        self._polling = threading.Event()

        self._local = threading.local()

    # 切歌后最多重取几次（每次轮询一轮，约 500ms），超过就放弃
    STALE_RETRY_LIMIT = 6

    @property
    def api_url(self) -> str:
        return self._api_url

    @api_url.setter
    def api_url(self, value: str):
        self._api_url = value

    def start(self):
        """开始轮询"""
        self._timer.start(self._interval_ms)

    def stop(self):
        """停止轮询"""
        self._timer.stop()
        if self._connected:
            self._connected = False
            self.connection_changed.emit(False)

    # ---------------------------------------------------------------- 内部

    def _session(self) -> requests.Session:
        """每个线程一个 Session（Session 非线程安全）"""
        session = getattr(self._local, "session", None)
        if session is None:
            session = requests.Session()
            self._local.session = session
        return session

    def _poll(self):
        """执行一次轮询（在后台线程中）

        ⚠️ 上一次还没跑完就直接跳过：切歌时要同步取歌词（最长 3s），
        若每 500ms 都无脑再起一个线程，两个线程会同时写 `_last_lyric` /
        `_last_lines`，后结束的那个（往往是旧歌的）会把新歌的覆盖掉。
        """
        if self._polling.is_set():
            return
        self._polling.set()
        threading.Thread(target=self._do_poll, daemon=True).start()

    def _do_poll(self):
        """实际 HTTP 请求"""
        try:
            self._poll_once()
        finally:
            self._polling.clear()

    def _poll_once(self):
        try:
            params = {"filter": self.STATUS_FILTER}
            url = f"{self._api_url}/status?{urlencode(params)}"
            resp = self._session().get(url, timeout=2)
            resp.raise_for_status()
            data = resp.json()

            # 检测歌曲切换 —— 清空缓存并重新获取歌词
            name = data.get("name", "")
            line_text = data.get("lyricLineText", "") or ""
            prev_lyric = self._last_lyric
            prev_lines = list(self._last_lines)

            if name and name != self._last_name:
                # 新歌首次出现才重置重试计数；"因歌词未就绪而重试"不算新歌
                if not self._retrying:
                    self._stale_tries = 0
                self._last_name = name
                self._reset_lyric_cache()
                self._fetch_lyric(name)

                if self._looks_stale(name, line_text, prev_lyric, prev_lines):
                    # 取回来的还是上一首的歌词（洛雪切歌后歌词有延迟）
                    if self._stale_tries < self.STALE_RETRY_LIMIT:
                        self._stale_tries += 1
                        self._retrying = True
                        # 丢掉这份可疑歌词，并让下一轮重新走"切歌"分支
                        self._reset_lyric_cache()
                        self._last_name = None
                    else:
                        # 重试用尽：宁可显示歌名，也不要显示上一首的歌词
                        self._reset_lyric_cache()
                        self._retrying = False
                        self._last_name = name
                else:
                    self._retrying = False

            # /status 不带 lyric 字段；这里补上缓存的内容
            if data.get("lyric"):
                self._last_lyric = data["lyric"]
            data["lyric"] = self._last_lyric or ""
            data["lyric_lines"] = self._last_lines
            data["is_word_by_word"] = self._last_word_by_word

            if not self._connected:
                self._connected = True
                self.connection_changed.emit(True)

            self.status_changed.emit(data)

        except requests.RequestException:
            if self._connected:
                self._connected = False
                self.connection_changed.emit(False)
        except (ValueError, KeyError):
            pass  # JSON 解析失败，忽略

    @classmethod
    def _norm_title(cls, text: str) -> str:
        """归一化歌名/歌词标题：忽略大小写、空白与中英标点

        实测同一首歌在 `/status` 与歌词 `[ti:]` 里写法会不一致，例如
        `Pedujara: Even Immortality Ends` vs `Pedujara Even Immortality's End`
        —— 所以不能直接字符串相等比较。
        """
        return _TITLE_STRIP_RE.sub("", text or "").lower()

    def _looks_stale(self, name: str, line_text: str,
                     prev_lyric: str, prev_lines: list) -> bool:
        """判断刚取回的歌词是不是**上一首的残留**

        三个判据（任一命中即认为残留；都用了偏保守的写法，避免误杀）：
          1. 与上一次取到的原文完全相同 —— 不同歌的完整 LRC 不可能一字不差
          2. 歌词头 `[ti:]` 与当前歌名明显不同
          3. `/status` 给的当前行**出现在上一首的歌词里**、却不在新歌词里
        """
        raw = self._last_lyric or ""
        if not raw:
            # 没取到任何歌词：不是"上一首残留"，交给上层回退到歌名显示
            return False

        if prev_lyric and raw == prev_lyric:
            return True

        m = _TITLE_RE.search(raw)
        if m:
            ti = self._norm_title(m.group(1))
            cur = self._norm_title(name)
            if ti and cur and not self._titles_agree(ti, cur):
                return True

        lt = line_text.strip()
        if lt and prev_lines:
            new_texts = {line.text.strip() for line in self._last_lines}
            if lt not in new_texts:
                old_texts = {line.text.strip() for line in prev_lines}
                if lt in old_texts:
                    return True
        return False

    @staticmethod
    def _titles_agree(a: str, b: str) -> bool:
        """两个归一化标题是否指同一首歌

        不能只做子串判断：实测同一首歌在 `/status` 与歌词 `[ti:]` 里写法不同，
        例如 `Pedujara: Even Immortality Ends` vs `Pedujara Even Immortality's End`
        （差一个 s、冒号、撇号）。所以用相似度，阈值取 0.8：
        真正不同的歌名（如"第一首"/"第二首"）相似度约 0.67，能区分开。
        """
        if a == b or a in b or b in a:
            return True
        return difflib.SequenceMatcher(None, a, b).ratio() >= 0.8

    def _reset_lyric_cache(self):
        self._last_lyric = ""
        self._last_lines = []
        self._last_word_by_word = False
        self._last_has_lxlyric = False

    def _fetch_lyric(self, name: str = ""):
        """取当前歌曲的四条歌词轨

        走 `/lyric-all` 而不是 `/lyric`：多花约 4KB，但一次拿到翻译与逐字轨，
        不必再为翻译单独请求（`/tlyric` 端点并不存在，实测 401）。
        """
        try:
            resp = self._session().get(f"{self._api_url}/lyric-all", timeout=3)
            resp.raise_for_status()
            payload = resp.json()
        except (requests.RequestException, ValueError):
            # /lyric-all 失败时退回只取原文，保证至少能显示歌词
            try:
                resp = self._session().get(f"{self._api_url}/lyric", timeout=3)
                text = resp.text.strip()
                if text:
                    self._last_lyric = text
                    self._last_lines, self._last_word_by_word = parse_lyrics(text)
            except requests.RequestException:
                pass
            return

        plain = payload.get("lyric") if isinstance(payload.get("lyric"), str) else ""
        lx = payload.get("lxlyric") if isinstance(payload.get("lxlyric"), str) else ""

        # 优先逐字轨：它有字级时间，且文本与原文轨一致（实测逐行时间戳与文本都相同）
        if lx.strip() and lx.strip() != plain.strip():
            lines, is_word = parse_lyrics(lx)
            if lines and is_word:
                self._last_lyric = plain or lx
                self._last_lines = lines
                self._last_word_by_word = True
                self._last_has_lxlyric = True
                return

        # 没有逐字轨（或解析失败）：回退标准 LRC
        self._last_lyric = plain
        self._last_lines = parse_lrc(plain) if plain else []
        self._last_word_by_word = False
        self._last_has_lxlyric = bool(lx.strip())
