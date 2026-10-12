# -*- coding: utf-8 -*-
"""验证图标修复结果：PyQt5 能否加载、各尺寸观感是否正常。

用法: python tools/verify_icon.py
"""
import os
from pathlib import Path

import numpy as np
from PIL import Image

# 图标在仓库根目录，本脚本在 tools/ 下
ROOT = Path(__file__).resolve().parent.parent
ICO = ROOT / "lyrics-display-logo.ico"
PNG = ROOT / "lyrics-display-logo.png"
ORIG_PNG = ROOT / "lyrics-display-logo.orig.png"

print("=" * 62)
print("1. PNG 与 ICO 的透明通道")
print("=" * 62)
for p in (PNG, ICO):
    im = Image.open(p)
    a = np.array(im.convert("RGBA"))
    al = a[..., 3]
    print(f"  {p.name:32s} 模式={im.mode:5s} 尺寸={im.size}")
    print(f"    透明像素 {int((al == 0).sum()):7d} / {al.size}  ({(al == 0).mean() * 100:.2f}%)")
    for name, (y, x) in (("左上", (0, 0)), ("右上", (0, a.shape[1] - 1)),
                         ("左下", (a.shape[0] - 1, 0)), ("右下", (a.shape[0] - 1, a.shape[1] - 1))):
        px = tuple(int(v) for v in a[y, x])
        print(f"    {name}角 {px}  {'透明 OK' if px[3] == 0 else '不透明'}")
    cy, cx = a.shape[0] // 2, a.shape[1] // 2
    print(f"    中心(音符处) {tuple(int(v) for v in a[cy, cx])}  (应不透明)")

print()
print("=" * 62)
print("2. PyQt5 加载测试（应用实际使用的路径）")
print("=" * 62)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
try:
    from PyQt5.QtGui import QIcon
    from PyQt5.QtWidgets import QApplication
    import sys

    app = QApplication(sys.argv)
    for p in (ICO, PNG):
        ic = QIcon(str(p))
        sizes = ic.availableSizes()
        size_str = ", ".join(f"{s.width()}x{s.height()}" for s in sizes)
        pm = ic.pixmap(256, 256)
        col = pm.toImage().pixelColor(0, 0)
        print(f"  {p.name}")
        print(f"    可加载    : {not ic.isNull()}")
        print(f"    可用尺寸  : {size_str}")
        print(f"    256px 渲染后左上角 RGBA = ({col.red()},{col.green()},{col.blue()},{col.alpha()})")
except Exception as e:  # noqa: BLE001
    print(f"  跳过（PyQt5 不可用或 offscreen 平台失败）: {e}")

print()
print("=" * 62)
print("3. 各尺寸观感（拼到深色条上，导出 _icon_sizes.png）")
print("=" * 62)
targets = [16, 20, 24, 32, 48, 64, 128, 256]
ico_sizes = set(Image.open(ICO).ico.sizes())
# 取 ICO 的 256 档作为缩放源（用 size 属性选帧，不能直接赋值）
base_frame = Image.open(ICO)
base_frame.size = (256, 256)
base = base_frame.convert("RGBA")

gap, pad = 18, 18
width = pad * 2 + sum(t + gap for t in targets) - gap
height = 256 + pad * 2
canvas = Image.new("RGBA", (width, height), (32, 34, 40, 255))
x = pad
for t in targets:
    if (t, t) in ico_sizes:
        im = Image.open(ICO)
        im.size = (t, t)
        frame = im.convert("RGBA")
        src = "ico"
    else:
        frame = base.resize((t, t), Image.LANCZOS)
        src = "png"
    canvas.alpha_composite(frame, (x, pad + (256 - t) // 2))
    print(f"  {t:4d}px  ← {src}")
    x += t + gap
canvas.save(ROOT / "_icon_sizes.png")
print(f"  已导出 _icon_sizes.png ({canvas.size[0]}x{canvas.size[1]})")

print()
print("=" * 62)
print("4. 与修复前的差异")
print("=" * 62)
if ORIG_PNG.exists():
    o = np.array(Image.open(ORIG_PNG).convert("RGBA"))[..., 3]
    n = np.array(Image.open(PNG).convert("RGBA"))[..., 3]
    print(f"  修复前透明像素: {int((o == 0).sum())}")
    print(f"  修复后透明像素: {int((n == 0).sum())}")
    print(f"  新增透明像素  : {int((n == 0).sum()) - int((o == 0).sum())}")
else:
    print("  未找到 .orig.png 备份（原图可从 git 历史取回）")
