"""Motor del bordado: formas -> puntadas -> archivo .dst (Tajima).

Coordenadas en milímetros. pyembroidery usa décimas de mm (se multiplica por 10).

Una forma puede tener varios anillos (contornos). Se rellenan con regla
par-impar: un anillo dentro de otro actúa como agujero (ej.: la letra "O").

Las puntadas de cada forma se guardan en caché y solo se recalculan
cuando cambia la forma, así que dibujar y mover va fluido.
"""
import math

import numpy as np
import pyembroidery as pe

STITCH_MM = 3.0           # largo máximo de cada puntada
DEFAULT_SPACING_MM = 0.4  # separación entre líneas de relleno
DEFAULT_HOOP = (380.0, 260.0)  # bastidor más grande (mm)
DEFAULT_SATIN_WIDTH_MM = 3.0   # ancho por defecto de una línea de satén
SATIN_DENSITY_MM = 0.4         # distancia entre columnas de zigzag del satén


# ---------- geometría ----------

def rotate_scale(pts, angle_deg=0.0, scale=1.0, pivot=None):
    """Gira y agranda puntos alrededor de un pivote."""
    arr = np.asarray(pts, dtype=float)
    cx, cy = pivot if pivot is not None else arr.mean(axis=0)
    a = math.radians(angle_deg)
    c, s = math.cos(a), math.sin(a)
    dx = (arr[:, 0] - cx) * scale
    dy = (arr[:, 1] - cy) * scale
    return np.column_stack([cx + dx * c - dy * s, cy + dx * s + dy * c])


def _as_rings(rings):
    """Acepta un anillo (lista de puntos) o una lista de anillos."""
    if isinstance(rings, np.ndarray) and rings.ndim == 2:
        return [rings.astype(float)]
    rings = list(rings)
    if rings and np.ndim(rings[0]) == 1:
        return [np.asarray(rings, dtype=float)]
    return [np.asarray(r, dtype=float) for r in rings]


def _subdivide(pts, step):
    """Parte una línea en puntadas de largo máximo `step`."""
    pts = np.asarray(pts, dtype=float)
    out = [pts[:1]]
    for a, b in zip(pts[:-1], pts[1:]):
        length = math.hypot(b[0] - a[0], b[1] - a[1])
        if length < 1e-9:
            continue
        n = max(1, math.ceil(length / step))
        t = np.arange(1, n + 1)[:, None] / n
        out.append(a + (b - a) * t)
    return np.vstack(out)


def _fill_lines(rings, angle, spacing, step):
    """Líneas de relleno (en mm) con la dirección pedida, en serpentina."""
    pivot = rings[0].mean(axis=0)
    # Giramos la forma al revés para que las líneas queden horizontales.
    flat = [rotate_scale(r, -angle, pivot=pivot) for r in rings]
    seg = np.vstack([np.column_stack([r, np.roll(r, -1, axis=0)]) for r in flat])
    x1, y1, x2, y2 = seg.T
    lo = np.minimum(y1, y2)
    hi = np.maximum(y1, y2)

    lines = []
    for k, y in enumerate(np.arange(lo.min() + spacing / 2, hi.max(), spacing)):
        m = (lo <= y) & (y < hi)
        if not m.any():
            continue
        xs = x1[m] + (y - y1[m]) * (x2[m] - x1[m]) / (y2[m] - y1[m])
        xs.sort()
        n = len(xs) // 2 * 2
        left, right = xs[0:n:2], xs[1:n:2]
        if k % 2:  # ida y vuelta: cada fila se recorre al revés
            left, right = right[::-1], left[::-1]
        for a, b in zip(left, right):
            line = _subdivide(np.array([[a, y], [b, y]]), step)
            if len(line) > 1:
                lines.append(rotate_scale(line, angle, pivot=pivot))
    return lines


def _satin_line(center, width, density=SATIN_DENSITY_MM, step=STITCH_MM):
    """Zigzag de satén a lo largo de una línea, de borde a borde."""
    c = np.asarray(center, dtype=float)
    d = np.hypot(*np.diff(c, axis=0).T)
    c = c[np.concatenate([[True], d > 1e-9])]
    if len(c) < 2:
        return np.zeros((0, 2))
    d = np.hypot(*np.diff(c, axis=0).T)
    cum = np.concatenate([[0.0], np.cumsum(d)])
    n = max(1, math.ceil(cum[-1] / density))
    t = np.linspace(0.0, cum[-1], n + 1)
    pts = np.column_stack([np.interp(t, cum, c[:, 0]), np.interp(t, cum, c[:, 1])])
    tan = np.gradient(pts, axis=0)
    norm = np.hypot(tan[:, 0], tan[:, 1])
    norm[norm == 0] = 1.0
    tan = tan / norm[:, None]
    nrm = np.column_stack([-tan[:, 1], tan[:, 0]]) * (width / 2)
    zig = np.empty((2 * len(pts), 2))
    zig[0::2] = pts + nrm       # un lado
    zig[1::2] = pts - nrm       # el otro lado
    return _subdivide(zig, step)


# ---------- forma ----------

class Shape:
    """Una forma del bordado.

    kind: "fill" (relleno, llena la forma), "run" (contorno, una línea),
          "satin" (satén: una línea gruesa de `width` mm) o "raw" (puntadas
          exactas de un .dst abierto: cada anillo es una línea que no se regenera).
    fill_angle: dirección de las líneas de relleno, en grados.
    """

    def __init__(self, rings, kind="fill", color="#1e3a8a",
                 fill_angle=45.0, spacing=DEFAULT_SPACING_MM,
                 width=DEFAULT_SATIN_WIDTH_MM):
        self.rings = _as_rings(rings)
        self.kind = kind
        self.color = color
        self.fill_angle = float(fill_angle)
        self.spacing = float(spacing)
        self.width = float(width)
        self._key = None
        self._lines = None

    def copy(self):
        return Shape([r.copy() for r in self.rings], self.kind, self.color,
                     self.fill_angle, self.spacing, self.width)

    def is_valid(self):
        if self.kind == "satin":
            return len(self.rings) > 0 and len(self.rings[0]) >= 2
        if self.kind == "raw":
            return any(len(r) >= 2 for r in self.rings)
        return any(len(r) >= 3 for r in self.rings)

    def translate(self, dx, dy):
        self.rings = [r + np.array([dx, dy]) for r in self.rings]

    def transform(self, angle=0.0, scale=1.0):
        """Gira y/o agranda la forma alrededor de su centro."""
        pivot = self.rings[0].mean(axis=0)
        self.rings = [rotate_scale(r, angle, scale, pivot) for r in self.rings]
        self.width *= scale

    def contains(self, x, y):
        """¿El punto está dentro de la forma? (regla par-impar; en satén, cerca de la línea)"""
        if self.kind == "raw":
            best = np.inf
            for r in self.rings:
                if len(r) == 1:
                    best = min(best, math.hypot(r[0][0] - x, r[0][1] - y))
                    continue
                a, b = r[:-1], r[1:]
                ab = b - a
                den = np.maximum((ab ** 2).sum(axis=1), 1e-12)
                t = np.clip(((np.array([x, y]) - a) * ab).sum(axis=1) / den, 0.0, 1.0)
                proj = a + ab * t[:, None]
                best = min(best, np.hypot(proj[:, 0] - x, proj[:, 1] - y).min())
            return best <= 1.5
        if self.kind == "satin":
            c = self.rings[0]
            a, b = c[:-1], c[1:]
            ab = b - a
            den = np.maximum((ab ** 2).sum(axis=1), 1e-12)
            t = np.clip(((np.array([x, y]) - a) * ab).sum(axis=1) / den, 0.0, 1.0)
            proj = a + ab * t[:, None]
            dist = np.hypot(proj[:, 0] - x, proj[:, 1] - y).min()
            return dist <= max(self.width / 2, 1.5)
        inside = False
        for r in self.rings:
            n = len(r)
            for i in range(n):
                x1, y1 = r[i]
                x2, y2 = r[(i + 1) % n]
                if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
                    inside = not inside
        return inside

    def polylines(self, stitch=STITCH_MM):
        """Líneas de puntadas (mm). Se guardan en caché."""
        key = (self.kind, self.fill_angle, self.spacing, self.width, stitch,
               tuple(r.tobytes() for r in self.rings))
        if key != self._key:
            self._lines = self._compute(stitch)
            self._key = key
        return self._lines

    def _compute(self, stitch):
        if not self.is_valid():
            return []
        if self.kind == "raw":
            return [r for r in self.rings if len(r) >= 1]   # puntadas tal cual
        if self.kind == "run":
            return [_subdivide(np.vstack([r, r[:1]]), stitch)
                    for r in self.rings if len(r) >= 2]
        if self.kind == "satin":
            line = _satin_line(self.rings[0], self.width, SATIN_DENSITY_MM, stitch)
            return [line] if len(line) > 1 else []
        return _fill_lines(self.rings, self.fill_angle, self.spacing, stitch)


def bbox_of(shapes):
    """(mínimo, máximo) de todas las formas válidas, o None."""
    valid = [s for s in shapes if s.is_valid()]
    if not valid:
        return None
    mins, maxs = [], []
    for s in valid:
        pad = s.width / 2 if s.kind == "satin" else 0.0
        allp = np.vstack(s.rings)
        mins.append(allp.min(axis=0) - pad)
        maxs.append(allp.max(axis=0) + pad)
    return np.min(mins, axis=0), np.max(maxs, axis=0)


def resize_shapes(shapes, new_w, new_h):
    """Escala todo el diseño para que mida new_w x new_h mm (satén incluido), manteniendo su centro.

    El satén agrega su ancho a los bordes, así que se repite el ajuste hasta acertar.
    """
    for _ in range(8):
        b = bbox_of(shapes)
        if b is None:
            return
        mn, mx = b
        w, h = mx[0] - mn[0], mx[1] - mn[1]
        if abs(w - new_w) < 1e-3 and abs(h - new_h) < 1e-3:
            break
        sx = new_w / w if w > 1e-9 else 1.0
        sy = new_h / h if h > 1e-9 else 1.0
        c = (mn + mx) / 2
        for s in shapes:
            s.rings = [(r - c) * np.array([sx, sy]) + c for r in s.rings]
            if s.kind == "satin":
                s.width *= min(sx, sy)


def center_shapes(shapes, cx, cy):
    b = bbox_of(shapes)
    if b is None:
        return
    mn, mx = b
    d = np.array([cx, cy]) - (mn + mx) / 2
    for s in shapes:
        s.translate(d[0], d[1])


# ---------- archivo ----------

def _u(mm):
    return int(round(mm * 10))


def _layers(shapes, stitch):
    layers = []
    for s in shapes:
        if not s.is_valid():
            continue
        lines = s.polylines(stitch)
        if lines:
            layers.append((s.color, lines))
    return layers


def _placement(layers, hoop, center):
    """Desplazamiento para centrar el diseño en el bastidor, y su tamaño."""
    allp = np.vstack([line for _, lines in layers for line in lines])
    mn, mx = allp.min(axis=0), allp.max(axis=0)
    off = (np.array(hoop) / 2 - (mn + mx) / 2) if center else np.zeros(2)
    return off, mx - mn


def _ops(layers, off, stitch):
    """Secuencia de comandos: ('C',) cambio de hilo, ('J'|'S', x, y)."""
    cur = None
    prev = None
    for color, lines in layers:
        if prev is not None and color != prev:
            yield ("C", 0.0, 0.0)
            cur = None
        prev = color
        for line in lines:
            for i, (x, y) in enumerate((line + off).tolist()):
                if i == 0 and (cur is None or math.hypot(x - cur[0], y - cur[1]) > stitch * 1.01):
                    yield ("J", x, y)
                else:
                    yield ("S", x, y)
                cur = (x, y)


def _info(count, size, hoop):
    w, h = float(size[0]), float(size[1])
    return {"stitches": count, "width": w, "height": h,
            "fits": w <= hoop[0] and h <= hoop[1]}


def analyze(shapes, hoop=DEFAULT_HOOP, center=True, stitch=STITCH_MM):
    """Cuenta puntadas y tamaño, sin generar el archivo (cuenta por línea, no por punto)."""
    layers = _layers(shapes, stitch)
    if not layers:
        return _info(0, (0, 0), hoop)
    off, size = _placement(layers, hoop, center)
    count = 0
    cur = None
    for i, (color, lines) in enumerate(layers):
        if i and color != layers[i - 1][0]:
            cur = None                       # cambio de hilo: el siguiente salto cuenta
        for line in lines:
            first = line[0] + off
            if cur is None or math.hypot(first[0] - cur[0], first[1] - cur[1]) > stitch * 1.01:
                count += len(line) - 1       # el primer punto es un salto, no puntada
            else:
                count += len(line)
            cur = line[-1] + off
    return _info(count, size, hoop)


def build_pattern(shapes, hoop=DEFAULT_HOOP, center=True, stitch=STITCH_MM):
    """Convierte las formas en un patrón de pyembroidery. Devuelve (patron, datos)."""
    layers = _layers(shapes, stitch)
    if not layers:
        return None, _info(0, (0, 0), hoop)
    off, size = _placement(layers, hoop, center)
    pat = pe.EmbPattern()
    count = 0
    for kind, x, y in _ops(layers, off, stitch):
        if kind == "C":
            pat.add_command(pe.COLOR_CHANGE)   # la máquina pide cambiar de hilo
        elif kind == "J":
            pat.add_stitch_absolute(pe.JUMP, _u(x), _u(y))
        else:
            pat.add_stitch_absolute(pe.STITCH, _u(x), _u(y))
            count += 1
    pat.add_command(pe.END)
    return pat, _info(count, size, hoop)


def write_dst(shapes, path, hoop=DEFAULT_HOOP, center=True):
    pat, info = build_pattern(shapes, hoop, center)
    if pat is None:
        raise ValueError("No hay formas para guardar.")
    pe.write_dst(pat, path)
    return info


# ---------- importar ----------

def photo_to_shapes(path, n_colors=4, width_mm=150.0, min_area_mm2=2.0):
    """Foto -> formas de relleno, una por color. Es una aproximación: revísala."""
    import cv2

    data = np.fromfile(path, dtype=np.uint8)   # funciona con rutas con tildes
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("No pude abrir la imagen.")
    h, w = img.shape[:2]
    if max(h, w) > 500:
        f = 500 / max(h, w)
        img = cv2.resize(img, (round(w * f), round(h * f)), interpolation=cv2.INTER_AREA)
    img = cv2.medianBlur(img, 5)

    pix = img.reshape(-1, 3).astype(np.float32)
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
    _, labels, centers = cv2.kmeans(pix, n_colors, None, crit, 3, cv2.KMEANS_PP_CENTERS)
    labels = labels.reshape(img.shape[:2])
    counts = np.bincount(labels.ravel(), minlength=n_colors)
    mm_px = width_mm / img.shape[1]

    shapes = []
    for k in np.argsort(-counts):          # las áreas grandes primero
        if counts[k] == 0:
            continue
        mask = np.zeros((img.shape[0] + 2, img.shape[1] + 2), np.uint8)
        mask[1:-1, 1:-1] = np.where(labels == k, 255, 0)
        contours, _ = cv2.findContours(mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
        rings = []
        for c in contours:
            c = cv2.approxPolyDP(c, 1.0, True).reshape(-1, 2).astype(float) - 1
            if len(c) < 3:
                continue
            area = abs(cv2.contourArea(c.astype(np.float32))) * mm_px ** 2
            if area < min_area_mm2:
                continue
            rings.append(c * mm_px)
        if rings:
            b, g, r = centers[k]
            color = "#%02x%02x%02x" % (int(r), int(g), int(b))
            shapes.append(Shape(rings, "fill", color))
    return shapes


def svg_to_shapes(path, width_mm=150.0):
    """Vector SVG -> formas.

    - Figuras rellenas: relleno (las letras con agujeros quedan bien).
    - Líneas abiertas con borde: satén, con el grosor del trazo.
    - Contornos cerrados con solo borde: contorno.
    """
    import svgelements as se

    svg = se.SVG.parse(path)
    items = []   # (tipo, color, anillos, grosor del trazo o None)
    for el in svg.elements():
        if not isinstance(el, se.Shape):
            continue
        p = se.Path(el)
        fill = getattr(el.fill, "hex", None)
        stroke = getattr(el.stroke, "hex", None)
        sw = el.stroke_width if el.stroke_width else 1.0
        rings = []
        for sub in p.as_subpaths():
            sp = se.Path(sub)
            n = max(12, min(400, 8 * len(sp)))
            pts = np.asarray(sp.npoint(np.linspace(0, 1, n)), dtype=float)
            if len(pts) >= 2:
                rings.append(pts)
        if not rings:
            continue
        if fill:
            items.append(("fill", fill, [r for r in rings if len(r) >= 3], None))
        elif stroke:
            for r in rings:
                closed = np.hypot(*(r[0] - r[-1])) < 1e-6
                if closed:
                    items.append(("run", stroke, [r], None))
                else:
                    items.append(("satin", stroke, [r], float(sw)))
        else:
            items.append(("fill", "#111827", [r for r in rings if len(r) >= 3], None))

    items = [it for it in items if it[2]]
    if not items:
        return []
    allp = np.vstack([r for _, _, rings, _ in items for r in rings])
    mn, mx = allp.min(axis=0), allp.max(axis=0)
    span = max(mx[0] - mn[0], 1e-9)
    scale = width_mm / span
    shapes = []
    for kind, color, rings, sw in items:
        scaled = [(r - mn) * scale for r in rings]
        if kind == "satin":
            shapes.append(Shape(scaled, "satin", color, width=max(0.5, sw * scale)))
        else:
            shapes.append(Shape(scaled, kind, color))
    return shapes


def dst_to_shapes(path, palette=None):
    """Archivo .dst -> formas "raw", una por trazo de puntadas (sin cambios).

    El .dst no guarda colores: se asignan en orden, uno por cada cambio de hilo.
    """
    pat = pe.read(path)
    palette = palette or ["#1e3a8a", "#b91c1c", "#15803d", "#eab308",
                          "#111827", "#ea580c", "#7e22ce", "#78350f"]
    shapes, cur, k = [], [], 0

    def flush():
        if len(cur) >= 2:
            line = np.array(cur, dtype=float) / 10.0      # décimas de mm -> mm
            shapes.append(Shape([line], "raw", palette[k % len(palette)]))

    for st in pat.stitches:
        x, y, cmd = st[0], st[1], st[2]
        if cmd == pe.END:
            break
        if cmd == pe.COLOR_CHANGE:
            flush()
            cur = []
            k += 1
        elif cmd == pe.JUMP:
            flush()
            cur = [(x, y)]
        else:
            cur.append((x, y))
    flush()
    return shapes
