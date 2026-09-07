import tempfile
import unittest
from pathlib import Path

import engine
import xiff


class EngineTests(unittest.TestCase):
    def test_parse_basic_curve_expands_to_doc(self):
        doc = engine.parse_xiff(
            "canvas 120 80\n"
            "palette #fff #111\n"
            "curve x=10 y=60 length=90 bend_at=30 bend=-20 width=4 color=1\n"
        )
        self.assertEqual(doc.width, 120)
        self.assertEqual(doc.height, 80)
        self.assertEqual(len(doc.ops), 1)
        self.assertEqual(doc.ops[0].name, "curve")

    def test_mirror_expands_previous_drawable(self):
        doc = engine.parse_xiff(
            "canvas 200 200\n"
            "line x=60 y=170 length=130 angle=-72 width=10 color=1\n"
            "mirror axis=y pivot=100\n"
        )
        self.assertEqual(len(doc.ops), 2)
        self.assertEqual(doc.ops[1].mods["x"], "140")
        self.assertEqual(doc.ops[1].mods["angle"], "252")

    def test_group_place_scales_drawables(self):
        doc = engine.parse_xiff(
            "canvas 200 200\n"
            "group name=A\n"
            "  line x=10 y=20 length=100 angle=0 width=8 color=1\n"
            "end\n"
            "place name=A x=50 y=60 scale=0.5 angle=10\n"
        )
        self.assertEqual(len(doc.ops), 1)
        self.assertEqual(doc.ops[0].mods["x"], "53.1876")
        self.assertEqual(doc.ops[0].mods["y"], "70.7163")
        self.assertEqual(doc.ops[0].mods["length"], "50")
        self.assertEqual(doc.ops[0].mods["width"], "4")

    def test_render_file_writes_png(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "sample.xiff"
            output = root / "sample.png"
            source.write_text(
                "canvas 64 48\n"
                "palette #fff #111\n"
                "circle x=32 y=24 r=12 color=1\n",
                encoding="utf-8",
            )
            engine.render_file(source, output)
            data = output.read_bytes()
            self.assertTrue(data.startswith(b"\x89PNG\r\n\x1a\n"))
            self.assertGreater(len(data), 100)

    def test_public_package_import(self):
        self.assertIs(xiff.parse_xiff, engine.parse_xiff)

    def test_group_scale_matches_explicit_geometry(self):
        cases = [
            ("circle cx=10 cy=12 radius=4", "circle x=20 y=24 r=8"),
            ("rect x=5 y=6 width_px=8 height=4", "rect x=10 y=12 w=16 h=8"),
            ("line x=5 y=6", "line x=10 y=12 length=20 width=4"),
            ("arc x=10 y=12 start=0 end=90", "arc x=20 y=24 r=20 width=4 start=0 end=90"),
            ("wave x=5 y=12 length=20", "wave x=10 y=24 length=40 amp=20 width=4"),
        ]
        for shape, expected in cases:
            with self.subTest(shape=shape):
                placed = engine.parse_xiff(
                    f"canvas 80 80\ngroup G\n{shape}\nend\nplace name=G scale=2\n"
                )
                explicit = engine.parse_xiff(f"canvas 80 80\n{expected}\n")
                self.assertEqual(engine.render(placed).pixels, engine.render(explicit).pixels)

    def test_mirror_matches_reflected_pixels(self):
        shapes = [
            "rect x=12 y=16 w=20 h=10",
            "rect x=30 y=16 w=20 h=10 angle=90",
            "arc x=20 y=20 r=10 start=0 end=90",
            "circle cx=20 cy=25 radius=6",
            "wave x=10 y=20 length=20",
        ]
        for shape in shapes:
            for axis in ("x", "y"):
                with self.subTest(shape=shape, axis=axis):
                    doc = engine.parse_xiff(f"canvas 80 80\n{shape}\nmirror axis={axis} pivot=40\n")
                    original, mirrored = [
                        engine.render(engine.Doc(80, 80, doc.palette, [op]))
                        for op in doc.ops
                    ]
                    expected = [
                        original.pixels[(79-y if axis == "x" else y)*80 + (79-x if axis == "y" else x)]
                        for y in range(80) for x in range(80)
                    ]
                    self.assertEqual(mirrored.pixels, expected)

    def test_invalid_document_has_line_number(self):
        for source in ("canvas 0 10", "canvas -1 10", "canvas a 10", "palette", "palette invalid"):
            with self.subTest(source=source):
                with self.assertRaisesRegex(ValueError, "line 1:"):
                    engine.parse_xiff(source)

    def test_tiny_and_reversed_curve_pass_through_bend(self):
        for length in (1e-6, -10):
            with self.subTest(length=length):
                bend_at = length / 2
                a, b, c = engine.quadratic_from_bend(length, bend_at, 1)
                self.assertAlmostEqual(a*bend_at**2 + b*bend_at + c, 1)
                self.assertAlmostEqual(a*length**2 + b*length + c, 0)


if __name__ == "__main__":
    unittest.main()
