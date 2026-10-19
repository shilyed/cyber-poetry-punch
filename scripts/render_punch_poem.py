#!/usr/bin/env python3
"""Render a Xiaohongshu-style cyber poetry punch image.

The input is a JSON plan:

{
  "title": "过零丁洋",
  "author": "文天祥",
  "lines": [
    "辛苦遭逢起一经，干戈寥落四周星。",
    "山河破碎风飘絮，身世浮沉雨打萍。",
    "惶恐滩头说惶恐，零丁洋里叹零丁。",
    "人生自古谁无死，留取丹心照汗青。"
  ],
  "new_phrase": "生照山河，死落零丁。",
  "punch": [{"line": 1, "index": 0}],
  "palette": "vermilion",
  "canvas": [1800, 2400],
  "footer": "CUT FROM THE MOMENT"
}

If "punch" is omitted, the script finds occurrences of the CJK characters in
"new_phrase" and chooses a spread-out set automatically. If "punch" is present,
the script validates that the punched CJK characters match "new_phrase".
"""

from __future__ import annotations

import argparse
import io
import json
import math
import os
import random
import sys
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Any

from PIL import (
    Image,
    ImageChops,
    ImageDraw,
    ImageEnhance,
    ImageFilter,
    ImageFont,
    ImageStat,
)
from PIL.PngImagePlugin import PngInfo


PALETTES: dict[str, dict[str, str]] = {
    "vermilion": {
        "paper": "#F2E8D5",
        "accent": "#A61B1B",
        "ink": "#2B2B2B",
    },
    "ink-green": {
        "paper": "#E9E3D2",
        "accent": "#2F4F3A",
        "ink": "#1F2A22",
    },
    "navy": {
        "paper": "#EFE6D8",
        "accent": "#1F3A5F",
        "ink": "#1B2430",
    },
    "black": {
        "paper": "#E9E3D6",
        "accent": "#1A1A1A",
        "ink": "#111111",
    },
    "ochre": {
        "paper": "#F4E9D0",
        "accent": "#B5651D",
        "ink": "#2B2118",
    },
}

SKILL_ROOT = Path(__file__).resolve().parent.parent
BUNDLED_FONT = SKILL_ROOT / "assets" / "fonts" / "Huiwenmincho-improved.ttf"
BUNDLED_PAPER = SKILL_ROOT / "assets" / "textures" / "ricepaper.png"

FONT_CANDIDATES: dict[str, list[str]] = {
    "old-song": [
        str(BUNDLED_FONT),
        r"C:\Windows\Fonts\KingHwa_OldSong.ttf",
        r"C:\Windows\Fonts\KingHwaOldSong.ttf",
        r"C:\Windows\Fonts\JinghuaOldSong.ttf",
        r"C:\Windows\Fonts\京华老宋体.ttf",
        r"C:\Windows\Fonts\京華老宋体.ttf",
        r"C:\Windows\Fonts\Huiwen-MinchoGBK.ttf",
        r"C:\Windows\Fonts\HuiwenMincho.ttf",
        r"C:\Windows\Fonts\汇文明朝体.otf",
        r"C:\Windows\Fonts\匯文明朝體.ttf",
        r"C:\Windows\Fonts\NotoSerifSC-VF.ttf",
        r"C:\Windows\Fonts\mingliub.ttc",
        r"C:\Windows\Fonts\simsun.ttc",
        "/System/Library/Fonts/Supplemental/Songti.ttc",
        "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
    ],
    "serif": [
        r"C:\Windows\Fonts\simsun.ttc",
        r"C:\Windows\Fonts\simsunb.ttf",
        "/System/Library/Fonts/Supplemental/Songti.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSerifCJKsc-Regular.otf",
        "/usr/share/fonts/truetype/noto/NotoSerifCJK-Regular.ttc",
    ],
    "kai": [
        r"C:\Windows\Fonts\simkai.ttf",
        "/System/Library/Fonts/Supplemental/Kaiti.ttc",
        "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
    ],
    "sans": [
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        "/System/Library/Fonts/PingFang.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    ],
}


@lru_cache(maxsize=1)
def user_font_candidates() -> tuple[Path, ...]:
    """Find user-installed KingHwa/Huiwen fonts without reading the registry."""
    roots = [
        Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts",
        Path(os.environ.get("LOCALAPPDATA", ""))
        / "Microsoft"
        / "Windows"
        / "Fonts",
    ]
    keywords = ("kinghwa", "jinghua", "huiwen", "汇文", "京华", "京華")
    found: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.iterdir():
            if path.suffix.lower() not in {".ttf", ".otf", ".ttc"}:
                continue
            name = path.name.lower()
            if any(keyword.lower() in name for keyword in keywords):
                found.append(path)
    return tuple(found)


def to_traditional(text: str) -> str:
    """Convert Simplified Chinese to Traditional using the Windows API.

    On non-Windows systems, return the input unchanged. The skill's bundled
    font already contains Traditional glyphs, so the caller can also provide
    Traditional text directly.
    """
    if not text or sys.platform != "win32":
        return text
    try:
        import ctypes
        from ctypes import wintypes

        lcmap_traditional_chinese = 0x04000000
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        func = kernel32.LCMapStringEx
        func.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.LPCWSTR,
            ctypes.c_int,
            wintypes.LPWSTR,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        func.restype = ctypes.c_int
        needed = func(
            "zh-CN",
            lcmap_traditional_chinese,
            text,
            len(text),
            None,
            0,
            None,
            None,
            None,
        )
        if needed <= 0:
            return text
        buffer = ctypes.create_unicode_buffer(needed)
        written = func(
            "zh-CN",
            lcmap_traditional_chinese,
            text,
            len(text),
            buffer,
            needed,
            None,
            None,
            None,
        )
        return buffer[:written] if written > 0 else text
    except Exception:
        return text


def is_cjk(ch: str) -> bool:
    code = ord(ch)
    return (
        0x3400 <= code <= 0x4DBF
        or 0x4E00 <= code <= 0x9FFF
        or 0xF900 <= code <= 0xFAFF
        or 0x20000 <= code <= 0x2FA1F
    )


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.strip().lstrip("#")
    if len(value) != 6:
        raise ValueError(f"无效颜色：{value!r}，需要六位 HEX")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def mix(
    a: tuple[int, int, int], b: tuple[int, int, int], t: float
) -> tuple[int, int, int]:
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))  # type: ignore[return-value]


def darken(color: tuple[int, int, int], factor: float = 0.8) -> tuple[int, int, int]:
    return mix(color, (0, 0, 0), 1.0 - factor)


def lighten(color: tuple[int, int, int], factor: float = 0.2) -> tuple[int, int, int]:
    return mix(color, (255, 255, 255), factor)


def load_font(
    style: str, size: int, font_path: str | None = None
) -> ImageFont.FreeTypeFont:
    size = max(1, int(size))
    if font_path:
        candidates = [font_path]
    elif style == "old-song":
        candidates = [str(BUNDLED_FONT)]
        candidates.extend(str(path) for path in user_font_candidates())
        candidates.extend(FONT_CANDIDATES["old-song"])
    else:
        candidates = FONT_CANDIDATES.get(style, FONT_CANDIDATES["serif"])
    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size, index=0)
            except OSError:
                continue
    raise SystemExit(
        "没有找到可用的中文字体。请安装 SimSun / Noto Serif CJK，"
        "或在 plan 中用 font_path 指定一个支持中文的 TTF/OTF 字体。"
    )


def text_bbox(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont):
    return draw.textbbox((0, 0), text, font=font)


def draw_centered(
    draw: ImageDraw.ImageDraw,
    cx: float,
    cy: float,
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int],
) -> None:
    bbox = text_bbox(draw, text, font)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    draw.text(
        (cx - w / 2 - bbox[0], cy - h / 2 - bbox[1]),
        text,
        font=font,
        fill=fill,
    )


def draw_spaced_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int],
    cx: float,
    cy: float,
    spacing: float,
) -> None:
    widths = [draw.textlength(ch, font=font) for ch in text]
    total = sum(widths) + spacing * max(0, len(text) - 1)
    x = cx - total / 2
    for ch, width in zip(text, widths):
        draw.text((x, cy), ch, font=font, fill=fill, anchor="lm")
        x += width + spacing


def make_surface(
    size: tuple[int, int],
    color: tuple[int, int, int],
    seed: int,
    kind: str = "paper",
) -> Image.Image:
    """Tint a bundled rice-paper scan without replacing the palette color."""
    width, height = size
    is_paper = kind == "paper"
    try:
        with Image.open(BUNDLED_PAPER) as source:
            tile = source.convert("L")
    except (OSError, ValueError) as exc:
        raise SystemExit(
            f"无法读取内置纸张材质 {BUNDLED_PAPER}：{exc}。"
            "请重新解压完整 skill，保留 assets/textures 目录。"
        ) from exc

    scale = width / 1800 * 1.35
    tile = tile.resize(
        (max(1, round(tile.width * scale)), max(1, round(tile.height * scale))),
        Image.Resampling.LANCZOS,
    )
    rnd = random.Random(seed)
    offset_x = rnd.randrange(tile.width)
    offset_y = rnd.randrange(tile.height)
    texture = Image.new("L", size)
    for y in range(-offset_y, height, tile.height):
        for x in range(-offset_x, width, tile.width):
            texture.paste(tile, (x, y))

    # Remove the scan's lighting/color cast; retain only its fibre relief.
    mean = ImageStat.Stat(texture).mean[0]
    strength = 1.6 if is_paper else 0.42
    relief = texture.point(
        lambda value: max(0, min(255, round(128 + (value - mean) * strength)))
    )
    relief_rgb = Image.merge("RGB", (relief, relief, relief))
    return ImageChops.add(Image.new("RGB", size, color), relief_rgb, offset=-128)


def parse_palette(value: Any) -> dict[str, tuple[int, int, int]]:
    if value is None:
        value = "vermilion"
    if isinstance(value, str):
        if value not in PALETTES:
            names = "、".join(PALETTES)
            raise SystemExit(f"未知配色 {value!r}。可用配色：{names}")
        raw = PALETTES[value]
    elif isinstance(value, dict):
        raw = {
            "paper": value.get("paper", PALETTES["vermilion"]["paper"]),
            "accent": value.get("accent", PALETTES["vermilion"]["accent"]),
            "ink": value.get("ink", PALETTES["vermilion"]["ink"]),
        }
    else:
        raise SystemExit("palette 必须是配色名称或 {paper, accent, ink} 对象")

    return {
        "paper": hex_to_rgb(raw["paper"]),
        "accent": hex_to_rgb(raw["accent"]),
        "ink": hex_to_rgb(raw["ink"]),
    }


def normalize_lines(plan: dict[str, Any]) -> list[str]:
    lines = plan.get("lines")
    if lines is None:
        text = plan.get("text")
        if text is None:
            raise SystemExit("plan 需要 lines 数组或 text 字符串")
        lines = str(text).splitlines()
    if not isinstance(lines, list):
        raise SystemExit("lines 必须是字符串数组")
    cleaned = [str(line).strip("\ufeff") for line in lines]
    cleaned = [line for line in cleaned if line.strip()]
    if not cleaned:
        raise SystemExit("诗为空，无法生成")
    return cleaned


def collect_cjk_positions(
    lines: list[str],
) -> list[tuple[int, int, str]]:
    return [
        (line_index, char_index, ch)
        for line_index, line in enumerate(lines)
        for char_index, ch in enumerate(line)
        if is_cjk(ch)
    ]


def auto_match_positions(
    lines: list[str], new_phrase: str
) -> list[tuple[int, int]]:
    """Choose a spread-out set of occurrences that spells new_phrase."""
    target_chars = [ch for ch in new_phrase if is_cjk(ch)]
    if not target_chars:
        raise SystemExit("new_phrase 里没有汉字，无法挖字")

    by_char: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for line_index, char_index, ch in collect_cjk_positions(lines):
        by_char[ch].append((line_index, char_index))

    needed = Counter(target_chars)
    for ch, count in needed.items():
        available = len(by_char.get(ch, []))
        if available < count:
            raise SystemExit(
                f"诗中「{ch}」只有 {available} 个，新句需要 {count} 个。"
                "请减少该字，或换一个方案。"
            )

    # Rarest characters first makes duplicate handling much safer.
    order = sorted(
        range(len(target_chars)),
        key=lambda index: (len(by_char[target_chars[index]]), index),
    )

    selected: list[tuple[int, int]] = []
    used: set[tuple[int, int]] = set()
    line_usage: Counter[int] = Counter()

    for target_index in order:
        ch = target_chars[target_index]
        best: tuple[float, int, int] | None = None
        for line_index, char_index in by_char[ch]:
            if (line_index, char_index) in used:
                continue

            cost = line_usage[line_index] * 3.0
            for selected_line, selected_char in selected:
                if selected_line == line_index:
                    distance = abs(selected_char - char_index)
                    if distance == 1:
                        cost += 8.0
                    elif distance == 2:
                        cost += 4.0
                    elif distance == 3:
                        cost += 1.5

            line_length = len(lines[line_index])
            cost += abs(char_index - (line_length - 1) / 2.0) * 0.03

            if best is None or cost < best[0]:
                best = (cost, line_index, char_index)

        if best is None:
            raise SystemExit(
                f"无法为「{ch}」找到未占用的位置，请换一个挖字方案。"
            )

        _, line_index, char_index = best
        selected.append((line_index, char_index))
        used.add((line_index, char_index))
        line_usage[line_index] += 1

    return sorted(selected)


def parse_explicit_positions(
    lines: list[str], raw_positions: Any
) -> list[tuple[int, int]]:
    if not isinstance(raw_positions, list) or not raw_positions:
        raise SystemExit("punch 必须是非空数组")

    positions: list[tuple[int, int]] = []
    for item in raw_positions:
        if isinstance(item, dict):
            line_index = item.get("line")
            char_index = item.get("index")
        elif isinstance(item, (list, tuple)) and len(item) == 2:
            line_index, char_index = item
        else:
            raise SystemExit(
                "punch 的每一项应为 {line, index} 或 [line, index]"
            )

        if not isinstance(line_index, int) or not isinstance(char_index, int):
            raise SystemExit("punch 的 line/index 必须是整数")
        if not 0 <= line_index < len(lines):
            raise SystemExit(f"punch 行号越界：{line_index}")
        line = lines[line_index]
        if not 0 <= char_index < len(line):
            raise SystemExit(
                f"punch 字位越界：line={line_index}, index={char_index}, "
                f"该行长度={len(line)}"
            )
        if line[char_index].isspace():
            raise SystemExit(
                f"punch 指向空白：line={line_index}, index={char_index}"
            )
        positions.append((line_index, char_index))

    if len(set(positions)) != len(positions):
        raise SystemExit("punch 中有重复位置")
    return sorted(positions)


def punched_text(lines: list[str], positions: list[tuple[int, int]]) -> str:
    return "".join(lines[line_index][char_index] for line_index, char_index in positions)


def validate_plan(
    plan: dict[str, Any],
) -> tuple[list[str], str, list[tuple[int, int]], dict[str, tuple[int, int, int]]]:
    original_lines = normalize_lines(plan)
    use_traditional = bool(plan.get("traditional", True))
    lines = (
        [to_traditional(line) for line in original_lines]
        if use_traditional
        else original_lines
    )
    new_phrase = str(plan.get("new_phrase") or plan.get("target_phrase") or "").strip()
    if use_traditional:
        new_phrase = to_traditional(new_phrase)

    if "punch" in plan and plan["punch"]:
        if any(len(before) != len(after) for before, after in zip(original_lines, lines)):
            raise SystemExit(
                "繁体转换改变了字符数，显式 punch 位置会错位。"
                "请改用 new_phrase 自动匹配，或设置 traditional: false。"
            )

    if "punch" in plan and plan["punch"]:
        positions = parse_explicit_positions(lines, plan["punch"])
        if not new_phrase:
            new_phrase = punched_text(lines, positions)
    else:
        if not new_phrase:
            raise SystemExit("需要 new_phrase/target_phrase，或显式 punch 位置")
        positions = auto_match_positions(lines, new_phrase)

    # Punctuation is allowed in the bottom phrase but is not part of the
    # multiset comparison. This lets a user punch punctuation deliberately.
    selected_han = Counter(ch for ch in punched_text(lines, positions) if is_cjk(ch))
    phrase_han = Counter(ch for ch in new_phrase if is_cjk(ch))
    if selected_han != phrase_han:
        missing = phrase_han - selected_han
        extra = selected_han - phrase_han
        details = []
        if missing:
            details.append("缺少 " + "、".join(f"{ch}×{n}" for ch, n in missing.items()))
        if extra:
            details.append("多出 " + "、".join(f"{ch}×{n}" for ch, n in extra.items()))
        raise SystemExit("punch 与新句汉字不一致：" + "；".join(details))

    return lines, new_phrase, positions, parse_palette(plan.get("palette"))


def preview(
    lines: list[str], positions: list[tuple[int, int]], new_phrase: str
) -> str:
    hole_set = set(positions)
    rendered = []
    for line_index, line in enumerate(lines):
        rendered.append(
            "".join(
                "□" if (line_index, char_index) in hole_set else ch
                for char_index, ch in enumerate(line)
            )
        )
    return "\n".join(rendered) + f"\n\n新句：{new_phrase}"


def paste_textured_rect(
    target: Image.Image,
    source: Image.Image,
    box: tuple[int, int, int, int],
    radius: int,
    source_box: tuple[int, int, int, int],
) -> None:
    """Paste a rounded, textured patch from source into target."""
    x0, y0, x1, y1 = box
    width = max(1, x1 - x0)
    height = max(1, y1 - y0)
    patch = source.crop(source_box).resize((width, height), Image.LANCZOS)
    mask = Image.new("L", (width, height), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, width - 1, height - 1), radius=radius, fill=255
    )
    target.paste(patch, (x0, y0), mask)


def torn_paper_mask(
    size: tuple[int, int], seed: int, roughness: float
) -> tuple[Image.Image, list[tuple[float, float]]]:
    """Build a subtly hand-torn paper-edge mask.

    Edges follow a smoothed random walk so they wobble like torn stock rather
    than a saw blade. The mask is drawn at 3x and downsampled for a clean,
    slightly translucent edge. `roughness` is in pixels at output scale.
    """
    width, height = size
    if roughness <= 0:
        return (
            Image.new("L", (width, height), 255),
            [(0.0, 0.0), (width, 0.0), (width, height), (0.0, height)],
        )
    supersample = 3
    canvas = (width * supersample, height * supersample)
    rough = max(0.4, float(roughness)) * supersample
    step = max(2.2, min(canvas) * 0.045)

    # Keep the same seed per tile so output stays reproducible.
    rnd = random.Random(seed)

    def edge_offsets(length: float) -> list[float]:
        count = max(4, int(length / step) + 1)
        walk = [0.0]
        for _ in range(1, count):
            walk.append(walk[-1] + rnd.uniform(-step * 0.32, step * 0.32))
        mean = sum(walk) / len(walk)
        walk = [value - mean for value in walk]
        peak = max(1e-6, max(abs(value) for value in walk))
        scale = rough * rnd.uniform(0.55, 0.95) / peak
        offsets = [value * scale for value in walk]

        # A couple of small tears bite a little deeper into the sheet.
        for _ in range(rnd.randint(1, 3)):
            index = rnd.randrange(count)
            offsets[index] -= rnd.uniform(rough * 0.35, rough * 0.85)
        return offsets

    points: list[tuple[float, float]] = []

    count = max(4, int(canvas[0] / step))
    offsets = edge_offsets(canvas[0])
    for index in range(count + 1):
        x = canvas[0] * index / count
        y = min(max(0.0, offsets[min(index, len(offsets) - 1)]), rough * 1.6)
        points.append((x, y))

    count = max(4, int(canvas[1] / step))
    offsets = edge_offsets(canvas[1])
    for index in range(count + 1):
        y = canvas[1] * index / count
        x = canvas[0] - min(
            max(0.0, offsets[min(index, len(offsets) - 1)]), rough * 1.6
        )
        points.append((x, y))

    count = max(4, int(canvas[0] / step))
    offsets = edge_offsets(canvas[0])
    for index in range(count + 1):
        x = canvas[0] - canvas[0] * index / count
        y = canvas[1] - min(
            max(0.0, offsets[min(index, len(offsets) - 1)]), rough * 1.6
        )
        points.append((x, y))

    count = max(4, int(canvas[1] / step))
    offsets = edge_offsets(canvas[1])
    for index in range(count + 1):
        y = canvas[1] - canvas[1] * index / count
        x = min(
            max(0.0, offsets[min(index, len(offsets) - 1)]), rough * 1.6
        )
        points.append((x, y))

    mask = Image.new("L", canvas, 0)
    ImageDraw.Draw(mask).polygon(points, fill=255)
    mask = mask.resize((width, height), Image.LANCZOS)
    mask = mask.filter(ImageFilter.GaussianBlur(0.35))
    return mask, [(x / supersample, y / supersample) for x, y in points]


def render_tile_layer(
    source: Image.Image,
    source_box: tuple[int, int, int, int],
    size: tuple[int, int],
    char: str,
    font: ImageFont.FreeTypeFont,
    ink: tuple[int, int, int],
    seed: int,
    roughness: float,
) -> Image.Image:
    """Render one torn-paper character tile on its own transparent layer."""
    width, height = size
    padding = int(math.ceil(roughness * 2 + 6))
    layer = Image.new("RGBA", (width + 2 * padding, height + 2 * padding), (0, 0, 0, 0))
    mask, points = torn_paper_mask((width, height), seed, roughness)
    patch = source.crop(source_box).resize((width, height), Image.LANCZOS)

    # Each scrap comes from a slightly different sheet: a whisper of tonal
    # variation keeps the row from reading as one copied tile.
    rnd = random.Random(seed + 71)
    patch = ImageEnhance.Brightness(patch).enhance(rnd.uniform(0.982, 1.006))
    layer.paste(patch, (padding, padding), mask)

    # A light frayed fringe and a faint inner shadow along the tear.
    eroded = mask.filter(ImageFilter.MinFilter(3))
    outer_band = ImageChops.subtract(mask, eroded)
    inner_eroded = eroded.filter(ImageFilter.MinFilter(3))
    inner_band = ImageChops.subtract(eroded, inner_eroded)

    fringe = Image.new("RGBA", (width, height), (252, 246, 232, 0))
    fringe.putalpha(outer_band.point(lambda value: int(value * 0.30)))
    layer.alpha_composite(fringe, dest=(padding, padding))

    shade = Image.new("RGBA", (width, height), (74, 56, 40, 0))
    shade.putalpha(inner_band.point(lambda value: int(value * 0.22)))
    layer.alpha_composite(shade, dest=(padding, padding))

    # A few single fibres escape the edge. They are only a pixel or two long,
    # just enough for the eye to read "torn" instead of "cut".
    fray = ImageDraw.Draw(layer)
    edge_points = [(x + padding, y + padding) for x, y in points]
    center = (padding + width / 2, padding + height / 2)
    fray_count = max(10, int((width + height) / 16)) if roughness > 0 else 0
    for _ in range(fray_count):
        x, y = edge_points[rnd.randrange(len(edge_points))]
        dx = x - center[0]
        dy = y - center[1]
        length = math.hypot(dx, dy) or 1.0
        nx, ny = dx / length, dy / length
        t = rnd.uniform(-0.6, 0.6)
        nx, ny = nx + -ny * t, ny + nx * t
        norm = math.hypot(nx, ny) or 1.0
        nx, ny = nx / norm, ny / norm
        reach = rnd.uniform(0.8, max(1.2, roughness * 1.15))
        fray.line(
            [(x, y), (x + nx * reach, y + ny * reach)],
            fill=(250, 243, 229, rnd.randint(30, 62)),
            width=1,
        )

    draw_centered(
        ImageDraw.Draw(layer),
        padding + width / 2,
        padding + height / 2,
        char,
        font,
        ink,
    )
    return layer


def layout_phrase(
    phrase: str, tile_size: float, max_width: float, gap: float
) -> list[list[tuple[str, float, bool]]]:
    """Return rows of (char, width, is_tile). Punctuation is narrow and untiled."""
    items: list[tuple[str, float, bool]] = []
    for ch in phrase:
        if ch.isspace():
            continue
        if is_cjk(ch):
            items.append((ch, tile_size * 0.98, True))
        else:
            items.append((ch, tile_size * 0.48, False))

    rows: list[list[tuple[str, float, bool]]] = []
    row: list[tuple[str, float, bool]] = []
    row_width = 0.0
    for item in items:
        add = item[1] + (gap if row else 0)
        if row and row_width + add > max_width:
            rows.append(row)
            row = []
            row_width = 0.0
            add = item[1]
        row.append(item)
        row_width += add
    if row:
        rows.append(row)
    return rows


def render(
    plan: dict[str, Any],
    output_path: Path,
) -> Path:
    lines, new_phrase, positions, palette = validate_plan(plan)
    paper = palette["paper"]
    accent = palette["accent"]
    ink = palette["ink"]

    canvas = plan.get("canvas") or plan.get("size") or [1800, 2400]
    width, height = int(canvas[0]), int(canvas[1])
    if width < 600 or height < 600:
        raise SystemExit("canvas 尺寸太小，建议至少 1200×1600")
    if width * 4 != height * 3:
        print(
            "提示：当前画布不是 3:4，仍会按给定尺寸渲染。"
            "小红书风格建议使用 1800×2400。",
            file=sys.stderr,
        )

    margin = int(width * 0.07)
    split_y = int(height * 0.56)
    seed = int(plan.get("seed", 42))
    font_style = str(plan.get("font_style", "old-song"))
    font_path = str(plan.get("font_path") or "").strip() or None
    use_traditional = bool(plan.get("traditional", True))
    footer = plan.get("footer", "CUT FROM THE MOMENT")
    if footer is False or footer is None:
        footer = ""
    footer = str(footer).strip()

    title = str(plan.get("title", "")).strip()
    author = str(plan.get("author", "")).strip()
    if use_traditional:
        title = to_traditional(title)
        author = to_traditional(author)

    top_paper = make_surface((width, split_y), paper, seed, "paper")
    bottom_board = make_surface((width, height - split_y), accent, seed + 1, "board")
    image = Image.new("RGB", (width, height), paper)
    image.paste(top_paper, (0, 0))
    image.paste(bottom_board, (0, split_y))

    # The top sheet lies on the colored sheet, so it casts a whisper of shadow
    # along the seam. This keeps the two-color split from looking like a
    # vector rectangle stacked on another vector rectangle.
    seam_shadow = Image.new("RGBA", (width, max(8, int(height * 0.014))), (0, 0, 0, 0))
    seam_draw = ImageDraw.Draw(seam_shadow)
    seam_height = seam_shadow.height
    for offset in range(seam_height):
        alpha = int(30 * (1.0 - offset / seam_height) ** 2.1)
        seam_draw.line([(0, offset), (width, offset)], fill=(0, 0, 0, alpha))
    seam_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    seam_layer.paste(seam_shadow, (0, split_y))
    image = Image.alpha_composite(image.convert("RGBA"), seam_layer).convert("RGB")
    ImageDraw.Draw(image).line(
        [(0, split_y - 1), (width, split_y - 1)],
        fill=mix(paper, ink, 0.10),
        width=1,
    )

    max_chars = max(len(line) for line in lines)
    available_width = width - 2 * margin - int(width * 0.02)
    body_size = min(
        available_width / max(1, max_chars * 1.04),
        (split_y - 2 * margin) / max(1, len(lines) * 1.55),
        120,
    )

    if body_size < 24:
        raise SystemExit(
            "诗句太长，字号会小于 24px。请把长句拆成更多行，"
            "或减少每行字数。"
        )

    title_size = min(body_size * 1.15, 110)
    author_size = max(18, body_size * 0.38)
    title_font = load_font(font_style, int(title_size), font_path)
    author_font = load_font(font_style, int(author_size), font_path)
    body_font = load_font(font_style, int(body_size), font_path)

    draw = ImageDraw.Draw(image)
    cursor_y = float(margin)
    if title:
        draw_centered(
            draw,
            width / 2,
            cursor_y + title_size * 0.62,
            title,
            title_font,
            ink,
        )
        cursor_y += title_size * 1.22
    if author:
        muted_ink = mix(ink, paper, 0.38)
        draw_centered(
            draw,
            width / 2,
            cursor_y + author_size * 0.62,
            author,
            author_font,
            muted_ink,
        )
        cursor_y += author_size * 1.55

    poem_top = cursor_y + body_size * 0.55
    line_height = body_size * 1.55
    cell_width = body_size * 1.04

    # Re-check vertical fit after the title/author block.
    available_height = split_y - poem_top - margin * 0.55
    if available_height < len(lines) * line_height:
        body_size = max(
            24,
            min(
                body_size,
                available_height / max(1, len(lines) * 1.55),
            ),
        )
        line_height = body_size * 1.55
        cell_width = body_size * 1.04
        body_font = load_font(font_style, int(body_size), font_path)

    poem_width = max_chars * cell_width
    if poem_width > width - 2 * margin:
        body_size *= (width - 2 * margin) / poem_width
        line_height = body_size * 1.55
        cell_width = body_size * 1.04
        body_font = load_font(font_style, int(body_size), font_path)

    poem_height = len(lines) * line_height
    # Keep a little more air above the poem than below it, matching the
    # reference's calm top sheet while avoiding a floating text block.
    start_y = poem_top + max(0.0, (available_height - poem_height) * 0.55)

    hole_set = set(positions)
    for line_index, line in enumerate(lines):
        line_width = len(line) * cell_width
        start_x = (width - line_width) / 2
        for char_index, ch in enumerate(line):
            if (line_index, char_index) in hole_set:
                continue
            cx = start_x + char_index * cell_width + cell_width / 2
            cy = start_y + line_index * line_height + line_height / 2
            draw_centered(draw, cx, cy, ch, body_font, ink)

    # Punch holes reveal the bottom paper. Sample a matching texture patch so
    # the hole reads as the same stock, not a flat color swatch.
    hole_size = body_size * 0.94
    bottom_height = height - split_y
    hole_patch_x = width // 2 - int(hole_size) // 2
    hole_patch_y = bottom_height // 2 - int(hole_size) // 2
    for line_index, char_index in positions:
        line_width = len(lines[line_index]) * cell_width
        start_x = (width - line_width) / 2
        cx = start_x + char_index * cell_width + cell_width / 2
        cy = start_y + line_index * line_height + line_height / 2
        x0 = int(round(cx - hole_size / 2))
        y0 = int(round(cy - hole_size / 2))
        x1 = x0 + int(round(hole_size))
        y1 = y0 + int(round(hole_size))

        # Pull a small patch from the center of the lower sheet so the hole
        # shares its grain and color instead of looking like a flat swatch.
        patch_x = int(
            hole_patch_x
            + (char_index * 13 + line_index * 7) % max(1, int(hole_size * 1.2))
        )
        patch_y = int(
            hole_patch_y
            + (line_index * 17 + char_index * 11) % max(1, int(hole_size * 1.2))
        )
        patch_x = max(0, min(width - int(hole_size), patch_x))
        patch_y = max(0, min(bottom_height - int(hole_size), patch_y))
        paste_textured_rect(
            image,
            bottom_board,
            (x0, y0, x1, y1),
            radius=max(2, int(body_size * 0.045)),
            source_box=(
                patch_x,
                patch_y,
                patch_x + int(hole_size),
                patch_y + int(hole_size),
            ),
        )
        draw.rounded_rectangle(
            (x0, y0, x1, y1),
            radius=max(2, int(body_size * 0.045)),
            outline=mix(accent, ink, 0.16),
            width=max(1, int(body_size * 0.012)),
        )
        # A thin inner shadow at the top and a faint lower highlight give the
        # cut a little depth without turning it into a sticker outline.
        draw.line(
            [(x0 + 2, y0 + 1), (x1 - 2, y0 + 1)],
            fill=mix(accent, ink, 0.22),
            width=1,
        )
        draw.line(
            [(x0 + 2, y1 - 1), (x1 - 2, y1 - 1)],
            fill=mix(accent, paper, 0.18),
            width=1,
        )

    # Bottom composition: paper tiles on the accent sheet.
    han_count = sum(1 for ch in new_phrase if is_cjk(ch))
    tile_size = min(
        body_size * 1.05,
        (width - 2 * margin) / max(1, han_count) * 0.78,
        112,
    )
    tile_size = max(44, tile_size)
    gap = tile_size * 0.18
    rows = layout_phrase(new_phrase, tile_size, width - 2 * margin * 1.12, gap)
    row_height = tile_size * 1.05
    row_gap = tile_size * 0.24
    total_rows_height = len(rows) * row_height + max(0, len(rows) - 1) * row_gap
    footer_height = tile_size * 0.75 if footer else 0
    block_top = split_y + max(
        tile_size * 0.15,
        (height - split_y - total_rows_height - footer_height) * 0.72,
    )

    collage = plan.get("collage") or {}
    if not isinstance(collage, dict):
        raise SystemExit("collage 必须是对象，例如 {\"jitter\": 2, \"rotation\": 0.8}")
    scale = width / 1800.0
    tile_jitter = float(collage.get("jitter", 3.2)) * scale
    tile_rotation = float(collage.get("rotation", 1.1))
    tile_roughness = float(collage.get("roughness", 2.2)) * scale

    # Build each tile as a separate torn-paper layer so it can be nudged and
    # rotated without disturbing the poem grid.
    tile_boxes: list[tuple[int, int, int, int, str, int]] = []
    cursor_y = block_top
    punctuation_font = load_font(font_style, int(tile_size * 0.86), font_path)
    tile_font = load_font(font_style, int(tile_size * 0.76), font_path)
    tile_index = 0

    for row in rows:
        row_width = sum(item[1] for item in row) + gap * max(0, len(row) - 1)
        cursor_x = (width - row_width) / 2
        for ch, item_width, is_tile in row:
            if is_tile:
                x0 = int(round(cursor_x))
                y0 = int(round(cursor_y))
                x1 = x0 + int(round(item_width))
                y1 = y0 + int(round(row_height * 0.92))
                tile_boxes.append((x0, y0, x1, y1, ch, tile_index))
                tile_index += 1
            cursor_x += item_width + gap
        cursor_y += row_height + row_gap

    image_rgba = image.convert("RGBA")
    tile_rnd = random.Random(seed + 101)
    for x0, y0, x1, y1, ch, index in tile_boxes:
        # Each scrap is torn by hand: a hair of size variation on top of the
        # nudge and rotation below.
        size_scale = tile_rnd.uniform(0.986, 1.014)
        tile_width = max(1, int(round((x1 - x0) * size_scale)))
        tile_height = max(1, int(round((y1 - y0) * size_scale)))
        center_x = (x0 + x1) / 2
        center_y = (y0 + y1) / 2
        # Sample the paper stock from the top sheet for a tactile tile.
        source_x = max(0, min(width - tile_width, x0 + int(tile_size * 0.2)))
        source_y = max(
            0,
            min(
                split_y - tile_height,
                int((y0 * 0.37) % max(1, split_y - tile_height)),
            ),
        )
        layer = render_tile_layer(
            top_paper,
            (source_x, source_y, source_x + tile_width, source_y + tile_height),
            (tile_width, tile_height),
            ch,
            tile_font,
            ink,
            seed + 1000 + index,
            tile_roughness,
        )
        angle = tile_rnd.uniform(-tile_rotation, tile_rotation)
        rotated = layer.rotate(angle, resample=Image.BICUBIC, expand=True)

        jitter_x = tile_rnd.uniform(-tile_jitter, tile_jitter)
        jitter_y = tile_rnd.uniform(-tile_jitter, tile_jitter)
        center_x += jitter_x
        center_y += jitter_y

        alpha = rotated.split()[-1]
        shadow = Image.new("RGBA", rotated.size, (0, 0, 0, 0))
        shadow.putalpha(alpha.point(lambda value: int(value * 0.34)))
        shadow = shadow.filter(
            ImageFilter.GaussianBlur(max(1.8, 2.6 * scale))
        )
        shadow_x = int(round(center_x - rotated.width / 2 + 1.3 * scale))
        shadow_y = int(round(center_y - rotated.height / 2 + 2.4 * scale))
        image_rgba.alpha_composite(shadow, dest=(shadow_x, shadow_y))
        image_rgba.alpha_composite(
            rotated,
            dest=(
                int(round(center_x - rotated.width / 2)),
                int(round(center_y - rotated.height / 2)),
            ),
        )

    image = image_rgba.convert("RGB")
    draw = ImageDraw.Draw(image)

    # Punctuation sits directly on the accent sheet, without a tile.
    cursor_y = block_top
    for row in rows:
        row_width = sum(item[1] for item in row) + gap * max(0, len(row) - 1)
        cursor_x = (width - row_width) / 2
        for ch, item_width, is_tile in row:
            if not is_tile:
                draw_centered(
                    draw,
                    cursor_x + item_width / 2,
                    cursor_y + row_height * 0.46,
                    ch,
                    punctuation_font,
                    paper,
                )
            cursor_x += item_width + gap
        cursor_y += row_height + row_gap

    if footer:
        footer_font = load_font(
            font_style, max(13, int(tile_size * 0.2)), font_path
        )
        footer_color = mix(paper, accent, 0.52)
        draw_spaced_text(
            draw,
            footer.upper(),
            footer_font,
            footer_color,
            width / 2,
            height - margin * 0.55,
            spacing=max(1.0, tile_size * 0.07),
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    metadata = PngInfo()
    metadata.add_text(
        "Paper texture attribution",
        "Rice Paper by Atle Mo / Subtle Patterns. "
        "https://www.toptal.com/designers/subtlepatterns/rice-paper/",
    )
    metadata.add_text(
        "Paper texture license",
        "CC BY-SA 3.0: https://creativecommons.org/licenses/by-sa/3.0/ "
        "(applies to the adapted paper texture).",
    )
    metadata.add_text(
        "Paper texture modifications",
        "Grayscale, proportional resizing, seamless tiling, seeded sampling, "
        "luminance normalization and palette tinting.",
    )
    image.save(output_path, "PNG", optimize=True, pnginfo=metadata)
    return output_path


def demo_plan() -> dict[str, Any]:
    return {
        "title": "过零丁洋",
        "author": "文天祥",
        "lines": [
            "辛苦遭逢起一经，干戈寥落四周星。",
            "山河破碎风飘絮，身世浮沉雨打萍。",
            "惶恐滩头说惶恐，零丁洋里叹零丁。",
            "人生自古谁无死，留取丹心照汗青。",
        ],
        "new_phrase": "生照山河，死落零丁。",
        "palette": "vermilion",
        "canvas": [1800, 2400],
        "footer": "CUT FROM THE MOMENT",
        "seed": 42,
    }


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Render a Xiaohongshu-style cyber poetry punch image."
    )
    parser.add_argument("plan", nargs="?", help="Path to plan JSON")
    parser.add_argument(
        "-o",
        "--output",
        default="cyber-poetry-punch.png",
        help="Output PNG path",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Print the leftover poem and new phrase without rendering",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Render the built-in 过零丁洋 demo",
    )
    args = parser.parse_args()

    if args.demo:
        plan = demo_plan()
    else:
        if not args.plan:
            parser.error("需要 plan JSON，或使用 --demo")
        plan_path = Path(args.plan)
        try:
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise SystemExit(f"找不到 plan：{plan_path}")
        except json.JSONDecodeError as exc:
            raise SystemExit(f"plan JSON 解析失败：{exc}")

    lines, new_phrase, positions, _palette = validate_plan(plan)
    if args.check:
        print(preview(lines, positions, new_phrase))
        return

    output = render(plan, Path(args.output))
    print(f"已生成：{output}")
    print("挖字位置：" + ", ".join(f"({line},{index})" for line, index in positions))
    print("新句：" + new_phrase)


if __name__ == "__main__":
    main()
