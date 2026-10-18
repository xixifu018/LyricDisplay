"""配置管理模块 —— JSON 文件持久化"""

import json
import os
import sys

DEFAULT_SETTINGS = {
    "api_host": "127.0.0.1",
    "api_port": 23330,
    "dock_edge": "top",
    "font_size": 8,
    "text_color": "#FFFFFF",
    "bg_color": "#000000",
    "bg_opacity": 0.45,
    "window_width": 600,
    "display_mode": "single",
    "show_spectrum": True,
    "show_cover": True,
    "lxmusic_path": "",        # 洛雪音乐安装目录（留空=自动检测）
    # 逐字歌词：洛雪返回 lxlyric（Any Listen 逐字轨）时，按字扫过上色。
    # 纯 LRC 曲目没有字级时间，此开关无效（仍是整行切换）。
    "show_word_by_word": True,
    # ---- 窗口锁定（防误触）----
    # 注意：锁定状态本身**不持久化**（每次启动都是未锁定），
    # 避免锁定后重启、用户不知道如何解锁。这里只存配置。
    "unlock_hover_seconds": 2,              # 鼠标悬浮几秒解锁（1~10）
    "hotkey_lock": "Ctrl+Alt+L",            # 锁定
    "hotkey_unlock": "Ctrl+Alt+U",          # 解锁
    "show_tray": True,                      # 显示托盘图标（锁定时的兜底出口）
    # ---- 窗口层级（置顶 / 正常 / 置底，三档互斥）----
    # 同一时刻只有一档生效；两个开关都关 = 正常层级。
    # 与「锁定」的区别：锁定是"不可点击"，层级只管"被谁遮挡"。
    # 这两个开关**可以持久化**（与 locked 相反）：它们有托盘 + 热键两个出口，
    # 即使重启后仍是置顶/置底也不会把用户困住。
    "always_on_top": True,                  # 窗口置顶（默认，保持原有行为）
    "bottom_mode": False,                   # 窗口置底（原「壁纸模式」）
    "hotkey_top": "Ctrl+Alt+T",             # 切换窗口置顶
    "hotkey_bottom": "Ctrl+Alt+B",          # 切换窗口置底
}

# 旧版配置键 -> 新键。改名后要迁移，否则用户原来的开关和热键会被重置成默认值。
_RENAMED_KEYS = {
    "wallpaper_mode": "bottom_mode",
    "hotkey_wallpaper": "hotkey_bottom",
}


def _get_settings_path() -> str:
    """获取配置文件路径（exe 同目录 / 源码同目录）"""
    if getattr(sys, 'frozen', False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, "settings.json")


SETTINGS_FILE = _get_settings_path()


def migrate(data: dict) -> dict:
    """把旧版配置键迁移到新键（原地修改并返回）

    只做单向迁移：旧键存在、新键不存在时才搬过去；搬完删掉旧键，
    避免下次启动又把它当"新键缺失"重复搬运，覆盖用户后来改的值。
    """
    for old, new in _RENAMED_KEYS.items():
        if old in data:
            if new not in data:
                data[new] = data[old]
            data.pop(old, None)
    return data


def load() -> dict:
    """加载配置，缺失项用默认值补齐"""
    if not os.path.exists(SETTINGS_FILE):
        return dict(DEFAULT_SETTINGS)

    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError):
        data = {}

    # ⚠️ 迁移必须在 setdefault 之前：否则旧键 wallpaper_mode 会被当成
    # "未知键"留在文件里，而新键 bottom_mode 被默认值 False 占掉，
    # 用户原来的"置底已开启"就丢了。
    migrate(data)

    for key, value in DEFAULT_SETTINGS.items():
        data.setdefault(key, value)

    return data


def save(settings: dict):
    """保存配置到文件"""
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)


def get_api_url(settings: dict) -> str:
    """返回 LX Music API 基础 URL"""
    return f"http://{settings['api_host']}:{settings['api_port']}"
