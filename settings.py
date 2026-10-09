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
}


def _get_settings_path() -> str:
    """获取配置文件路径（exe 同目录 / 源码同目录）"""
    if getattr(sys, 'frozen', False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, "settings.json")


SETTINGS_FILE = _get_settings_path()


def load() -> dict:
    """加载配置，缺失项用默认值补齐"""
    if not os.path.exists(SETTINGS_FILE):
        return dict(DEFAULT_SETTINGS)

    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError):
        data = {}

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
