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

### 单实例限制

同一时间只允许跑一个 LyricDisplay：用**命名互斥体**（`CreateMutexW`）判定，
重复启动会弹一个提示框然后立刻退出（退出码 0）。

- 为什么不用"查进程名"：进程名检查有竞态（两个实例同时启动会**都**通过检查），
  而且打包成 exe 后进程名可能被改。互斥体是内核对象，创建与判定是一步原子操作。
- 锁的释放不用管：进程一退出内核自动回收，不会留下需要手工清理的锁文件。
- 从源码跑（`main.py`）和跑 exe 用的是**同一个**互斥体名，因此两者也互斥 ——
  避免同时出现两个歌词浮窗去抢同一个洛雪 API。
- 检查放在 `QApplication` 创建**之前**：第二实例连 Qt 都不会初始化，
  既不会闪一下窗口，也不会短暂占用音频设备。

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
├── main_window.py        # 主窗口（无边框、置顶、边缘吸附、交互、锁定）
├── api_client.py         # LX Music API 客户端（轮询 + 歌词 + 封面）
├── lyrics_parser.py      # LRC 歌词解析器
├── hotkey.py             # 全局热键（Windows RegisterHotKey 封装 + 冲突检测）
├── single_instance.py    # 单实例限制（命名互斥体）
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

### 窗口锁定（防误触）

开着浮窗打游戏时，鼠标会频繁扫过窗口导致误点击/误拖动。锁定后解决这个问题：

```
锁定 → 窗口加 Qt.WindowTransparentForInput
         │
         ├── 鼠标消息不再投递给本窗口 → 点击/拖动直接落到下面的程序
         └── 拖动、双击换边、右键菜单、点封面全部失效
```

**解锁有三条路**（任选其一，互为保险）：

| 方式 | 实现 | 说明 |
|------|------|------|
| 鼠标悬浮 N 秒 | 100ms 轮询 `GetCursorPos` 判断光标是否在窗口内 | 秒数在设置面板里配（1~10 秒） |
| 全局热键 | `RegisterHotKey` + `WM_HOTKEY` | 默认锁定 `Ctrl+Alt+L` / 解锁 `Ctrl+Alt+U`，**可在设置面板改，并实时检测冲突** |
| 托盘图标 | `QSystemTrayIcon` 右键菜单 | 最后兜底：即使热键冲突、悬浮失效也能解锁 |

**为什么悬浮解锁要靠轮询而不是 `enterEvent`**：加 `WindowTransparentForInput` 后窗口
收不到鼠标事件，`enterEvent` / `leaveEvent` 都不会再来 —— 只能主动查询光标位置。

**为什么加锁后要求"光标先离开窗口一次"**：从右键菜单点"锁定"时光标正停在窗口上，
若立刻开始计时就会马上自动解锁。因此必须先离开窗口才进入计时（`hover_unlock_step`）。

### 热键冲突检测的两个层次

系统没有「这个热键被谁占了」的查询接口，只能**试注册再立刻注销**（`hotkey.probe()`）。
但它查不出"自身占用"，所以要分两层：

| 层次 | 问题 | 处理 |
|------|------|------|
| 跨进程 | 被别的程序（游戏、聊天工具）占用 | `probe()` 失败 → 红字"已被系统或其他程序占用" |
| **同进程** | 两个热键框填成**同一个组合** | 单独比对两个框的规范化值 → 红字"与解锁热键重复" |

第二层必须自己判：Windows 允许同一进程用**不同 id** 注册同一个组合键，
而 `probe()` 正是用独立 id 去试注册的，所以它探测不到自身占用。
真出现重复时后果很实际：锁定键会失效（只会锁、永远不会解）。

**锁定状态不持久化**：每次启动都是未锁定，避免出现"锁着启动、用户不知道怎么解锁"的死局。
可配置项只有解锁秒数与两个热键，存在 `settings.json` 里。

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
| 锁定防误触 | 右键 → "锁定窗口" / 锁定热键 / 设置面板"立即锁定窗口" |
| 解除锁定 | 鼠标悬浮数秒 / 解锁热键 / 托盘菜单 |

---

## 设置面板

右键 → "设置..." 打开：

| 设置项 | 所在页 | 说明 |
|--------|--------|------|
| 字号 | 外观 | 6~48 数字微调 |
| 文字颜色 | 外观 | 8 种预设 + 自定义取色器 |
| 背景颜色 | 外观 | 8 种预设 + 自定义取色器 |
| 背景透明度 | 外观 | 滑块 + 8 个快捷百分比 |
| 显示歌曲封面 | 功能 | 复选框 |
| 显示频谱背景 | 功能 | 复选框 |
| 洛雪音乐安装目录 | 功能 | 手动输入或浏览选择（留空=自动检测） |
| 洛雪音乐官网 → | 功能 | 按钮，跳转官网 |
| 鼠标悬浮解锁 | 锁定 | 1~10 秒数字微调 |
| 锁定 / 解锁热键 | 锁定 | 组合键录入框，**实时检测冲突**（被占用时红字提示） |
| 显示托盘图标 | 锁定 | 复选框（锁定后的兜底出口） |
| 立即锁定窗口 | 锁定 | 按钮，关掉面板即生效 |

面板按功能分为**外观 / 功能 / 锁定**三页，宽度固定 340，高度由代码按**最高的那一页**
自动算出（`_fit_height()`，当前约 500px），因此切换页签时窗口大小不变。

> 高度不写死：先按各页 `sizeHint` 估一个值，设上去后再量出页签栏的真实高度并按缺口
> 迭代补齐。手填魔数在换字体或换 DPI 后很容易把"使用说明"最后一行裁掉。

> **样式不依赖层叠。** 每个控件都挂自己的样式表（`_apply_widget_styles()`），
> 不再依赖对话框样式表的继承。原因有两个真实故障：
> 1. 外观页的标签曾去问系统调色板，解析出 `WindowText=(0,0,0)` 纯黑，
>    在黑色底上整页文字**完全看不见**；
> 2. 统一涂改按钮样式时把 `_ColorPicker` 色块的**内联样式覆盖**了，
>    彩色圆点变成黑方块。现在会跳过自带样式的控件。
>
> 界面字体**显式指定**（优先 `Microsoft YaHei UI`，回退 微软雅黑 / SimHei，10pt）。
> 也不能依赖系统默认：Qt 5.15 在 Windows 上取的是 `DEFAULT_GUI_FONT`，
> 本机实测为「SimSun 12px」→ 整个对话框被渲染成**宋体 7pt**，小到看不清。
>
> 透明度快捷百分比按钮分**两行各 4 个**：挤在一行时 8 个按钮共需约 384px，
> 而页内只有约 300px，布局会把它们压到 34px（文字需 44px），"10%" 被裁成 "|0%"。

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
| `unlock_hover_seconds` | `2` | 锁定后鼠标悬浮几秒解锁（1~10） |
| `hotkey_lock` | `"Ctrl+Alt+L"` | 锁定热键 |
| `hotkey_unlock` | `"Ctrl+Alt+U"` | 解锁热键 |
| `show_tray` | `true` | 是否显示托盘图标 |

> 锁定状态本身**不写入** `settings.json`：每次启动都是未锁定。

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

### 安装

插件已发布到 npm，在 DSH 里**一条命令即可安装**：

```
dsh-whalegirl-lyric
```

**用 GUI**：设置 →「插件」→ 安装 → 填入上面的包名。

**用命令行**：

```sh
cd ~/.dsh/profiles/<profile 名称>
pnpm add dsh-whalegirl-lyric
```

> ⚠️ 无论用哪种方式，都要再确认 `package.json` 的 `dsh.profile.bundles` 里**含有**
> `"dsh-whalegirl-lyric"`。`pnpm add` 只写 `dependencies` 与 lockfile，**不会**动 `bundles`；
> 缺了这一项，插件会「文件都在但毫无反应」。安装后重启 DeepSeek Harness 并刷新页面。

> 若安装时报 `ERR_PNPM_UNEXPECTED_STORE`，是 profile 的 `node_modules` 由旧版 pnpm 安装、
> 与运行时自带的新版 pnpm 的 store 格式不兼容所致，与插件本身无关。
> 修复脚本见插件 README 的[故障排查](plugins/dsh-whalegirl-lyric/README.md#重建-profile-依赖修-err_pnpm_unexpected_store)章节。

npm 页面：https://www.npmjs.com/package/dsh-whalegirl-lyric
