#!/usr/bin/env python3
"""XIFF fundamentals prototype.

This deliberately starts smaller than SVG:

- Parse intent-style directives.
- Resolve each primitive in local x-axis coordinates.
- Transform into canvas coordinates.
- Rasterize directly to PNG with only Python's standard library.
"""

from __future__ import annotations

import argparse
import math
import re
import struct
import sys
import zlib
from dataclasses import dataclass
from pathlib import Path


HEX_RE = re.compile(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


@dataclass
class Op:
    name: str
    mods: dict[str, str]
    line: int


@dataclass
class Doc:
    width: int
    height: int
    palette: list[tuple[int, int, int, int]]
    ops: list[Op]


def parse_color(value: str) -> tuple[int, int, int, int]:
    match = HEX_RE.match(value)
    if not match:
        raise ValueError(f"bad color: {value}")
    text = match.group(1)
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    return (
        int(text[0:2], 16),
        int(text[2:4], 16),
        int(text[4:6], 16),
        255,
    )


def strip_comment(line: str) -> str:
    out = []
    for i, ch in enumerate(line):
        if ch == "#":
            maybe_hex = HEX_RE.match(line[i:].split()[0])
            if maybe_hex:
                out.append(ch)
                continue
            break
        out.append(ch)
    return "".join(out).strip()


def parse_xiff(text: str) -> Doc:
    width = 256
    height = 256
    palette = [parse_color("#ffffff"), parse_color("#000000")]
    ops: list[Op] = []
    groups: dict[str, list[Op]] = {}
    current_group: str | None = None
    group_ops: list[Op] = []

    for line_no, raw in enumerate(text.splitlines(), start=1):
        line = strip_comment(raw)
        if not line:
            continue
        parts = line.split()
        head = parts[0]
        rest = parts[1:]

        if head == "canvas":
            if len(rest) != 2:
                raise ValueError(f"line {line_no}: canvas needs width height")
            try:
                width, height = int(rest[0]), int(rest[1])
            except ValueError:
                raise ValueError(f"line {line_no}: canvas needs positive integer dimensions") from None
            if width <= 0 or height <= 0:
                raise ValueError(f"line {line_no}: canvas needs positive integer dimensions")
            continue

        if head == "palette":
            if not rest:
                raise ValueError(f"line {line_no}: palette needs at least one color")
            try:
                palette = [parse_color(part) for part in rest]
            except ValueError as exc:
                raise ValueError(f"line {line_no}: {exc}") from None
            continue

        if head == "group":
            if current_group is not None:
                raise ValueError(f"line {line_no}: nested groups are not supported yet")
            current_group = group_name(rest, line_no)
            group_ops = []
            continue

        if head == "end":
            if current_group is None:
                raise ValueError(f"line {line_no}: end without group")
            groups[current_group] = preprocess_ops(group_ops, groups)
            current_group = None
            group_ops = []
            continue

        mods: dict[str, str] = {}
        for token in rest:
            if "=" not in token:
                raise ValueError(f"line {line_no}: expected key=value, got {token}")
            key, value = token.split("=", 1)
            mods[key] = value
        op = Op(head, mods, line_no)
        if current_group is not None:
            group_ops.append(op)
        else:
            ops.append(op)

    if current_group is not None:
        raise ValueError(f"unclosed group: {current_group}")

    return Doc(width, height, palette, preprocess_ops(ops, groups))


def group_name(parts: list[str], line: int) -> str:
    if len(parts) == 1 and "=" not in parts[0]:
        return parts[0]
    mods = {}
    for token in parts:
        if "=" not in token:
            raise ValueError(f"line {line}: expected group name or name=value")
        key, value = token.split("=", 1)
        mods[key] = value
    name = mods.get("name")
    if not name:
        raise ValueError(f"line {line}: group needs a name")
    return name


def preprocess_ops(ops: list[Op], groups: dict[str, list[Op]]) -> list[Op]:
    """Expand intent directives like mirror/repeat/place into drawables."""
    out: list[Op] = []
    for op in ops:
        if op.name == "mirror":
            if not out:
                raise ValueError(f"line {op.line}: mirror needs a previous drawable")
            out.append(mirror_op(out[-1], op.mods, op.line))
            continue

        if op.name == "repeat":
            if not out:
                raise ValueError(f"line {op.line}: repeat needs a previous drawable")
            out.extend(repeat_op(out[-1], op.mods, op.line))
            continue

        if op.name == "place":
            out.extend(place_group(groups, op.mods, op.line))
            continue

        out.append(op)
    return out


def place_group(groups: dict[str, list[Op]], mods: dict[str, str], line: int) -> list[Op]:
    name = mods.get("name", mods.get("group"))
    if not name:
        raise ValueError(f"line {line}: place needs name=GROUP")
    if name not in groups:
        raise ValueError(f"line {line}: unknown group {name}")

    ox = float(mods.get("x", "0"))
    oy = float(mods.get("y", "0"))
    scale = float(mods.get("scale", "1"))
    angle = float(mods.get("angle", "0"))

    placed = []
    for src in groups[name]:
        placed.append(transform_op(src, ox, oy, scale, angle, line))
    return placed


def geometry_mods(src: Op) -> dict[str, str]:
    """Resolve aliases and implicit dimensions before transforming geometry."""
    out = dict(src.mods)
    if src.name == "circle":
        out.setdefault("x", out.get("cx", "0"))
        out.setdefault("y", out.get("cy", "0"))
    if src.name in {"circle", "arc"}:
        out.setdefault("r", out.get("radius", "10"))
    if src.name == "rect":
        out.setdefault("w", out.get("width_px", "10"))
        out.setdefault("h", out.get("height", "10"))
    if src.name in {"line", "curve", "wave"}:
        out.setdefault("length", "100" if src.name == "wave" else "10")
    if src.name == "wave":
        out.setdefault("amp", "10")
    out.setdefault("width", "0" if src.name == "circle" else "2")
    return out


def transform_op(src: Op, ox: float, oy: float, scale: float, angle: float, line: int) -> Op:
    out = geometry_mods(src)
    x = float(out.get("x", "0")) * scale
    y = float(out.get("y", "0")) * scale
    tx, ty = transform_point(x, y, ox, oy, angle)
    out["x"] = fmt(tx)
    out["y"] = fmt(ty)
    out["angle"] = fmt(float(out.get("angle", "0")) + angle + (180 if scale < 0 else 0))

    for key in ("length", "width", "bend_at", "bend", "amp", "r", "w", "h"):
        if key in out:
            out[key] = fmt(float(out[key]) * abs(scale))
    return Op(src.name, out, line)


def mirror_op(src: Op, mods: dict[str, str], line: int) -> Op:
    axis = mods.get("axis", "y")
    pivot = float(mods.get("pivot", "0"))
    if axis not in {"x", "y"}:
        raise ValueError(f"line {line}: mirror axis must be x or y")

    out = geometry_mods(src)
    x = float(out.get("x", "0"))
    y = float(out.get("y", "0"))
    angle = float(out.get("angle", "0"))

    if axis == "y":
        out["x"] = fmt(2.0 * pivot - x)
        out["angle"] = fmt(180.0 - angle)
    else:
        out["y"] = fmt(2.0 * pivot - y)
        out["angle"] = fmt(-angle)

    # Reflection changes handedness, so local perpendicular offsets flip.
    for key in ("bend", "amp"):
        if key in out:
            out[key] = fmt(-float(out[key]))

    if src.name == "arc":
        out["start"] = fmt(-float(out.get("start", "0")))
        out["end"] = fmt(-float(out.get("end", "360")))
    elif src.name == "rect":
        # Reflection reverses the local y-axis. Move to the opposite
        # corner so the rectangle can retain positive dimensions.
        x, y = transform_point(
            0, -float(out["h"]), float(out.get("x", "0")),
            float(out.get("y", "0")), float(out["angle"]),
        )
        out["x"], out["y"] = fmt(x), fmt(y)

    if "color" in mods:
        out["color"] = mods["color"]
    if "width" in mods:
        out["width"] = mods["width"]

    return Op(src.name, out, line)


def repeat_op(src: Op, mods: dict[str, str], line: int) -> list[Op]:
    count = int(float(mods.get("count", "2")))
    if count < 1:
        return []

    dx = float(mods.get("dx", "0"))
    dy = float(mods.get("dy", "0"))
    dangle = float(mods.get("dangle", mods.get("angle_step", "0")))
    dbend = float(mods.get("dbend", "0"))
    dwidth = float(mods.get("dwidth", "0"))

    copies = []
    # count includes the original drawable, which is already in out.
    for i in range(1, count):
        out = dict(src.mods)
        out["x"] = fmt(float(out.get("x", "0")) + dx * i)
        out["y"] = fmt(float(out.get("y", "0")) + dy * i)
        out["angle"] = fmt(float(out.get("angle", "0")) + dangle * i)
        if "bend" in out:
            out["bend"] = fmt(float(out["bend"]) + dbend * i)
        if "width" in out:
            out["width"] = fmt(float(out["width"]) + dwidth * i)
        if "color" in mods:
            out["color"] = mods["color"]
        copies.append(Op(src.name, out, line))
    return copies


def fmt(value: float) -> str:
    if abs(value) < 1e-9:
        value = 0.0
    return f"{value:.6g}"


class Image:
    def __init__(self, width: int, height: int, background: tuple[int, int, int, int]):
        self.width = width
        self.height = height
        self.pixels = [background] * (width * height)

    def blend(self, x: int, y: int, color: tuple[int, int, int, int], alpha: float) -> None:
        if x < 0 or y < 0 or x >= self.width or y >= self.height:
            return
        alpha = max(0.0, min(1.0, alpha)) * (color[3] / 255.0)
        if alpha <= 0:
            return
        idx = y * self.width + x
        old = self.pixels[idx]
        inv = 1.0 - alpha
        self.pixels[idx] = (
            round(old[0] * inv + color[0] * alpha),
            round(old[1] * inv + color[1] * alpha),
            round(old[2] * inv + color[2] * alpha),
            255,
        )

    def write_png(self, path: str) -> None:
        raw = bytearray()
        for y in range(self.height):
            raw.append(0)
            for x in range(self.width):
                raw.extend(self.pixels[y * self.width + x])

        def chunk(name: bytes, data: bytes) -> bytes:
            return (
                struct.pack(">I", len(data))
                + name
                + data
                + struct.pack(">I", zlib.crc32(name + data) & 0xFFFFFFFF)
            )

        png = bytearray(b"\x89PNG\r\n\x1a\n")
        png.extend(chunk(b"IHDR", struct.pack(">IIBBBBB", self.width, self.height, 8, 6, 0, 0, 0)))
        png.extend(chunk(b"IDAT", zlib.compress(bytes(raw), 9)))
        png.extend(chunk(b"IEND", b""))
        with open(path, "wb") as handle:
            handle.write(png)


def num(mods: dict[str, str], key: str, default: float) -> float:
    return float(mods.get(key, default))


def color(doc: Doc, mods: dict[str, str]) -> tuple[int, int, int, int]:
    idx = int(float(mods.get("color", "1")))
    if idx < 0 or idx >= len(doc.palette):
        idx = 1 if len(doc.palette) > 1 else 0
    return doc.palette[idx]


def transform_point(x: float, y: float, ox: float, oy: float, angle_deg: float) -> tuple[float, float]:
    theta = math.radians(angle_deg)
    c = math.cos(theta)
    s = math.sin(theta)
    return ox + x * c - y * s, oy + x * s + y * c


def quadratic_from_bend(length: float, bend_at: float, bend: float) -> tuple[float, float, float]:
    """Solve y = ax^2 + bx + c through (0,0), (length,0), (bend_at,bend)."""
    if abs(length) < 1e-9:
        return 0.0, 0.0, 0.0
    # Clamp relative to length so tiny and reversed curves remain valid.
    fraction = max(1e-6, min(1.0 - 1e-6, bend_at / length))
    bend_at = fraction * length
    c = 0.0
    # Since y(0)=0 and y(length)=0, b = -a*length.
    # bend = a*bend_at^2 - a*length*bend_at.
    a = bend / (bend_at * bend_at - length * bend_at)
    b = -a * length
    return a, b, c


def line_points(mods: dict[str, str]) -> list[tuple[float, float]]:
    ox = num(mods, "x", 0.0)
    oy = num(mods, "y", 0.0)
    length = num(mods, "length", 10.0)
    angle = num(mods, "angle", 0.0)
    return [
        transform_point(0.0, 0.0, ox, oy, angle),
        transform_point(length, 0.0, ox, oy, angle),
    ]


def curve_points(mods: dict[str, str], samples: int = 160) -> list[tuple[float, float]]:
    ox = num(mods, "x", 0.0)
    oy = num(mods, "y", 0.0)
    length = num(mods, "length", 10.0)
    angle = num(mods, "angle", 0.0)
    bend_at = num(mods, "bend_at", length / 2.0)
    bend = num(mods, "bend", 0.0)
    a, b, c = quadratic_from_bend(length, bend_at, bend)

    pts = []
    for i in range(samples + 1):
        x = length * i / samples
        y = a * x * x + b * x + c
        pts.append(transform_point(x, y, ox, oy, angle))
    return pts


def wave_points(mods: dict[str, str], samples: int = 220) -> list[tuple[float, float]]:
    ox = num(mods, "x", 0.0)
    oy = num(mods, "y", 0.0)
    length = num(mods, "length", 100.0)
    amp = num(mods, "amp", 10.0)
    cycles = num(mods, "cycles", 1.0)
    angle = num(mods, "angle", 0.0)
    pts = []
    for i in range(samples + 1):
        t = i / samples
        x = length * t
        y = math.sin(t * math.tau * cycles) * amp
        pts.append(transform_point(x, y, ox, oy, angle))
    return pts


def arc_points(mods: dict[str, str], samples: int = 180) -> list[tuple[float, float]]:
    ox = num(mods, "x", 0.0)
    oy = num(mods, "y", 0.0)
    radius = num(mods, "r", num(mods, "radius", 10.0))
    start = math.radians(num(mods, "start", 0.0))
    end = math.radians(num(mods, "end", 360.0))
    rotate = num(mods, "angle", 0.0)

    span = end - start
    steps = max(8, int(samples * abs(span) / math.tau))
    pts = []
    for i in range(steps + 1):
        t = i / steps
        theta = start + span * t
        x = math.cos(theta) * radius
        y = math.sin(theta) * radius
        pts.append(transform_point(x, y, ox, oy, rotate))
    return pts


def draw_polyline(img: Image, pts: list[tuple[float, float]], width: float, ink: tuple[int, int, int, int]) -> None:
    radius = max(0.5, width / 2.0)
    for p0, p1 in zip(pts, pts[1:]):
        draw_segment(img, p0, p1, radius, ink)


def draw_circle(img: Image, mods: dict[str, str], ink: tuple[int, int, int, int]) -> None:
    cx = num(mods, "x", num(mods, "cx", 0.0))
    cy = num(mods, "y", num(mods, "cy", 0.0))
    radius = num(mods, "r", num(mods, "radius", 10.0))
    stroke_width = num(mods, "width", 0.0)
    fill = mods.get("fill", "1") not in {"0", "false", "no"}

    min_x = math.floor(cx - radius - stroke_width - 1)
    max_x = math.ceil(cx + radius + stroke_width + 1)
    min_y = math.floor(cy - radius - stroke_width - 1)
    max_y = math.ceil(cy + radius + stroke_width + 1)

    for py in range(min_y, max_y + 1):
        for px in range(min_x, max_x + 1):
            dist = math.hypot(px + 0.5 - cx, py + 0.5 - cy)
            if fill:
                alpha = radius + 0.5 - dist
            else:
                half = max(0.5, stroke_width / 2.0)
                alpha = half + 0.5 - abs(dist - radius)
            img.blend(px, py, ink, alpha)


def draw_rect(img: Image, mods: dict[str, str], ink: tuple[int, int, int, int]) -> None:
    ox = num(mods, "x", 0.0)
    oy = num(mods, "y", 0.0)
    w = num(mods, "w", num(mods, "width_px", 10.0))
    h = num(mods, "h", num(mods, "height", 10.0))
    angle = num(mods, "angle", 0.0)

    theta = math.radians(angle)
    c = math.cos(-theta)
    s = math.sin(-theta)
    corners = [
        transform_point(0, 0, ox, oy, angle),
        transform_point(w, 0, ox, oy, angle),
        transform_point(w, h, ox, oy, angle),
        transform_point(0, h, ox, oy, angle),
    ]
    min_x = math.floor(min(p[0] for p in corners) - 1)
    max_x = math.ceil(max(p[0] for p in corners) + 1)
    min_y = math.floor(min(p[1] for p in corners) - 1)
    max_y = math.ceil(max(p[1] for p in corners) + 1)

    for py in range(min_y, max_y + 1):
        for px in range(min_x, max_x + 1):
            dx = px + 0.5 - ox
            dy = py + 0.5 - oy
            lx = dx * c - dy * s
            ly = dx * s + dy * c
            inside_x = min(lx, w - lx)
            inside_y = min(ly, h - ly)
            edge = min(inside_x, inside_y)
            alpha = edge + 0.5
            img.blend(px, py, ink, alpha)


def draw_segment(
    img: Image,
    p0: tuple[float, float],
    p1: tuple[float, float],
    radius: float,
    ink: tuple[int, int, int, int],
) -> None:
    x0, y0 = p0
    x1, y1 = p1
    min_x = math.floor(min(x0, x1) - radius - 1)
    max_x = math.ceil(max(x0, x1) + radius + 1)
    min_y = math.floor(min(y0, y1) - radius - 1)
    max_y = math.ceil(max(y0, y1) + radius + 1)
    vx = x1 - x0
    vy = y1 - y0
    seg_len2 = vx * vx + vy * vy

    for py in range(min_y, max_y + 1):
        for px in range(min_x, max_x + 1):
            cx = px + 0.5
            cy = py + 0.5
            if seg_len2 < 1e-9:
                dist = math.hypot(cx - x0, cy - y0)
            else:
                t = ((cx - x0) * vx + (cy - y0) * vy) / seg_len2
                t = max(0.0, min(1.0, t))
                qx = x0 + vx * t
                qy = y0 + vy * t
                dist = math.hypot(cx - qx, cy - qy)
            alpha = radius + 0.5 - dist
            img.blend(px, py, ink, alpha)


def render(doc: Doc) -> Image:
    bg = doc.palette[0] if doc.palette else (255, 255, 255, 255)
    img = Image(doc.width, doc.height, bg)

    for op in doc.ops:
        ink = color(doc, op.mods)
        width = num(op.mods, "width", 2.0)
        if op.name == "line":
            draw_polyline(img, line_points(op.mods), width, ink)
        elif op.name == "curve":
            draw_polyline(img, curve_points(op.mods), width, ink)
        elif op.name == "wave":
            draw_polyline(img, wave_points(op.mods), width, ink)
        elif op.name == "arc":
            draw_polyline(img, arc_points(op.mods), width, ink)
        elif op.name == "circle":
            draw_circle(img, op.mods, ink)
        elif op.name == "rect":
            draw_rect(img, op.mods, ink)
        else:
            raise ValueError(f"line {op.line}: unknown directive {op.name}")

    return img


def render_text_to_png(text: str, out_path: str | Path) -> Path:
    """Parse XIFF source text, render it, and write a PNG."""
    doc = parse_xiff(text)
    out = Path(out_path)
    render(doc).write_png(str(out))
    return out


def render_file(in_path: str | Path, out_path: str | Path) -> Path:
    """Render a .xiff file to a PNG path."""
    source = Path(in_path).read_text(encoding="utf-8")
    return render_text_to_png(source, out_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="xiff",
        description="Render XIFF intent-geometry files directly to PNG.",
    )
    parser.add_argument("input", help="input .xiff file")
    parser.add_argument("output", help="output .png file")
    args = parser.parse_args(argv)

    render_file(args.input, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
