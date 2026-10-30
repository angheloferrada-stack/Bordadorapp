import os
import tempfile
import unittest

import numpy as np
import pyembroidery as pe

import engine as E


def square(x, y, side):
    return [(x, y), (x + side, y), (x + side, y + side), (x, y + side)]


class FillTests(unittest.TestCase):
    def test_fill_points_stay_inside_shape(self):
        s = E.Shape(square(100, 100, 20), kind="fill", fill_angle=30)
        lines = s.polylines()
        self.assertGreater(len(lines), 10)
        for line in lines:
            self.assertTrue(np.all(line >= 100 - 0.01))
            self.assertTrue(np.all(line <= 120 + 0.01))

    def test_no_stitch_longer_than_limit(self):
        s = E.Shape(square(0, 0, 60), kind="fill", fill_angle=10)
        for line in s.polylines():
            steps = np.hypot(*np.diff(line, axis=0).T)
            self.assertLessEqual(steps.max(), E.STITCH_MM + 1e-6)

    def test_angle_changes_stitch_direction(self):
        rect = [(0, 0), (60, 0), (60, 10), (0, 10)]
        horiz = np.vstack(E.Shape(rect, fill_angle=0).polylines())
        vert = np.vstack(E.Shape(rect, fill_angle=90).polylines())
        self.assertGreater(np.ptp(horiz[:, 0]), 40)
        self.assertGreater(np.ptp(vert[:, 1]), 8)

    def test_hole_is_not_filled(self):
        outer = square(0, 0, 40)
        hole = square(10, 10, 20)
        s = E.Shape([outer, hole], fill_angle=45)
        pts = np.vstack(s.polylines())
        center = pts[(np.abs(pts[:, 0] - 20) < 8) & (np.abs(pts[:, 1] - 20) < 8)]
        self.assertEqual(len(center), 0)

    def test_contains_respects_hole(self):
        s = E.Shape([square(0, 0, 40), square(10, 10, 20)])
        self.assertTrue(s.contains(5, 5))
        self.assertFalse(s.contains(20, 20))


class RunTests(unittest.TestCase):
    def test_outline_closes_on_start_point(self):
        s = E.Shape(square(0, 0, 30), kind="run")
        line = s.polylines()[0]
        self.assertTrue(np.allclose(line[0], line[-1]))
        perimeter = np.hypot(*np.diff(line, axis=0).T).sum()
        self.assertAlmostEqual(perimeter, 120, places=3)


class CacheTests(unittest.TestCase):
    def test_cache_reused_until_shape_changes(self):
        s = E.Shape(square(0, 0, 30))
        first = s.polylines()
        self.assertIs(first, s.polylines())
        s.translate(5, 0)
        self.assertIsNot(first, s.polylines())


class FileTests(unittest.TestCase):
    def test_write_and_read_back(self):
        shapes = [
            E.Shape(square(0, 0, 20), color="#1e3a8a"),
            E.Shape(square(30, 0, 10), kind="run", color="#b91c1c"),
        ]
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "t.dst")
            info = E.write_dst(shapes, path)
            self.assertGreater(os.path.getsize(path), 512)
            pat = pe.read(path)
            self.assertGreater(len(pat.stitches), 50)
            self.assertTrue(info["fits"])

    def test_analyze_matches_build(self):
        shapes = [E.Shape(square(0, 0, 40), fill_angle=20),
                  E.Shape(square(60, 0, 20), kind="run", color="#b91c1c")]
        _, built = E.build_pattern(shapes)
        self.assertEqual(E.analyze(shapes)["stitches"], built["stitches"])

    def test_design_is_centered_and_sized_right(self):
        shapes = [E.Shape(square(5, 5, 50))]   # 50 x 50 mm
        pat, _ = E.build_pattern(shapes)
        real = [s for s in pat.stitches if s[2] != pe.END]
        xs = [s[0] for s in real]
        ys = [s[1] for s in real]
        self.assertAlmostEqual((max(xs) - min(xs)) / 10, 50, delta=0.6)
        self.assertAlmostEqual((max(ys) - min(ys)) / 10, 50, delta=0.6)
        self.assertAlmostEqual((max(xs) + min(xs)) / 20, E.DEFAULT_HOOP[0] / 2, delta=0.6)
        self.assertAlmostEqual((max(ys) + min(ys)) / 20, E.DEFAULT_HOOP[1] / 2, delta=0.6)

    def test_color_change_is_written(self):
        shapes = [E.Shape(square(0, 0, 20), color="#1e3a8a"),
                  E.Shape(square(30, 0, 20), color="#b91c1c")]
        pat, _ = E.build_pattern(shapes)
        self.assertTrue(any(s[2] == pe.COLOR_CHANGE for s in pat.stitches))

    def test_too_big_is_flagged(self):
        _, info = E.build_pattern([E.Shape(square(0, 0, 400))])
        self.assertFalse(info["fits"])

    def test_custom_small_hoop(self):
        shapes = [E.Shape(square(0, 0, 50))]
        self.assertTrue(E.analyze(shapes, hoop=(100, 100))["fits"])
        self.assertFalse(E.analyze([E.Shape(square(0, 0, 120))], hoop=(100, 100))["fits"])


class ImportTests(unittest.TestCase):
    def test_svg_import_keeps_hole_and_stroke(self):
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">'
            '<path d="M10 10 L90 10 L90 90 L10 90 Z M30 30 L30 70 L70 70 L70 30 Z" fill="#ff0000"/>'
            '<rect x="0" y="0" width="5" height="5" stroke="#00ff00" fill="none"/>'
            '</svg>')
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "t.svg")
            with open(path, "w") as f:
                f.write(svg)
            shapes = E.svg_to_shapes(path, width_mm=200)
        self.assertEqual(len(shapes), 2)
        fill, run = shapes
        self.assertEqual(fill.kind, "fill")
        self.assertEqual(fill.color, "#ff0000")
        self.assertEqual(run.kind, "run")
        self.assertFalse(fill.contains(100, 100))  # el centro es el agujero: no se borda
        self.assertTrue(fill.contains(30, 30))     # entre el borde y el agujero: sí
        b = E.bbox_of(shapes)
        self.assertAlmostEqual(b[1][0] - b[0][0], 200, delta=0.5)

    def test_photo_import_makes_color_shapes(self):
        import cv2
        img = np.full((120, 160, 3), 255, np.uint8)          # fondo blanco
        cv2.rectangle(img, (20, 20), (80, 100), (0, 0, 255), -1)   # rojo (BGR)
        cv2.circle(img, (120, 60), 25, (255, 0, 0), -1)        # azul
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "foto.png")
            cv2.imwrite(path, img)
            shapes = E.photo_to_shapes(path, n_colors=3, width_mm=160)
        self.assertGreaterEqual(len(shapes), 3)
        colors = {s.color for s in shapes}
        self.assertIn("#ff0000", colors)   # rojo
        self.assertIn("#0000ff", colors)   # azul
        b = E.bbox_of(shapes)
        self.assertAlmostEqual(b[1][0] - b[0][0], 160, delta=2)


if __name__ == "__main__":
    unittest.main()
