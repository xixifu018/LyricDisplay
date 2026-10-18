"""窗口层级 —— 置顶 / 正常 / 置底三档，以及"不抢焦点"与"点击穿透"两个开关

与「锁定」的区别（两者都涉及"点击"，但目标不同，别混）：

    |          | 锁定（主窗口的 _set_locked） | 本模块的层级            |
    |----------|-----------------------------|------------------------|
    | 鼠标穿透 | 有（不可点击）               | 置顶/置底都不加穿透      |
    | z 序     | 由「置顶」决定               | **置顶 / 正常 / 置底**  |
    | 目的     | 防误触，位置不动             | 决定被谁遮挡            |

三档层级是**互斥**的，由主窗口保证同一时刻只有一个开关为真：

    - 置顶：`HWND_TOPMOST`，永远盖在普通窗口之上（默认）
    - 正常：`HWND_NOTOPMOST`，普通窗口之间按激活顺序排
    - 置底：`HWND_BOTTOM`，所有普通窗口都能盖住它

⚠️ Windows **没有"常驻最底"的窗口样式**。`SetWindowPos(.., HWND_BOTTOM, ..)`
只是"放到底部一次"：之后新建的窗口会叠在它上面（正合需求），但
**窗口激活、"显示桌面"、最小化其他窗口等操作可能把它重新顶上来**，
所以必须在那些时机重新压底 —— 主窗口用 `_apply_zorder()` 提供这个入口。

⚠️ 置顶同理不是"永久生效"：别的置顶窗口出现时可能把它挤下去，
所以切窗口/激活后也要补一次。

**注意：桌面图标盖不住置底窗口。** 图标与壁纸在另一条更深的窗口分支里，
z 序跨不过去（实测：图标像素存活 0，详见 AGENTS.md §5.1.3）。
曾经试过"把窗口创建成壁纸层 WorkerW 的子窗口"来做到图标遮挡，
**那条路已放弃并移除** —— 与动态壁纸抢同一块绘制表面，会导致整个桌面闪烁。
"""

import sys

# ---- Win32 常量 ----

GWL_EXSTYLE = -20

WS_EX_NOACTIVATE = 0x08000000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TOPMOST = 0x00000008

# SetWindowPos 的 hWndInsertAfter 特殊值
HWND_BOTTOM = 1
HWND_NOTOPMOST = -2
HWND_TOPMOST = -1

# z 序操作的 flag 组合。
# `SWP_NOOWNERZORDER` 是参考 Rainmeter 的 `ZPOS_FLAGS` 补上的
# （rainmeter/Library/System.cpp）：改 z 序不该顺带重排同带其他窗口的顺序。
# `SWP_NOSENDCHANGING` 避免触发 `WM_WINDOWPOSCHANGING`，减少与 shell 的交互。
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_NOOWNERZORDER = 0x0200
SWP_NOSENDCHANGING = 0x0400
ZPOS_FLAGS = (SWP_NOMOVE | SWP_NOSIZE | SWP_NOOWNERZORDER
              | SWP_NOACTIVATE | SWP_NOSENDCHANGING)

# 只在 Windows 上加载；其它平台保持 available() == False，调用全部变成空操作
if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.windll.user32
    _user32.SetWindowPos.argtypes = [
        wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, ctypes.c_uint,
    ]
    _user32.SetWindowPos.restype = wintypes.BOOL
    # 64 位下必须声明这两个，否则句柄会被截断成 32 位
    _user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.GetWindowLongW.restype = ctypes.c_long
    _user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
    _user32.SetWindowLongW.restype = ctypes.c_long

    # hWndInsertAfter 用 c_void_p 表示：-1/-2 要先包成有符号指针再传，
    # 直接把 int 传给 HWND 形参在部分 ctypes 版本上会 OverflowError
    _HWND_BOTTOM = wintypes.HWND(HWND_BOTTOM)
    _HWND_NOTOPMOST = ctypes.c_void_p(HWND_NOTOPMOST)
    _HWND_TOPMOST = ctypes.c_void_p(HWND_TOPMOST)
else:  # pragma: no cover - 非 Windows 只用于跑测试
    _user32 = None


def available() -> bool:
    """当前平台是否支持窗口层级调整"""
    return _user32 is not None


def _ex_style(hwnd: int) -> int:
    return _user32.GetWindowLongW(wintypes.HWND(hwnd), GWL_EXSTYLE)


def _set_ex_style(hwnd: int, style: int) -> None:
    _user32.SetWindowLongW(wintypes.HWND(hwnd), GWL_EXSTYLE, ctypes.c_long(style))


def _set_pos(hwnd: int, insert_after) -> bool:
    if not available() or not hwnd:
        return False
    try:
        ok = _user32.SetWindowPos(
            wintypes.HWND(hwnd), insert_after,
            0, 0, 0, 0,
            ZPOS_FLAGS,
        )
        return bool(ok)
    except OSError:
        return False


def bring_to_front(hwnd: int) -> bool:
    """置顶：放到置顶带的最前（`HWND_TOPMOST`）

    会把窗口的 `WS_EX_TOPMOST` 打开。不改变尺寸/位置，也不抢焦点。
    """
    return _set_pos(hwnd, _HWND_TOPMOST)


def send_to_normal(hwnd: int) -> bool:
    """回到正常层级：去掉置顶（`HWND_NOTOPMOST`）

    窗口不再盖住别人的普通窗口，但仍会盖住「置底」的窗口。
    """
    return _set_pos(hwnd, _HWND_NOTOPMOST)


def send_to_bottom(hwnd: int) -> bool:
    """置底：放到普通带的最后（`HWND_BOTTOM`），让所有普通窗口盖住它

    返回是否成功。句柄无效或平台不支持时返回 False（调用方不必特殊处理，
    静默失败即可 —— 托盘与热键仍然是可用出口）。
    """
    return _set_pos(hwnd, _HWND_BOTTOM)


def is_topmost(hwnd: int) -> bool:
    """当前是否处于置顶带"""
    if not available() or not hwnd:
        return False
    try:
        return bool(_ex_style(hwnd) & WS_EX_TOPMOST)
    except OSError:
        return False


def set_no_activate(hwnd: int, enabled: bool = True) -> bool:
    """加/去 WS_EX_NOACTIVATE

    作用：点击窗口时**不抢焦点**。置底模式下窗口在桌面层，抢焦点会让
    "刚点过的窗口失去焦点"，体验上很突兀。

    注意：这只是"不激活"，**不阻止鼠标消息**。要真正做到点击穿透，
    得另加 WS_EX_TRANSPARENT（见 `set_click_through`）。
    """
    if not available() or not hwnd:
        return False
    try:
        style = _ex_style(hwnd)
        new_style = (style | WS_EX_NOACTIVATE) if enabled else (style & ~WS_EX_NOACTIVATE)
        if new_style != style:
            _set_ex_style(hwnd, new_style)
        return True
    except OSError:
        return False


def set_click_through(hwnd: int, enabled: bool = True) -> bool:
    """加/去 WS_EX_TRANSPARENT（点击穿透）

    置顶/置底都**不用**这个：用户要的是"能被遮挡"，点一下还能拖动更实用。
    真正"不可点击"的是锁定态，它在主窗口里用 `Qt.WindowTransparentForInput`
    实现（顺便也挡住拖动）。这里保留能力，供以后需要时用。

    直接改 ex-style 是为了**不调用 setWindowFlags** —— 那会隐藏并重建窗口，
    位置、动画、WA_ShowWithoutActivating 都要重新料理。
    """
    if not available() or not hwnd:
        return False
    try:
        style = _ex_style(hwnd)
        new_style = (style | WS_EX_TRANSPARENT) if enabled else (style & ~WS_EX_TRANSPARENT)
        if new_style != style:
            _set_ex_style(hwnd, new_style)
        return True
    except OSError:
        return False


def describe(hwnd: int) -> dict:
    """读取当前窗口状态，用于验证与排错"""
    if not available() or not hwnd:
        return {"available": False}
    try:
        style = _ex_style(hwnd)
    except OSError:
        return {"available": False, "error": "GetWindowLongW failed"}
    return {
        "available": True,
        "hwnd": hwnd,
        "topmost": bool(style & WS_EX_TOPMOST),
        "no_activate": bool(style & WS_EX_NOACTIVATE),
        "click_through": bool(style & WS_EX_TRANSPARENT),
        "ex_style": hex(style & 0xFFFFFFFF),
    }
