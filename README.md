# LyricDisplay — 洛雪音乐桌面歌词显示

基于 [LX Music（洛雪音乐）](https://github.com/lyswhut/lx-music-desktop) 开放 API 的桌面歌词浮窗，可吸附屏幕边缘，支持歌曲封面显示和真实音频频谱可视化。

## 效果预览

- 紧凑长条形浮窗，吸附屏幕顶部/底部
- 左侧圆形歌曲封面，播放时自动旋转，**点击封面切换播放/暂停**
- 单行 / 双行歌词显示模式，可切换
- 单行模式：歌词切换时从下方升起动画
- 双行模式：当前歌词 + 下一句预览，整行向上滚动
- 文字带发光阴影，清晰可读
- 半透明背景 + 可选七彩频谱条（**真实音频驱动**）
- 鼠标悬停显示 ♫ 按钮一键打开洛雪音乐，未安装则跳转官网
- 可视化设置面板：字号 / 颜色 / 透明度 / 封面 / 频谱 / 安装目录

## 运行方式

### 直接运行（无需安装）

从 [Releases](../../releases) 下载 `LyricDisplay.exe`，双击运行。首次运行会在同目录生成 `settings.json`。

> 仓库源码不含编译产物；想自己打包见 `LyricDisplay.spec`（`pyinstaller LyricDisplay.spec`）。

### 从源码运行

```bash
pip install PyQt5 requests sounddevice soundcard numpy
python main.py
```

### 前提

- LX Music 需开启**开放 API 服务**（设置 → 基本设置 → 开放 API，默认端口 23330）
- 频谱和封面在播放中自动显示，暂停/停止时自动隐藏

---

## 项目结构

```
lyric_display/
├── main.py               # 入口
├── main_window.py        # 主窗口（无边框、置顶、边缘吸附、交互）
├── api_client.py         # LX Music API 客户端（轮询 + 歌词 + 封面）
├── lyrics_parser.py      # LRC 歌词解析器
├── audio_capture.py      # WASAPI 音频捕获 + FFT 频谱分析
├── spectrum_widget.py    # 频谱可视化（48 根七彩条 + 峰值亮点）
├── flip_label.py         # 歌词标签（升起 / 滚动动画）
├── round_cover.py        # 圆形封面 + 旋转动画 + 点击播放控制
├── settings.py           # 配置管理（JSON 持久化，exe 同目录）
├── settings_dialog.py    # 可视化设置面板
└── requirements.txt      # 依赖清单
```

---

## 核心原理

### 歌词获取与同步

```
LX Music（本地 HTTP API :23330）
    │
    ├── GET /status?filter=... → 状态、进度、当前歌词、封面 URL
    ├── GET /lyric             → 完整 LRC 歌词文本
    │
    ▼
api_client.py（500ms 轮询）
    │
    ├── LRC 解析 → 时间标签有序列表
    ├── 二分查找当前行 + 下一行
    ├── 本地 200ms 进度推进
    ├── 切歌自动清空缓存 → 重新获取
    │
    ▼
flip_label.py（升起 / 滚动动画）
```

### 音频频谱

```
Windows WASAPI Loopback（soundcard 库）
    │
    ▼  捕获系统音频输出（44.1kHz / 2048 samples）
audio_capture.py
    │
    ├── 汉宁窗 → FFT → 幅度谱
    ├── 对数刻度 → 48 个频率柱（20Hz~16kHz）
    ├── log1p 压缩 → 频率加权 → min-max 归一化 → 指数映射
    ├── 上升快、下落慢的平滑策略
    │
    ▼  Qt 信号
spectrum_widget.py → 七彩渐变条 + 白色峰值亮点
```

### 封面显示与播放控制

```
API 返回 picUrl → QNetworkAccessManager 异步下载
    │
    ▼
round_cover.py
    ├── QPainterPath 圆形裁剪 + 白色细边框
    ├── 播放中 ~1.5°/帧旋转动画，暂停静止
    └── 鼠标点击 → API 切换播放/暂停
```

### 窗口吸附

- 无边框置顶浮窗（`FramelessWindowHint | WindowStaysOnTopHint | Tool`）
- 拖拽靠近屏幕边缘 < 20px 自动吸附，保持 X 坐标不变
- 拖离 > 80px 解除吸附，双击切换顶部/底部

### 歌词动画

- **单行模式（升起）：** 旧词渐隐 + 新词从下方滑入，280ms `OutCubic`
- **双行模式（滚动）：** 上方当前词（亮色）+ 下方下一句（半透明），整体上滚

---

## 功能清单

| 功能 | 操作 |
|------|------|
| 边缘吸附 | 拖动窗口靠近屏幕顶部/底部 |
| 切换吸附边 | 双击窗口 / 右键菜单 |
| 单行/双行切换 | 右键 → "双行歌词" / "单行歌词" |
| 调整字号 | 右键 → "字号 +" / "字号 −" |
| 可视化设置 | 右键 → "设置..." |
| 移动窗口 | 按住拖拽 |
| 关闭 | 悬停时 ✕ / 右键 → 退出 |
| 打开洛雪音乐 | 悬停时 ♫ / 右键 → 打开洛雪音乐 |
| 封面旋转 | 播放时自动旋转，暂停静止 |
| 播放/暂停 | **点击封面** |
| 频谱显示 | 播放时启动，设置面板可关闭 |

---

## 设置面板

右键 → "设置..." 打开：

| 设置项 | 说明 |
|--------|------|
| 字号 | 6~48 数字微调 |
| 文字颜色 | 8 种预设 + 自定义取色器 |
| 背景颜色 | 8 种预设 + 自定义取色器 |
| 背景透明度 | 滑块 + 8 个快捷百分比 |
| 显示歌曲封面 | 复选框 |
| 显示频谱背景 | 复选框 |
| 洛雪音乐安装目录 | 手动输入或浏览选择（留空=自动检测） |
| 洛雪音乐官网 → | 按钮，跳转官网 |

所有设置**立即生效并写入 `settings.json`**，下次启动自动恢复。

## 配置说明

`settings.json`（exe 同目录，自动生成）：

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `api_host` | `127.0.0.1` | LX Music API 地址 |
| `api_port` | `23330` | LX Music API 端口 |
| `dock_edge` | `top` | 吸附边：`top` / `bottom` |
| `font_size` | `8` | 歌词字号 |
| `text_color` | `#FFFFFF` | 歌词颜色 |
| `bg_color` | `#000000` | 背景颜色 |
| `bg_opacity` | `0.45` | 背景透明度（0~1） |
| `window_width` | `600` | 窗口固定宽度（px） |
| `display_mode` | `single` | 显示模式：`single` / `double` |
| `show_cover` | `true` | 是否显示封面 |
| `show_spectrum` | `true` | 是否显示频谱 |
| `lxmusic_path` | `""` | 洛雪音乐安装目录（留空=自动检测） |

## 技术栈

- **Python 3.13** + **PyQt5** — 桌面 GUI
- **soundcard** — WASAPI 音频回环捕获
- **sounddevice** — 音频捕获回退方案
- **numpy** — FFT 频谱分析
- **requests** — HTTP 轮询 LX Music API
- **PyInstaller** — 打包为独立 exe

## 许可证

代码采用 [MIT](LICENSE) 许可。

> ⚠️ 仓库中的角色插画 `whalegirl.png`、应用图标 `lyrics-display-logo.*` 与测试用专辑封面
> `test_cover.jpg` 是**第三方素材**，著作权不属于本项目作者，**不在 MIT 授权范围内**。
> 详见 [NOTICE](NOTICE)。再分发或商用前请自行取得原作者许可。

---

## 相关：DSH Web GUI 插件

本仓库的 [`plugins/dsh-whalegirl-lyric/`](plugins/dsh-whalegirl-lyric/README.md) 是一个
**DSH（DeepSeek Harness）Web GUI 插件**，把同样的歌词气泡搬进了 harness 界面里：

- 右下角浮窗，鲸鱼娘 + 右上角气泡歌词，可拖动
- 支持播放控制（上一首 / 播放暂停 / 下一首）、歌曲封面、翻译歌词
- 通过 SSE 推送即时响应切歌，见[插件说明](plugins/dsh-whalegirl-lyric/README.md)

它与 `LyricDisplay` 共用同一套洛雪 API 对接思路（含 LRC 解析与端点映射），但运行环境完全不同：
一个是 PyQt5 原生窗口，另一个是浏览器里的插件 bundle。
