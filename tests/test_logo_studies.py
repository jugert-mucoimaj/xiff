"""Visual landmarks for the two logo studies, not official logo conformance."""

import unittest
from pathlib import Path

import engine


EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "logo_tests"


class LogoStudiesTests(unittest.TestCase):
    def check_image(self, name, landmarks, bounds):
        image = engine.render(engine.parse_xiff((EXAMPLES / f"{name}.xiff").read_text()))
        self.assertEqual((image.width, image.height), (800, 520))
        for x, y, expected in landmarks:
            with self.subTest(name=name, position=(x, y)):
                self.assertEqual(image.pixels[y * image.width + x], engine.parse_color(expected))
        ink = {(i % image.width, i // image.width)
               for i, pixel in enumerate(image.pixels) if min(pixel[:3]) < 200}
        self.assertEqual((min(x for x, y in ink), min(y for x, y in ink),
                          max(x for x, y in ink), max(y for x, y in ink)), bounds)
        # Neither silhouette should contain disconnected fragments.
        pending = [ink.pop()]
        while pending:
            x, y = pending.pop()
            for neighbor in ((x-1, y), (x+1, y), (x, y-1), (x, y+1)):
                if neighbor in ink:
                    ink.remove(neighbor)
                    pending.append(neighbor)
        self.assertFalse(ink, "Disconnected pieces in logo silhouette")

    def test_nike_swoosh_study(self):
        self.check_image("nike_swoosh", [
            (135, 230, "#111111"), (200, 285, "#111111"),
            (350, 260, "#111111"), (610, 174, "#111111"),
            (180, 215, "#ffffff"), (350, 320, "#ffffff"),
        ], (120, 154, 660, 319))

    def test_google_g_study(self):
        self.check_image("google_g", [
            (400, 120, "#ea4335"), (260, 260, "#fbbc05"),
            (400, 400, "#34a853"), (540, 280, "#4285f4"),
            (450, 260, "#4285f4"), (400, 200, "#ffffff"),
            (540, 180, "#ffffff"),
        ], (230, 90, 569, 429))
