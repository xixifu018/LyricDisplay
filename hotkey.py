"""全局热键 —— Windows RegisterHotKey 封装

用系统级热键而非 Qt 快捷键：Qt 快捷键要求窗口有焦点，
而歌词浮窗被锁定时正好是「无焦点 + 点击穿透」状态，Qt 快捷键收不到按键。

线程约束：RegisterHotKey 绑定到**调用线程的消息队列**，因此注册与注销
都必须在 GUI 主线程里做。

WM_HOTKEY 只发给「注册时传入的那个 hwnd」。hwnd 为 0 时消息进入线程队列，
Qt 的事件循环不会派发它（也就无法响应）——所以实时生效的热键必须绑定到
主窗口的 HWND；hwnd=0 仅用于 probe() 这种「注册完立刻注销」的探测场景。
"""

import ctypes
from typing import Optional, Tuple
from ctypes import wintypes

user32 = ctypes.windll.user32

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000        # 按住不放只触发一次

WM_HOTKEY = 0x0312

# probe() 专用的热键 id，取值远离 HotkeyManager 的 1/2/3...，避免自冲突
_PROBE_ID = 0xBFF0

# probe() 的三种结果
STATUS_FREE = "free"            # 可用
STATUS_OWN = "own"              # 本程序自己当前已注册这个组合
STATUS_TAKEN = "taken"          # 被系统或其他程序占用

# 修饰键别名 -> 规范名
_MOD_ALIASES = {
    "CTRL": "Ctrl", "CONTROL": "Ctrl",
    "ALT": "Alt",
    "SHIFT": "Shift",
    "WIN": "Win", "WINDOWS": "Win", "META": "Win", "SUPER": "Win",
}

_MOD_FLAGS = {"Ctrl": MOD_CONTROL, "Alt": MOD_ALT, "Shift": MOD_SHIFT, "Win": MOD_WIN}

# 主键别名 -> 规范名
_KEY_ALIASES = {
    "ESC": "Esc", "ESCAPE": "Esc",
    "RETURN": "Enter", "ENTER": "Enter",
    "SPACE": "Space", "SPACEBAR": "Space",
    "TAB": "Tab", "BACKSPACE": "Backspace",
    "DELETE": "Delete", "DEL": "Delete",
    "INSERT": "Insert", "INS": "Insert",
    "HOME": "Home", "END": "End",
    "PAGEUP": "PgUp", "PGUP": "PgUp",
    "PAGEDOWN": "PgDown", "PGDN": "PgDown",
    "UP": "Up", "DOWN": "Down", "LEFT": "Left", "RIGHT": "Right",
    "PLUS": "+", "MINUS": "-",
}

# 规范名 -> 虚拟键码
_KEY_CODES = {
    "Space": 0x20, "PgUp": 0x21, "PgDown": 0x22, "End": 0x23, "Home": 0x24,
    "Left": 0x25, "Up": 0x26, "Right": 0x27, "Down": 0x28,
    "Insert": 0x2D, "Delete": 0x2E,
    "0": 0x30, "1": 0x31, "2": 0x32, "3": 0x33, "4": 0x34,
    "5": 0x35, "6": 0x36, "7": 0x37, "8": 0x38, "9": 0x39,
    "A": 0x41, "B": 0x42, "C": 0x43, "D": 0x44, "E": 0x45, "F": 0x46,
    "G": 0x47, "H": 0x48, "I": 0x49, "J": 0x4A, "K": 0x4B, "L": 0x4C,
    "M": 0x4D, "N": 0x4E, "O": 0x4F, "P": 0x50, "Q": 0x51, "R": 0x52,
    "S": 0x53, "T": 0x54, "U": 0x55, "V": 0x56, "W": 0x57, "X": 0x58,
    "Y": 0x59, "Z": 0x5A,
    "Esc": 0x1B, "Tab": 0x09, "Backspace": 0x08, "Enter": 0x0D,
    "-": 0xBD, "+": 0xBB,
}
# F1~F24
for _i in range(1, 25):
    _KEY_CODES[f"F{_i}"] = 0x70 + _i - 1
del _i


def _parse(text: str):
    """解析热键文本 -> (改键值 int, 规范文本 str)；无法识别返回 None

    规范文本固定为「修饰键按 Ctrl/Alt/Shift/Win 顺序 + 主键」，
    这样 "alt+ctrl+l" 与 "Ctrl+Alt+L" 会被判定为同一个热键。
    """
    if not text or not isinstance(text, str):
        return None

    parts = [p.strip() for p in text.split("+") if p.strip()]
    if not parts:
        return None

    mods, key_name = [], None
    for idx, part in enumerate(parts):
        alias = _MOD_ALIASES.get(part.upper())
        if alias and idx < len(parts) - 1:
            if alias not in mods:
                mods.append(alias)
            continue
        # 主键只允许出现一次，且必须在最后（"Ctrl+L+K" 之类的组合不支持）
        if key_name is not None or idx != len(parts) - 1:
            return None
        key_name = _KEY_ALIASES.get(part.upper(), part.upper())

    if key_name is None or key_name not in _KEY_CODES:
        return None

    mods.sort(key=lambda m: ["Ctrl", "Alt", "Shift", "Win"].index(m))
    return (
        sum(_MOD_FLAGS[m] for m in mods) | MOD_NOREPEAT,
        "+".join(mods + [key_name]),
    )


def parse(text: str):
    """解析为 (改键值, 规范文本)；非法返回 (None, None)"""
    parsed = _parse(text)
    if parsed is None:
        return None, None
    return parsed


def is_valid(text: str) -> bool:
    """文本是否为可用的热键"""
    return _parse(text) is not None


def normalize(text: str) -> str:
    """返回规范文本；非法返回空串"""
    parsed = _parse(text)
    return parsed[1] if parsed else ""


def probe(text: str, own_hotkeys: Optional[list] = None) -> Tuple[str, str]:
    """只检测不占用：该热键此刻能否被成功注册

    返回 (状态, 说明)，状态为 STATUS_FREE / STATUS_OWN / STATUS_TAKEN。

    系统没有「这个热键被谁占了」的查询接口，只能试注册再立刻注销。

    **本程序自己的热键必须由调用方通过 own_hotkeys 声明**，不能靠再注册一次
    来推断：实测 RegisterHotKey 的限制是**整个进程**级别的（同一进程换 hwnd、
    换 id 都注册不上），所以"自己再注册一次看行不行"这条路走不通。
    调用方应传「本程序确实注册成功」的规范化热键文本。
    """
    parsed = _parse(text)
    if parsed is None:
        return STATUS_TAKEN, "无法识别的热键，例：Ctrl+Alt+L"
    mods, norm = parsed

    # 声明进来的自身热键也要规范化后再比：否则 "alt+ctrl+shift+f8" 这种
    # 写法匹配不上，会被误报成"被其他程序占用"
    own = set()
    for item in (own_hotkeys or []):
        own.add(normalize(str(item)) or str(item))

    if user32.RegisterHotKey(None, _PROBE_ID, mods, key_code(text)):
        user32.UnregisterHotKey(None, _PROBE_ID)
        # probe 用的是线程级 hwnd(None)，与主窗口的 hwnd 不同：
        # 实测 RegisterHotKey 允许同一进程用不同 hwnd/id 重复注册同一组合，
        # 所以"注册得上 + 调用方声明是自己的"= 本程序另一个窗口持有它。
        # （调用方总是如实声明，这个歧义在实际使用中不会出现）
        if norm in own:
            return STATUS_OWN, "当前已在用（本程序自己的热键）"
        return STATUS_FREE, "可用"

    if norm in own:
        return STATUS_OWN, "当前已在用（本程序自己的热键）"
    return STATUS_TAKEN, "已被系统或其他程序占用"


def key_code(text: str) -> int:
    """取热键的主键虚拟键码；文本非法返回 0"""
    parts = [p.strip() for p in text.split("+") if p.strip()]
    if not parts:
        return 0
    name = _KEY_ALIASES.get(parts[-1].upper(), parts[-1].upper())
    return _KEY_CODES.get(name, 0)


class HotkeyManager:
    """全局热键注册表

    每个热键占一个 id（1 起递增，互不重复）。注册失败（冲突）时
    register() 返回 None，由调用方决定如何告知用户。
    """

    def __init__(self):
        self._hwnd = None
        self._registry = {}      # id -> (规范文本, 回调)
        self._next_id = 1

    # ------------------------------------------------------------
    #  生命周期
    # ------------------------------------------------------------

    def set_window(self, hwnd: int):
        """绑定消息接收窗口（必须在注册任何热键之前调用）"""
        self._hwnd = hwnd

    def register(self, text: str, callback) -> Optional[int]:
        """注册一个热键；成功返回 id，冲突或非法返回 None"""
        parsed = _parse(text)
        if parsed is None or self._hwnd is None:
            return None
        mods, norm = parsed

        hid = self._next_id
        if not user32.RegisterHotKey(
            wintypes.HWND(self._hwnd), hid, mods, key_code(text)
        ):
            return None

        self._next_id += 1
        self._registry[hid] = (norm, callback)
        return hid

    def unregister(self, hid: int):
        """注销单个热键"""
        if hid in self._registry:
            user32.UnregisterHotKey(wintypes.HWND(self._hwnd), hid)
            self._registry.pop(hid, None)

    def unregister_all(self):
        """注销全部热键（窗口关闭前必须调用，否则 id 会被系统占着）"""
        for hid in list(self._registry):
            user32.UnregisterHotKey(wintypes.HWND(self._hwnd), hid)
        self._registry.clear()

    def handles(self, event_type, message) -> bool:
        """处理 WM_HOTKEY 原生气消息；是否已消费"""
        if event_type != "windows_generic_MSG":
            return False
        try:
            msg = ctypes.cast(int(message), ctypes.POINTER(wintypes.MSG)).contents
        except (TypeError, ValueError):
            return False

        if msg.message != WM_HOTKEY:
            return False

        entry = self._registry.get(int(msg.wParam))
        if entry is None:
            return False

        entry[1]()
        return True
