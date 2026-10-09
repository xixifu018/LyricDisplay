"""LX Music API 客户端 —— 轮询 /status 接口获取播放状态"""

from PyQt5.QtCore import QObject, pyqtSignal, QTimer
import requests
import threading
from urllib.parse import urlencode


class ApiClient(QObject):
    """通过轮询 /status 接口获取播放状态，通过 Qt 信号通知"""

    # 状态变更信号: dict(status, name, singer, progress, duration, lyricLineText, lyric)
    status_changed = pyqtSignal(dict)
    # 连接状态信号: bool
    connection_changed = pyqtSignal(bool)

    def __init__(self, api_url: str, parent=None):
        super().__init__(parent)
        self._api_url = api_url
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._interval_ms = 500
        self._connected = False
        self._last_lyric = None  # 缓存上一次的完整歌词文本
        self._last_name = None   # 缓存上一次的歌曲名（用于检测切歌）

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

    def _poll(self):
        """执行一次轮询（在后台线程中）"""
        threading.Thread(target=self._do_poll, daemon=True).start()

    def _do_poll(self):
        """实际 HTTP 请求"""
        try:
            # 构建请求参数，获取需要的字段
            # 注意：不请求 lyric 字段（整首 LRC 约 4KB），歌词改由 /lyric 单独获取，
            # 轮询载荷可降到约 300B。
            params = {
                "filter": "status,name,singer,albumName,duration,progress,lyricLineText,picUrl"
            }
            url = f"{self._api_url}/status?{urlencode(params)}"
            resp = requests.get(url, timeout=2)
            resp.raise_for_status()
            data = resp.json()

            # 检测歌曲切换 —— 清空缓存并重新获取歌词
            name = data.get("name", "")
            if name and name != self._last_name:
                self._last_name = name
                self._last_lyric = ""      # 清空上一首歌词缓存
                self._fetch_lyric()

            # 如果 /status 返回了 lyric 字段则使用，否则用缓存的
            if data.get("lyric"):
                self._last_lyric = data["lyric"]
            data["lyric"] = self._last_lyric or ""

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

    def _fetch_lyric(self):
        """获取当前歌曲的完整 LRC 歌词"""
        try:
            resp = requests.get(f"{self._api_url}/lyric", timeout=2)
            resp.raise_for_status()
            text = resp.text.strip()
            if text:
                self._last_lyric = text
        except requests.RequestException:
            pass
