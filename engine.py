"""Motor del bordado: formas -> puntadas -> archivo .dst (Tajima).

Todas las coordenadas están en milímetros. pyembroidery trabaja en
décimas de milímetro, por eso al escribir se multiplica por 10.
"""
import math

import pyembroidery as pe

HOOP_W_MM = 380.0        # bastidor más grande del usuario (38 cm)
HOOP_H_MM = 260.0        # (26 cm)
STITCH_MM = 3.0          # largo máximo de cada puntada
DEFAULT_SPACING_MM = 0.4 # separación entre líneas de relleno


class Shape:
    """Una forma del bordado.

    kind: "fill" (relleno, llena la forma) o "run" (contorno, una línea).
    fill_angle: dirección de las líneas de relleno, en grados.
    """

    def __init__(self, points, kind="fill", color="#1e3a8a",
                 fill_angle=45.0, spacing=DEFAULT_SPACING_MM):
        self.points = [(float(x), float(y)) for x, y in points]
        self.kind = kind
        self.color = color
        self.fill_angle = float(fill_angle)
        self.spacing = float(spacing)

    def copy(self):
        return Shape(self.points, self.kind, self.color,
                     self.fill_angle, self.spacing)


# ---------- geometría ----------

def centroid(pts):
    n = len(pts)
    return (sum(x for x, _ in pts) / n, sum(y for _, y in pts) / n)


def rotate_scale(pts, angle_deg=0.0, scale=1.0, pivot=None):
    """Gira y agranda una lista de puntos alrededor de un pivote."""
    cx, cy = pivot if pivot is not None else centroid(pts)
    a = math.radians(angle_deg)
    c, s = math.cos(a), math.sin(a)
    out = []
    for x, y in pts:
        dx, dy = (x - cx) * scale, (y - cy) * scale
        out.append((cx + dx * c - dy * s, cy + dx * s + dy * c))
    return out


def translate(pts, dx, dy):
    return [(x + dx, y + dy) for x, y in pts]


def contains(pts, px, py):
    """¿El punto (px, py) está dentro del polígono? (ray casting)"""
    inside = False
    j = len(pts) - 1
    for i in range(len(pts)):
        xi, yi = pts[i]
        xj, yj = pts[j]
        if (yi > py) != (yj > py):
            x_cross = (xj - xi) * (py - yi) / (yj - yi) + xi
            if px < x_cross:
                inside = not inside
        j = i
    return inside


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _subdivide(poly, step):
    """Parte una línea en puntadas de largo máximo `step`."""
    out = [poly[0]]
    for (x1, y1), (x2, y2) in zip(poly, poly[1:]):
        length = math.hypot(x2 - x1, y2 - y1)
        if length < 1e-6:
            continue
        n = max(1, math.ceil(length / step))
        for i in range(1, n + 1):
            t = i / n
            out.append((x1 + (x2 - x1) * t, y1 + (y2 - y1) * t))
    return out


# ---------- puntadas ----------

def _fill_rows(pts, angle_deg, spacing):
    """Segmentos horizontales de relleno, después girados al ángulo pedido.

    Las filas van en "ida y vuelta" (serpentina) para que el hilo
    no tenga que cruzar toda la forma de vuelta.
    """
    pivot = centroid(pts)
    # Giramos la forma al revés para que las líneas queden horizontales.
    flat = rotate_scale(pts, -angle_deg, pivot=pivot)
    ys = [y for _, y in flat]
    n = len(flat)
    rows = []
    y = min(ys) + spacing / 2
    k = 0
    while y < max(ys):
        xs = []
        for i in range(n):
            (x1, y1), (x2, y2) = flat[i], flat[(i + 1) % n]
            if (y1 <= y < y2) or (y2 <= y < y1):
                xs.append(x1 + (y - y1) * (x2 - x1) / (y2 - y1))
        xs.sort()
        segs = [((xs[j], y), (xs[j + 1], y)) for j in range(0, len(xs) - 1, 2)]
        if k % 2:
            segs = [(b, a) for a, b in reversed(segs)]
        rows.extend(segs)
        y += spacing
        k += 1
    # Volvemos cada segmento a la orientación real de la forma.
    return [rotate_scale(list(seg), angle_deg, pivot=pivot) for seg in rows]


def shape_polylines(shape, stitch=STITCH_MM):
    """Lista de líneas (en mm) que la máquina debe recorrer para esta forma."""
    if shape.kind == "run":
        loop = shape.points + [shape.points[0]]
        return [_subdivide(loop, stitch)]
    rows = _fill_rows(shape.points, shape.fill_angle, shape.spacing)
    return [_subdivide(list(seg), stitch) for seg in rows]


# ---------- archivo ----------

def _units(mm):
    return int(round(mm * 10))


def build_pattern(shapes, center=True, stitch=STITCH_MM):
    """Convierte las formas en un patrón de pyembroidery.

    Devuelve (patron, datos). `datos` trae cantidad de puntadas,
    tamaño del diseño y si cabe en el bastidor.
    """
    layers = []
    for s in shapes:
        if len(s.points) < 3:
            continue
        lines = shape_polylines(s, stitch)
        if lines:
            layers.append((s.color, lines))

    if not layers:
        return None, {"stitches": 0, "width": 0.0, "height": 0.0, "fits": True}

    all_pts = [p for _, lines in layers for line in lines for p in line]
    xs = [x for x, _ in all_pts]
    ys = [y for _, y in all_pts]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    width, height = maxx - minx, maxy - miny

    dx = HOOP_W_MM / 2 - (minx + maxx) / 2 if center else 0.0
    dy = HOOP_H_MM / 2 - (miny + maxy) / 2 if center else 0.0

    pat = pe.EmbPattern()
    count = 0
    prev_color = None
    cur = None
    for color, lines in layers:
        if prev_color is not None and color != prev_color:
            pat.add_command(pe.COLOR_CHANGE)   # la máquina pide cambiar de hilo
            cur = None
        prev_color = color
        for line in lines:
            for i, (x, y) in enumerate(line):
                x, y = x + dx, y + dy
                close = cur is not None and _dist(cur, (x, y)) <= stitch * 1.01
                if i == 0 and not close:
                    pat.add_stitch_absolute(pe.JUMP, _units(x), _units(y))
                else:
                    pat.add_stitch_absolute(pe.STITCH, _units(x), _units(y))
                    count += 1
                cur = (x, y)
    pat.add_command(pe.END)

    fits = width <= HOOP_W_MM and height <= HOOP_H_MM
    return pat, {"stitches": count, "width": width, "height": height, "fits": fits}


def write_dst(shapes, path, center=True):
    pat, info = build_pattern(shapes, center=center)
    if pat is None:
        raise ValueError("No hay formas para guardar.")
    pe.write_dst(pat, path)
    return info
