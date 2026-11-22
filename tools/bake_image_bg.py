# -*- coding: utf-8 -*-
"""把用户提供的图片烘成待机背景底图：240x240 RGB565，dark / light 各一张。

    py -3 tools/bake_image_bg.py [图片路径]

默认输入 tools/bg_source/user_bg.png。输出与 tools/gen_bg_asset.py 一致：
    main/display/bg_assets.c / bg_assets.h   固件内嵌底图
    _bg_out/bg_*.png                          预览图（480x480 放大）
    _bg_out/preview_*.png                     带表情遮挡区虚线框的预览图

处理流程：
  1. 居中裁成正方形，缩到 240x240（LANCZOS）。
  2. light：原图直出；dark：整体压暗到 58%，夜里不刺眼。
  3. 顶部 24px 烘一条状态栏底色（与 gen_bg_asset.py 同色），保证状态栏文字可读。
  4. 加一点噪点，避免大面积纯色在 RGB565 面板上出现色带。

注意：跑 tools/gen_bg_asset.py 会把金鱼娘程序底图盖回来；改底图只跑本脚本。
"""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gen_bg_asset import to_rgb565  # noqa: E402  复用已验证过的 RGB565 转换

from PIL import Image, ImageDraw, ImageFilter  # noqa: E402

W = H = 240
STATUS_H = 24
DARK_DIM = 0.58
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DEFAULT = os.path.join(ROOT, "tools", "bg_source", "user_bg.png")
OUT_DIR = os.path.join(ROOT, "_bg_out")
C_PATH = os.path.join(ROOT, "main", "display", "bg_assets.c")
H_PATH = os.path.join(ROOT, "main", "display", "bg_assets.h")

# 状态栏底色与 gen_bg_asset.py 同款：dark 深蓝 / light 樱白。
STATUS = {
    "dark": ((14, 30, 44), (255, 176, 164)),
    "light": ((240, 246, 252), (255, 182, 172)),
}

# 表情遮挡区：表情 120x120 贴在 content_ 顶部正中，顶在 y=31（见 gen_bg_asset.py 注释）。
EMOJI_BOX = (60, 31, 180, 151)


def rgba(color, a):
    return (color[0], color[1], color[2], int(max(0, min(255, a))))


def center_square(img):
    w, h = img.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    return img.crop((left, top, left + side, top + side)).resize(
        (W, H), Image.LANCZOS)


def dim(img, factor):
    return img.point(lambda v: int(v * factor))


def draw_statusbar(img, theme):
    status, line = STATUS[theme]
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.rectangle([0, 0, W, STATUS_H], fill=rgba(status, 236))
    d.line([(0, STATUS_H), (W, STATUS_H)], fill=rgba(line, 120), width=1)
    d.line([(0, STATUS_H + 1), (W, STATUS_H + 1)], fill=rgba(line, 40), width=1)
    return Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")


def add_grain(img, amount, seed=7):
    rnd = random.Random(seed)
    px = img.load()
    for y in range(H):
        for x in range(W):
            n = rnd.randint(-amount, amount)
            r, g, b = px[x, y]
            px[x, y] = (max(0, min(255, r + n)), max(0, min(255, g + n)),
                        max(0, min(255, b + n)))
    return img


def emit_c(name, data):
    lines = ["// 由 tools/bake_image_bg.py 生成，勿手改",
             f"static const uint8_t {name}_map[] = {{"]
    for i in range(0, len(data), 20):
        lines.append("    " + ",".join(f"0x{b:02X}" for b in data[i:i + 20]) + ",")
    lines.append("};")
    lines.append("")
    lines.append(f"const lv_image_dsc_t {name} = {{")
    lines.append("    .header.magic = LV_IMAGE_HEADER_MAGIC,")
    lines.append("    .header.cf = LV_COLOR_FORMAT_RGB565,")
    lines.append("    .header.flags = 0,")
    lines.append(f"    .header.w = {W},")
    lines.append(f"    .header.h = {H},")
    lines.append(f"    .header.stride = {W * 2},")
    lines.append(f"    .data_size = {len(data)},")
    lines.append(f"    .data = {name}_map,")
    lines.append("};")
    lines.append("")
    return "\n".join(lines)


def mark_emoji_area(img, theme):
    """预览图上画表情遮挡区虚线框：框内会被金鱼娘表情盖住。"""
    out = img.resize((480, 480), Image.NEAREST).convert("RGB")
    d = ImageDraw.Draw(out)
    x0, y0, x1, y1 = [v * 2 for v in EMOJI_BOX]
    color = (255, 60, 60) if theme == "light" else (255, 120, 120)
    dash = 10
    for x in range(x0, x1, dash * 2):
        d.line([(x, y0), (min(x + dash, x1), y0)], fill=color, width=2)
        d.line([(x, y1), (min(x + dash, x1), y1)], fill=color, width=2)
    for y in range(y0, y1, dash * 2):
        d.line([(x0, y), (x0, min(y + dash, y1))], fill=color, width=2)
        d.line([(x1, y), (x1, min(y + dash, y1))], fill=color, width=2)
    return out


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else SRC_DEFAULT
    base = Image.open(src).convert("RGB")
    print("source:", src, base.size)
    square = center_square(base)
    os.makedirs(OUT_DIR, exist_ok=True)

    chunks = ["// 由 tools/bake_image_bg.py 生成，勿手改",
              f"// 底图来源：{os.path.relpath(src, ROOT)}",
              '#include "bg_assets.h"', ""]
    for name, theme in (("bg_dark", "dark"), ("bg_light", "light")):
        img = square.copy()
        if theme == "dark":
            img = dim(img, DARK_DIM)
        img = add_grain(img, 2)
        img = draw_statusbar(img, theme)
        img.resize((480, 480), Image.NEAREST).save(
            os.path.join(OUT_DIR, f"{name}.png"))
        mark_emoji_area(img, theme).save(
            os.path.join(OUT_DIR, f"preview_{theme}.png"))
        data = to_rgb565(img)
        print(name, len(data), "bytes")
        chunks.append(emit_c(name, data))

    with open(C_PATH, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(chunks))
    with open(H_PATH, "w", encoding="utf-8", newline="\n") as f:
        f.write(
            "// 由 tools/bake_image_bg.py 生成，勿手改\n"
            "#ifndef BG_ASSETS_H\n#define BG_ASSETS_H\n\n#include <lvgl.h>\n\n"
            "// 用户图片待机背景底图：dark（压暗）/ light（原图）各一张，240x240 RGB565\n"
            "extern const lv_image_dsc_t bg_dark;\nextern const lv_image_dsc_t bg_light;\n\n"
            "#endif\n"
        )
    print("wrote", C_PATH)
    print("wrote", H_PATH)


if __name__ == "__main__":
    main()
