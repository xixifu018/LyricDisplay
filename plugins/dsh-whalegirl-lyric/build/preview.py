# -*- coding: utf-8 -*-
"""用 Pillow 复现挂件的 CSS 布局，生成「默认收起态 + 展开控制区」的像素级预览。

所有尺寸都取自 build/client.template.js 里的实际 CSS 值。
改布局后先跑这个脚本看效果，再重启验证。

用法: python build/preview.py
"""
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path
import io
import json
import urllib.request

# ---- 路径：全部相对本脚本推导，便于在别的机器上运行（不要写死绝对路径） ----
HERE = Path(__file__).resolve().parent        # .../dsh-whalegirl-lyric/build
PLUGIN_ROOT = HERE.parent                     # .../dsh-whalegirl-lyric
WORKSPACE_ROOT = PLUGIN_ROOT.parents[1]      # .../lyric_display
SOURCE_IMAGE = WORKSPACE_ROOT / "whalegirl.png"
OUTPUT_IMAGE = HERE / "preview.png"

# ---- 与 client.template.js 的 CSS 保持一致的尺寸 ----
CARD_PAD = 8
CARD_GAP = 8
CARD_RADIUS = 13
COLLAPSE_COL = 14  # .dshWg_collapse 宽
COLLAPSE_ML = -5  # .dshWg_collapse 左外边距
BAR_W = 126
STAGE_W = 160
STAGE_H = 170
FIGURE_TOP = 20
BUBBLE_W = 148
BUBBLE_PAD_X = 8
BUBBLE_PAD_Y = 6
BUBBLE_RADIUS = 10
BTN = 21
BTN_GAP = 5
PLAY = 26
PROGRESS_H = 3
LINE_H = 15  # 11px * 1.35
TRANS_H = 12  # 9.5px * 1.3
NEXT_H = 12
RAIL_GAP = 4  # .dshWg_bar 的 gap
COVER_RADIUS = 9
COVER_W = 90  # .dshWg_cover 固定宽度（高度不超出控制列预算）
TRACK_W = 110  # .dshWg_track / .dshWg_progress / .dshWg_time 宽度

CARD_W_EXPANDED = CARD_PAD + COLLAPSE_COL + COLLAPSE_ML + CARD_GAP + BAR_W + CARD_GAP + STAGE_W + CARD_PAD
CARD_W_COLLAPSED = CARD_PAD + COLLAPSE_COL + COLLAPSE_ML + CARD_GAP + STAGE_W + CARD_PAD
CARD_H = CARD_PAD + STAGE_H + CARD_PAD

SS = 2
MARGIN = 22

SRC = Image.open(SOURCE_IMAGE).convert("RGBA")
GIRL = SRC.crop(SRC.getchannel("A").getbbox())


def fetch_cover():
    """取当前播放歌曲的封面；失败返回 None，预览照常出。"""
    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:23330/status?filter=picUrl", timeout=4
        ) as resp:
            url = json.loads(resp.read().decode("utf-8")).get("picUrl") or ""
        if not url:
            return None
        req = urllib.request.Request(url, headers={"accept": "image/*"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            return Image.open(io.BytesIO(resp.read())).convert("RGBA")
    except Exception as exc:  # noqa: BLE001 - 预览是辅助工具，取不到不该中断
        print("  (取封面失败，用占位方块:", exc, ")")
        return None


COVER = fetch_cover()


def s(v):
    return int(round(v * SS))


def font(size, bold=False):
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    try:
        return ImageFont.truetype(name, s(size))
    except OSError:
        return ImageFont.load_default()


def sfont(size):
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except OSError:
        return ImageFont.load_default()


def draw_girl(canvas, stage_x, stage_y):
    """按 contain 铺满舞台宽度、贴底绘制鲸鱼娘。"""
    box_w, box_h = STAGE_W, STAGE_H - FIGURE_TOP
    scale = min(box_w / GIRL.width, box_h / GIRL.height)
    gw, gh = int(GIRL.width * scale), int(GIRL.height * scale)
    img = GIRL.resize((s(gw), s(gh)), Image.LANCZOS)
    gx = s(stage_x) + (s(box_w) - s(gw)) // 2
    gy = s(stage_y + STAGE_H) - s(gh)
    canvas.alpha_composite(img, (gx, gy))


def draw_chevron(d, x, y, compact):
    """折叠开关的双箭头：收起态指向右侧（可展开），展开态指向左侧（可收起）。"""
    for offset, alpha in ((0, 255), (4, 110)):
        if compact:
            pts = [(x + offset, y + 3), (x + offset + 4, y + 7), (x + offset, y + 11)]
        else:
            pts = [(x + offset + 4, y + 3), (x + offset, y + 7), (x + offset + 4, y + 11)]
        d.line([(s(px), s(py)) for px, py in pts], fill=(150, 156, 170, alpha), width=s(1.3))


def render_card(compact):
    """渲染一张卡片，返回 RGBA 图。"""
    card_w = CARD_W_COLLAPSED if compact else CARD_W_EXPANDED
    W = (card_w + MARGIN * 2) * SS
    H = (CARD_H + MARGIN * 2) * SS
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(canvas)

    card_x, card_y = MARGIN, MARGIN
    d.rounded_rectangle(
        [s(card_x), s(card_y), s(card_x + card_w), s(card_y + CARD_H)],
        radius=s(CARD_RADIUS),
        fill=(30, 32, 38, 242),
        outline=(70, 74, 84, 255),
        width=s(1),
    )

    # 折叠开关（贴左边缘，负外边距）
    draw_chevron(d, card_x + CARD_PAD + COLLAPSE_ML + 3, card_y + CARD_PAD + 1, compact)

    # 舞台区：展开态排在控制区之后，收起态紧跟折叠开关
    stage_x = card_x + CARD_PAD + COLLAPSE_COL + COLLAPSE_ML + CARD_GAP
    if not compact:
        stage_x += BAR_W + CARD_GAP
    stage_y = card_y + CARD_PAD

    draw_girl(canvas, stage_x, stage_y)

    # 气泡（右上角，两种状态尺寸相同）
    bx = stage_x + STAGE_W - BUBBLE_W
    by = stage_y
    bubble_h = BUBBLE_PAD_Y * 2 + LINE_H + 2 + TRANS_H + 3 + NEXT_H
    d.rounded_rectangle(
        [s(bx), s(by), s(bx + BUBBLE_W), s(by + bubble_h)],
        radius=s(BUBBLE_RADIUS),
        fill=(44, 47, 55, 255),
        outline=(92, 97, 110, 255),
        width=s(1),
    )
    tail_cx = bx + 22 + 4
    tail_cy = by + bubble_h - 1
    d.polygon(
        [(s(tail_cx - 6), s(tail_cy - 5)), (s(tail_cx + 6), s(tail_cy - 5)), (s(tail_cx), s(tail_cy + 6))],
        fill=(44, 47, 55, 255),
    )
    ty = by + BUBBLE_PAD_Y
    d.text((s(bx + BUBBLE_PAD_X), s(ty)), "我遇见谁 会有怎样的对白", font=font(11, True), fill=(238, 240, 245, 255))
    ty += LINE_H + 2
    d.text((s(bx + BUBBLE_PAD_X), s(ty)), "Whom will I meet, what kind of", font=font(9.5), fill=(150, 156, 170, 255))
    ty += TRANS_H + 3
    d.text((s(bx + BUBBLE_PAD_X), s(ty)), "我等的人 他在多远的未来", font=font(9.5), fill=(150, 156, 170, 190))

    # 控制区（仅展开态）：从列底向上排，所有内容水平居中
    if not compact:
        center_x = card_x + CARD_PAD + COLLAPSE_COL + COLLAPSE_ML + CARD_GAP + BAR_W / 2
        track_top = 11   # 9.5px * 1.35 的行高
        time_h = 10      # 8.5px 行高
        content_h = COVER_W + RAIL_GAP + track_top + 3 + time_h + 3 + PROGRESS_H + RAIL_GAP + PLAY
        content_top = stage_y + STAGE_H - content_h

        cover_x = center_x - COVER_W / 2
        cover_y = content_top
        track_y = cover_y + COVER_W + RAIL_GAP
        progress_y = track_y + track_top + 3
        row_y = progress_y + PROGRESS_H + RAIL_GAP

        cover_size = s(COVER_W)
        if COVER is not None:
            fitted = COVER.resize((cover_size, cover_size), Image.LANCZOS)
        else:
            fitted = Image.new("RGBA", (cover_size, cover_size), (48, 52, 62, 255))
        cover_mask = Image.new("L", (cover_size, cover_size), 0)
        ImageDraw.Draw(cover_mask).rounded_rectangle(
            [0, 0, cover_size - 1, cover_size - 1], radius=s(COVER_RADIUS), fill=255
        )
        canvas.paste(fitted, (s(cover_x), s(cover_y)), cover_mask)
        if COVER is None:
            nf = font(26)
            nb = d.textbbox((0, 0), "♪", font=nf)
            d.text(
                (
                    s(cover_x) + (cover_size - (nb[2] - nb[0])) // 2,
                    s(cover_y) + (cover_size - (nb[3] - nb[1])) // 2 - s(3),
                ),
                "♪",
                font=nf,
                fill=(150, 156, 170, 128),
            )
        d.rounded_rectangle(
            [s(cover_x), s(cover_y), s(cover_x + COVER_W), s(cover_y + COVER_W)],
            radius=s(COVER_RADIUS),
            outline=(70, 74, 84, 255),
            width=s(1),
        )

        # 歌曲名居中，超长时裁剪（真实环境会来回滚动）
        track_x = center_x - TRACK_W / 2
        track_text = "遇见 · 孙燕姿"
        tb = d.textbbox((0, 0), track_text, font=font(9.5, True))
        d.text((s(track_x), s(track_y)), track_text, font=font(9.5, True), fill=(238, 240, 245, 255))
        # 裁剪标记：右侧越界提示
        if (tb[2] - tb[0]) / SS > TRACK_W:
            d.line(
                [(s(track_x + TRACK_W + 2), s(track_y)), (s(track_x + TRACK_W + 2), s(track_y + track_top))],
                fill=(90, 95, 108, 255),
                width=s(1),
            )

        # 进度区：上排「已播 —— 总时长」，下排通栏进度条（都在列内居中）
        tfont = font(8.5)
        cur_text, dur_text = "0:42", "3:29"
        time_y = progress_y - 3 - time_h
        d.text((s(center_x - TRACK_W / 2), s(time_y)), cur_text, font=tfont, fill=(150, 156, 170, 255))
        dur_w = (d.textbbox((0, 0), dur_text, font=tfont)[2]) / SS
        d.text((s(center_x + TRACK_W / 2 - dur_w), s(time_y)), dur_text, font=tfont, fill=(150, 156, 170, 255))

        bar_x0 = center_x - TRACK_W / 2
        d.rounded_rectangle(
            [s(bar_x0), s(progress_y), s(bar_x0 + TRACK_W), s(progress_y + PROGRESS_H)],
            radius=s(2),
            fill=(70, 74, 84, 255),
        )
        d.rounded_rectangle(
            [s(bar_x0), s(progress_y), s(bar_x0 + TRACK_W * (42.5 / 209.8)), s(progress_y + PROGRESS_H)],
            radius=s(2),
            fill=(56, 110, 240, 255),
        )

        # 按钮组水平居中
        buttons_w = BTN + BTN_GAP + PLAY + BTN_GAP + BTN
        bxx = center_x - buttons_w / 2
        for w, h, glyph in ((BTN, BTN, "prev"), (PLAY, PLAY, "pause"), (BTN, BTN, "next")):
            top = row_y + (PLAY - h) // 2 if h < PLAY else row_y
            d.rounded_rectangle(
                [s(bxx), s(top), s(bxx + w), s(top + h)],
                radius=s(h // 2 if glyph == "pause" else 7),
                fill=(56, 110, 240, 255) if glyph == "pause" else (0, 0, 0, 0),
                outline=None if glyph == "pause" else (80, 85, 96, 255),
                width=s(1),
            )
            cx, cy = bxx + w / 2, top + h / 2
            if glyph == "prev":
                d.polygon([(s(cx + 3), s(cy - 5)), (s(cx + 3), s(cy + 5)), (s(cx - 3), s(cy))], fill=(235, 238, 244, 255))
            elif glyph == "next":
                d.polygon([(s(cx - 3), s(cy - 5)), (s(cx - 3), s(cy + 5)), (s(cx + 3), s(cy))], fill=(235, 238, 244, 255))
            else:
                d.rectangle([s(cx - 3), s(cy - 5), s(cx - 1.5), s(cy + 5)], fill=(255, 255, 255, 255))
                d.rectangle([s(cx + 1.5), s(cy - 5), s(cx + 3), s(cy + 5)], fill=(255, 255, 255, 255))
            bxx += w + BTN_GAP

    return canvas.resize((W // SS, H // SS), Image.LANCZOS)


collapsed = render_card(True)
expanded = render_card(False)

# 胶囊（第三态）
pill_w, pill_h = 160, 31
pill = Image.new("RGBA", ((pill_w + MARGIN * 2), (pill_h + MARGIN * 2)), (0, 0, 0, 0))
pd = ImageDraw.Draw(pill)
pd.rounded_rectangle(
    [s(MARGIN), s(MARGIN), s(MARGIN + pill_w), s(MARGIN + pill_h)],
    radius=s(pill_h // 2),
    fill=(30, 32, 38, 242),
    outline=(70, 74, 84, 255),
    width=s(1),
)
pd.text((s(MARGIN + 9), s(MARGIN + 10)), "我遇见谁 会有怎样的对白", font=font(10), fill=(238, 240, 245, 255))
dot_x = MARGIN + 9 + 88 + 6
pd.ellipse(
    [s(dot_x), s(MARGIN + pill_h / 2 - 2.5), s(dot_x + 5), s(MARGIN + pill_h / 2 + 2.5)],
    fill=(46, 204, 113, 255),
)
face_size = s(22)
face = SRC.crop((760, 700, 1480, 1420)).resize((face_size, face_size), Image.LANCZOS)
fmask = Image.new("L", (face_size, face_size), 0)
ImageDraw.Draw(fmask).ellipse([0, 0, face_size - 1, face_size - 1], fill=255)
pill.paste(face, (s(MARGIN + pill_w - 4 - 22), s(MARGIN + 4)), fmask)
pill = pill.resize((pill.width // SS, pill.height // SS), Image.LANCZOS)

# 拼装：默认收起态 | 展开态，胶囊在下
gap = 20
W = collapsed.width + gap + expanded.width
H = max(collapsed.height, expanded.height) + gap + pill.height
out = Image.new("RGBA", (W, H), (17, 18, 22, 255))
out.alpha_composite(collapsed, (0, 0))
out.alpha_composite(expanded, (collapsed.width + gap, 0))
out.alpha_composite(pill, (0, max(collapsed.height, expanded.height) + gap))

d = ImageDraw.Draw(out)
d.text((4, collapsed.height + 3), "default (collapsed)", font=sfont(11), fill=(140, 145, 158, 255))
d.text(
    (collapsed.width + gap + 4, expanded.height + 3),
    "controls expanded",
    font=sfont(11),
    fill=(140, 145, 158, 255),
)

path = OUTPUT_IMAGE
out.save(path)
print("预览已生成: build/preview.png  %dx%d" % out.size)
print("默认（收起）卡片: %dx%d" % (CARD_W_COLLAPSED, CARD_H))
print("展开控制区卡片: %dx%d" % (CARD_W_EXPANDED, CARD_H))
print("鲸鱼娘舞台: %dx%d" % (STAGE_W, STAGE_H))
