import math
import os
import tempfile
import unittest

import pyembroidery as pe

import engine as E


def square(x, y, side):
    return [(x, y), (x + side, y), (x + side, y + side), (x, y + side)]


class FillTests(unittest.TestCase):
    def test_fill_points_stay_inside_shape(self):
        s = E.Shape(square(100, 100, 20), kind="fill", fill_angle=30)
        lines = E.shape_polylines(s)
        self.assertGreater(len(lines), 10)
        for line in lines:
            for x, y in line:
                self.assertTrue(-0.01 <= x - 100 <= 20.01, (x, y))
                self.assertTrue(-0.01 <= y - 100 <= 20.01, (x, y))

    def test_no_stitch_longer_than_limit(self):
        s = E.Shape(square(0, 0, 60), kind="fill", fill_angle=10)
        for line in E.shape_polylines(s):
            for a, b in zip(line, line[1:]):
                self.assertLessEqual(E._dist(a, b), E.STITCH_MM + 1e-6)

    def test_angle_changes_stitch_direction(self):
        rect = [(0, 0), (60, 0), (60, 10), (0, 10)]
        horiz = E.shape_polylines(E.Shape(rect, fill_angle=0))[0]
        vert = E.shape_polylines(E.Shape(rect, fill_angle=90))[0]
        # Horizontal: las líneas van en X; vertical: en Y.
        dx_h = max(x for x, _ in horiz) - min(x for x, _ in horiz)
        dy_v = max(y for _, y in vert) - min(y for _, y in vert)
        self.assertGreater(dx_h, 40)
        self.assertGreater(dy_v, 8)


class RunTests(unittest.TestCase):
    def test_outline_closes_on_start_point(self):
        s = E.Shape(square(0, 0, 30), kind="run")
        line = E.shape_polylines(s)[0]
        self.assertAlmostEqual(line[0][0], line[-1][0], places=6)
        self.assertAlmostEqual(line[0][1], line[-1][1], places=6)
        perimeter = sum(E._dist(a, b) for a, b in zip(line, line[1:]))
        self.assertAlmostEqual(perimeter, 120, places=3)


class FileTests(unittest.TestCase):
    def test_write_and_read_back(self):
        shapes = [
            E.Shape(square(0, 0, 20), color="#1e3a8a"),
            E.Shape(square(30, 0, 10), kind="run", color="#b91c1c"),
        ]
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "t.dst")
            info = E.write_dst(shapes, path)
            self.assertTrue(os.path.getsize(path) > 512)
            pat = pe.read(path)
            self.assertGreater(len(pat.stitches), 50)
            self.assertGreater(info["stitches"], 50)
            self.assertTrue(info["fits"])

    def test_design_is_centered_and_sized_right(self):
        shapes = [E.Shape(square(5, 5, 50))]   # 50 x 50 mm
        pat, info = E.build_pattern(shapes)
        # Descartamos el comando END, que queda guardado en (0, 0).
        real = [s for s in pat.stitches if s[2] != pe.END]
        xs = [s[0] for s in real]
        ys = [s[1] for s in real]
        # pyembroidery guarda en décimas de mm
        w_mm = (max(xs) - min(xs)) / 10
        h_mm = (max(ys) - min(ys)) / 10
        self.assertAlmostEqual(w_mm, 50, delta=0.6)
        self.assertAlmostEqual(h_mm, 50, delta=0.6)
        cx = (max(xs) + min(xs)) / 20
        cy = (max(ys) + min(ys)) / 20
        self.assertAlmostEqual(cx, E.HOOP_W_MM / 2, delta=0.6)
        self.assertAlmostEqual(cy, E.HOOP_H_MM / 2, delta=0.6)

    def test_color_change_is_written(self):
        shapes = [E.Shape(square(0, 0, 20), color="#1e3a8a"),
                  E.Shape(square(30, 0, 20), color="#b91c1c")]
        pat, _ = E.build_pattern(shapes)
        flags = [s[2] for s in pat.stitches]
        self.assertTrue(any(f & pe.COLOR_CHANGE for f in flags))

    def test_too_big_is_flagged(self):
        shapes = [E.Shape(square(0, 0, 400))]
        _, info = E.build_pattern(shapes)
        self.assertFalse(info["fits"])


if __name__ == "__main__":
    unittest.main()
