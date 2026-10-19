import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageChops, ImageStat


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import render_punch_poem as renderer


class PaperTextureTests(unittest.TestCase):
    def test_bundled_scan(self):
        with Image.open(renderer.BUNDLED_PAPER) as image:
            self.assertEqual(image.size, (500, 500))
            self.assertGreater(ImageStat.Stat(image.convert("L")).stddev[0], 3)

    def test_seed_reproducibility_and_variation(self):
        first = renderer.make_surface((900, 672), (242, 232, 213), 42)
        same = renderer.make_surface((900, 672), (242, 232, 213), 42)
        other = renderer.make_surface((900, 672), (242, 232, 213), 43)
        self.assertIsNone(ImageChops.difference(first, same).getbbox())
        self.assertIsNotNone(ImageChops.difference(first, other).getbbox())

    def test_palette_and_relief(self):
        for palette in renderer.PALETTES.values():
            for kind, key in (("paper", "paper"), ("board", "accent")):
                with self.subTest(palette=palette, kind=kind):
                    color = renderer.hex_to_rgb(palette[key])
                    image = renderer.make_surface((900, 672), color, 42, kind)
                    stats = ImageStat.Stat(image)
                    self.assertEqual(image.mode, "RGB")
                    self.assertEqual(image.size, (900, 672))
                    self.assertLess(
                        max(abs(a - b) for a, b in zip(stats.mean, color)), 0.2
                    )
                    self.assertGreater(stats.stddev[0], 3 if kind == "paper" else 0.8)
                    self.assertLess(stats.stddev[0], 8 if kind == "paper" else 3)

    def test_texture_comes_from_scan(self):
        size = (900, 672)
        surface = renderer.make_surface(size, (128, 128, 128), 42).convert("L")
        with Image.open(renderer.BUNDLED_PAPER) as source:
            tile = source.convert("L").resize((338, 338), Image.Resampling.LANCZOS)
        rnd = renderer.random.Random(42)
        offset = (rnd.randrange(338), rnd.randrange(338))
        expected = Image.new("L", size)
        for y in range(-offset[1], size[1], 338):
            for x in range(-offset[0], size[0], 338):
                expected.paste(tile, (x, y))
        mean = ImageStat.Stat(expected).mean[0]
        expected = expected.point(
            lambda v: max(0, min(255, round(128 + (v - mean) * 1.6)))
        )
        self.assertIsNone(ImageChops.difference(surface, expected).getbbox())

    def test_missing_or_corrupt_texture_is_explicit(self):
        with tempfile.TemporaryDirectory() as folder:
            missing = Path(folder) / "missing.png"
            with patch.object(renderer, "BUNDLED_PAPER", missing):
                with self.assertRaisesRegex(SystemExit, "assets/textures"):
                    renderer.make_surface((600, 448), (242, 232, 213), 42)
            corrupt = Path(folder) / "corrupt.png"
            corrupt.write_bytes(b"not a png")
            with patch.object(renderer, "BUNDLED_PAPER", corrupt):
                with self.assertRaisesRegex(SystemExit, "assets/textures"):
                    renderer.make_surface((600, 448), (242, 232, 213), 42)

    def test_full_render_is_repeatable_and_attributed(self):
        plan = renderer.demo_plan()
        plan["canvas"] = [600, 800]
        with tempfile.TemporaryDirectory() as folder:
            first = renderer.render(plan, Path(folder) / "first.png")
            second = renderer.render(plan, Path(folder) / "second.png")
            self.assertEqual(first.read_bytes(), second.read_bytes())
            with Image.open(first) as image:
                self.assertEqual(image.size, (600, 800))
                self.assertIn("Atle Mo", image.info["Paper texture attribution"])
                self.assertIn("CC BY-SA 3.0", image.info["Paper texture license"])


if __name__ == "__main__":
    unittest.main()
