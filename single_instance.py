"""单实例限制 —— 用命名互斥体保证同一时间只跑一个 LyricDisplay

为什么用互斥体而不是"查进程名"：
  进程名检查有竞态（两个实例同时启动会都通过检查），而且包成 exe 后
  进程名可能被改名。CreateMutexW 是内核对象，创建与判定是一步原子操作。

锁的生命周期跟着进程走：进程一退出，内核自动释放互斥体，
不会留下需要手工清理的锁文件。
"""

import ctypes
import os
import sys
from ctypes import wintypes

# 固定名字（不带安装路径），这样从源码跑和跑 exe 也互斥，
# 避免同时出现两个歌词浮窗抢同一个洛雪 API
MUTEX_NAME = "Global\\LyricDisplay_SingleInstance"

_ERROR_ALREADY_EXISTS = 183

_kernel32 = ctypes.windll.kernel32

# 句柄必须留到进程结束：一旦释放，互斥体就没了，限制也就失效
_handle = None
_held_name = None


def acquire(name: str = MUTEX_NAME) -> bool:
    """尝试取得单实例锁；已有实例在跑则返回 False"""
    global _handle, _held_name

    # 本进程已经持有**同一个名字**：直接算成功。
    # 否则第二次 CreateMutexW 会返回 ERROR_ALREADY_EXISTS（锁是自己持有的），
    # 把自己误判成"已有实例在运行"。
    # 必须比对名字：若只判断 _handle 非空，换个名字调用会被静默跳过检查。
    if _handle is not None and _held_name == name:
        return True

    _kernel32.CreateMutexW.restype = wintypes.HANDLE
    _kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL,
                                       wintypes.LPCWSTR]
    handle = _kernel32.CreateMutexW(None, False, name)
    if not handle:
        # 拿不到锁句柄（极端情况）时不要拦住用户，宁可允许多开
        return True

    if _kernel32.GetLastError() == _ERROR_ALREADY_EXISTS:
        # 别的进程已经持有这个名字，关掉我们刚拿到的句柄
        _kernel32.CloseHandle(wintypes.HANDLE(handle))
        return False

    _handle = handle
    _held_name = name
    return True


def notify_already_running(title: str = "LyricDisplay",
                           text: str = "LyricDisplay 已经在运行了。\n\n"
                                       "请使用已在运行的窗口（或托盘图标），"
                                       "不要重复启动。"):
    """用系统消息框提示用户（GUI 程序没有控制台可看）

    故意不用 QMessageBox：这里要在 QApplication 建起来之前就能调用，
    否则第二实例还会闪一下窗口、占用一次 Qt 初始化。
    设 DSH_LYRIC_NO_DIALOG=1 可跳过弹窗（自动化测试用，否则会阻塞）。
    """
    if os.environ.get("DSH_LYRIC_NO_DIALOG"):
        print(text, file=sys.stderr)
        return
    try:
        ctypes.windll.user32.MessageBoxW(None, text, title, 0x40)  # MB_ICONINFORMATION
    except Exception:
        print(text, file=sys.stderr)


def ensure_single_instance() -> bool:
    """检查并占用单实例锁

    返回 True 表示可以继续启动；False 表示已有实例，调用方应直接退出。
    """
    if acquire():
        return True
    notify_already_running()
    return False
