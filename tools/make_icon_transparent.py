# -*- coding: utf-8 -*-
"""把圆角图标四角的白色背景区域改为透明。

背景
----
`lyrics-display-logo.png` 是圆角方形图标：黑色圆角矩形 + 白色音符 + 彩色频谱。
但整张画布是 RGB（无 alpha 通道），圆角之外的四个角仍是**白色**，
这是生成图标时留下的底色，应当透明，否则图标放到非白色背景上会露出白角。

为什么不能简单地「把所有白色像素变透明」
----------------------------------------
图标内部有大量白色元素（音符主体、音符上的斜线），占全图约 12%。直接按颜色抠白
会把音符一起抠掉。因此采用**从四角出发的连通域填充**：只把与四角相连的白色区域
变透明。黑色圆角矩形的描边天然是填充边界，填充不会越界进入图标内部。

用法
----
    python tools/make_icon_transparent.py            # 处理并写回（会先备份 .orig.png）
    python tools/make_icon_transparent.py --check    # 只检查现状，不写文件
    python tools/make_icon_transparent.py --dry-run  # 只报告将影响的范围，不写文件
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image

# 图标在仓库根目录，本脚本在 tools/ 下
ROOT = Path(__file__).resolve().parent.parent
PNG = ROOT / "lyrics-display-logo.png"
ICO = ROOT / "lyrics-display-logo.ico"

# 与四角相连的白色判定阈值：纯白或接近纯白
WHITE_MIN = 250


def white_mask(rgb: np.ndarray) -> np.ndarray:
    """返回「接近白色」的布尔掩码。"""
    return np.all(rgb >= WHITE_MIN, axis=-1)


def corners_connected_region(mask: np.ndarray) -> np.ndarray:
    """从四个角出发，返回与角相连的 mask 连通区域（四连通）。

    用扫描线填充，避免逐像素 BFS 在 2048x2048 上的开销。
    """
    h, w = mask.shape
    out = np.zeros((h, w), dtype=bool)
    stack: list[tuple[int, int]] = []

    for y in (0, h - 1):
        for x in (0, w - 1):
            if mask[y, x] and not out[y, x]:
                stack.append((x, y))

    while stack:
        x, y = stack.pop()
        if out[y, x] or not mask[y, x]:
            continue

        # 向左右扩展整条水平段
        xl = x
        while xl > 0 and mask[y, xl - 1] and not out[y, xl - 1]:
            xl -= 1
        xr = x
        while xr < w - 1 and mask[y, xr + 1] and not out[y, xr + 1]:
            xr += 1

        out[y, xl:xr + 1] = True

        # 上下相邻行中，与当前段相连的种子入栈
        for ny in (y - 1, y + 1):
            if ny < 0 or ny >= h:
                continue
            row_mask = mask[ny, xl:xr + 1]
            row_out = out[ny, xl:xr + 1]
            # 找出该行中属于 mask 且尚未处理的位置
            candidates = np.flatnonzero(row_mask & ~row_out)
            for c in candidates:
                nx = xl + int(c)
                if not out[ny, nx]:
                    stack.append((nx, ny))

    return out


def report(path: Path) -> None:
    im = Image.open(path)
    a = np.array(im.convert("RGBA"))
    h, w = a.shape[:2]
    alpha = a[..., 3]
    print(f"  文件  : {path.name}")
    print(f"  模式  : {im.mode}   尺寸: {w}x{h}")
    print(f"  透明像素: {int((alpha == 0).sum())} ({(alpha == 0).mean() * 100:.2f}%)")
    for name, (y, x) in (("左上", (0, 0)), ("右上", (0, w - 1)),
                         ("左下", (h - 1, 0)), ("右下", (h - 1, w - 1))):
        px = tuple(int(v) for v in a[y, x])
        flag = "透明" if px[3] == 0 else "不透明"
        print(f"  {name}角: RGBA={px}  {flag}")
    # 图标中心（音符区域）应为不透明
    cy, cx = h // 2, w // 2
    print(f"  中心像素: RGBA={tuple(int(v) for v in a[cy, cx])}")


def main() -> int:
    ap = argparse.ArgumentParser(description="把圆角图标四角的白色背景改为透明")
    ap.add_argument("--check", action="store_true", help="只检查现状，不写文件")
    ap.add_argument("--dry-run", action="store_true", help="只报告影响范围，不写文件")
    ap.add_argument("--png", type=Path, default=PNG)
    args = ap.parse_args()

    if not args.png.exists():
        print(f"错误：找不到 {args.png}", file=sys.stderr)
        return 1

    print("=== 处理前 ===")
    report(args.png)

    if args.check:
        return 0

    im = Image.open(args.png).convert("RGBA")
    a = np.array(im)
    h, w = a.shape[:2]

    mask = white_mask(a[..., :3])
    print(f"\n=== 分析 ===")
    print(f"  接近白色的像素: {int(mask.sum())} ({mask.mean() * 100:.2f}%)")

    region = corners_connected_region(mask)
    n = int(region.sum())
    print(f"  与四角相连的白色区域: {n} ({region.mean() * 100:.2f}%)")

    # 安全检查：待透明区域不应触及画布中心附近（音符所在区域）
    cy, cx = h // 2, w // 2
    pad = h // 8
    center_block = region[cy - pad:cy + pad, cx - pad:cx + pad]
    if center_block.any():
        print("\n  ✗ 安全检查失败：待透明区域侵入了图标中心区域。", file=sys.stderr)
        print("    这说明四角白色与内部白色是连通的，不能这样抠。已中止。", file=sys.stderr)
        return 2
    print(f"  安全检查: 中心区域({2 * pad}x{2 * pad})未被侵入 ✓")

    # 边界检查：区域应集中在四角
    ys, xs = np.nonzero(region)
    print(f"  影响范围: x {xs.min()}~{xs.max()}, y {ys.min()}~{ys.max()}")

    if args.dry_run:
        print("\n(dry-run，未写文件)")
        return 0

    # 备份原始 PNG（只备份一次）
    backup = args.png.with_suffix(".orig.png")
    if not backup.exists():
        shutil.copy2(args.png, backup)
        print(f"\n  已备份原图: {backup.name}")
    else:
        print(f"\n  备份已存在，跳过: {backup.name}")

    # 应用透明：把角部区域的 alpha 置 0
    a[region, 3] = 0
    out = Image.fromarray(a, mode="RGBA")
    out.save(args.png, "PNG", optimize=True)
    print(f"  已写回: {args.png.name}")

    # 重新生成 ICO（保留原有的 6 种尺寸，支持透明）
    if ICO.exists():
        ico_backup = ICO.with_suffix(".orig.ico")
        if not ico_backup.exists():
            shutil.copy2(ICO, ico_backup)
            print(f"  已备份原 ico: {ico_backup.name}")
        sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
        out.save(ICO, format="ICO", sizes=sizes)
        print(f"  已重新生成 ico（{len(sizes)} 种尺寸，含透明通道）: {ICO.name}")

    print("\n=== 处理后 ===")
    report(args.png)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
