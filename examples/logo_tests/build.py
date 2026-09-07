"""Build two logo studies with the existing XIFF fundamentals engine.

The swoosh deliberately exposes a language limitation: variable-width
strokes currently require a sequence of short lines. No renderer changes
or external graphics libraries are used.
"""

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import engine


def tapered_curve(mods, start_width, end_width, samples=90):
    points = engine.curve_points(mods, samples=samples)
    lines = []
    for i, (a, b) in enumerate(zip(points, points[1:])):
        t = (i + 0.5) / samples
        width = start_width * (1 - t) + end_width * t
        dx, dy = b[0] - a[0], b[1] - a[1]
        lines.append(
            f"line x={a[0]:.6f} y={a[1]:.6f} length={math.hypot(dx, dy):.6f} "
            f"angle={math.degrees(math.atan2(dy, dx)):.6f} width={width:.6f} color=1"
        )
    return lines


def swoosh_source():
    lines = [
        "# Nike swoosh study: two intent curves with widths expanded to line segments.",
        "# Hook: narrow tip to broad heel. Blade: broad heel to narrow tip.",
        "canvas 800 520",
        "palette #ffffff #111111",
    ]
    for start, end, bend, widths in [
        ((170, 175), (205, 290), 54, (0, 60)),
        ((205, 290), (660, 155), 13, (60, 0)),
    ]:
        dx, dy = end[0] - start[0], end[1] - start[1]
        length = math.hypot(dx, dy)
        lines.extend(tapered_curve({
            "x": str(start[0]), "y": str(start[1]),
            "length": str(length), "angle": str(math.degrees(math.atan2(dy, dx))),
            "bend_at": str(length / 2), "bend": str(bend),
        }, *widths))
    return "\n".join(lines) + "\n"


def google_source():
    lines = [
        "# Google G study. Narrow concentric arcs approximate flat color joins.",
        "# Thick arcs currently have round caps, so each band is expanded here.",
        "canvas 800 520",
        "palette #ffffff #4285f4 #ea4335 #fbbc05 #34a853",
    ]
    for start, end, color in [(-8.45, 45, 1), (45, 140, 4), (140, 195, 3), (195, 315, 2)]:
        for radius in range(111, 170):
            lines.append(
                f"arc x=400 y=260 r={radius} start={start} end={end} width=2 color={color}"
            )
    lines.append("rect x=400 y=235 w=166 h=55 color=1")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    folder = Path(__file__).resolve().parent
    (folder / "nike_swoosh.xiff").write_text(swoosh_source(), encoding="utf-8")
    (folder / "google_g.xiff").write_text(google_source(), encoding="utf-8")
    for name in ("nike_swoosh", "google_g"):
        engine.render_file(folder / f"{name}.xiff", folder / f"{name}.png")
        print(f"Rendered {name}.png")
