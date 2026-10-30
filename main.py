"""Diseñador de bordados simple (inspirado en Wings XP).

Flujo:
  1. Pon el tamaño del bastidor que vas a usar.
  2. Dibuja una forma (clic en cada punto, doble clic para cerrarla),
     o importa una foto o un vector SVG.
  3. Elige relleno o contorno, el color y la dirección de las puntadas.
  4. Guarda el .dst y pásalo a la bordadora por USB.
"""
import math
import sys

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QFont, QImage, QKeySequence, QPainter,
                           QPainterPath, QPen, QPolygonF, QShortcut)
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFrame, QGridLayout,
    QHBoxLayout, QInputDialog, QLabel, QMainWindow, QMessageBox, QPushButton,
    QScrollArea, QSlider, QVBoxLayout, QWidget,
)

import engine as E

COLORS = {
    "Azul": "#1e3a8a", "Rojo": "#b91c1c", "Verde": "#15803d",
    "Amarillo": "#eab308", "Negro": "#111827", "Naranja": "#ea580c",
    "Morado": "#7e22ce", "Café": "#78350f",
}

RULER = 34   # ancho de las reglas laterales (px)
TOP = 26     # alto de la regla de arriba (px)
PAD = 12     # espacio entre reglas y bastidor (px)
ZOOM_MIN, ZOOM_MAX = 0.5, 12.0

STYLE = """
QWidget#panel { background: #ffffff; }
QPushButton {
    background: #f1f5f9; border: 1px solid #cbd5e1; border-radius: 8px;
    padding: 7px; font-size: 13px; color: #0f172a;
}
QPushButton:hover   { background: #e2e8f0; }
QPushButton:checked { background: #2563eb; color: white; border-color: #2563eb; }
QPushButton:disabled { color: #94a3b8; background: #f8fafc; }
QPushButton#save {
    background: #16a34a; color: white; border: none; font-weight: 600; padding: 12px;
}
QPushButton#save:hover { background: #15803d; }
QLabel#status { background: #f8fafc; border-radius: 8px; padding: 8px; color: #334155; }
QLabel#title  { font-weight: 600; font-size: 13px; color: #0f172a; margin-top: 10px; }
QLabel#hint   { color: #64748b; font-size: 11px; }
"""


def _steps(s):
    """Separación de las marcas de la regla, según el zoom."""
    major = next((m for m in (10, 20, 50, 100, 200, 500) if m * s >= 40), 500)
    return major // 5, major   # (marca chica, marca grande en mm)


def _ticks(lo, hi, step, top):
    """Marcas de la regla (en mm) entre lo y hi, dentro de 0..top."""
    lo, hi = max(0.0, lo), min(float(top), hi)
    if hi < lo:
        return []
    return [k * step for k in range(math.ceil(lo / step), math.floor(hi / step) + 1)]


def _dist(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


class Canvas(QWidget):
    """El bastidor donde se dibuja. Todo se trabaja en milímetros."""

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.mode = "draw_fill"   # "draw_fill", "draw_satin" o "select"
        self.in_progress = []     # puntos de la forma que se está dibujando
        self.sel = set()          # índices de las formas seleccionadas
        self.selected = -1        # la última tocada: la que muestra el panel
        self.zoom = 1.0           # 1.0 = todo el bastidor visible
        self.pan = [0.0, 0.0]     # desplazamiento de la vista (px)
        self._drag = None         # (tipo, inicio, valor original, historial)
        self._dragged = set()     # formas que se están arrastrando
        self._moved = False
        self._marq_base = set()   # selección previa al recuadro (con Shift)
        self._marq_now = (0.0, 0.0)
        self.edit_idx = -1        # forma que se edita punto a punto
        self.vsel = set()         # puntos seleccionados al editar: (anillo, punto)
        self.reopen = None        # última forma cerrada: (puntos, índice), para reabrirla con Ctrl+Z
        self.setMinimumSize(760, 540)
        self.setFocusPolicy(Qt.StrongFocus)

    # --- selección ---

    def select_only(self, i):
        self.sel = {i} if i >= 0 else set()
        self.selected = i

    def clear_sel(self):
        self.select_only(-1)

    def toggle(self, i):
        if i in self.sel:
            self.sel.discard(i)
            self.selected = max(self.sel) if self.sel else -1
        else:
            self.sel.add(i)
            self.selected = i

    def _select_in_rect(self, a, b):
        """Selecciona las formas que tocan el recuadro entre a y b (en mm)."""
        rx0, rx1 = sorted((a[0], b[0]))
        ry0, ry1 = sorted((a[1], b[1]))
        hits = set()
        for i, sh in enumerate(self.win.shapes):
            bb = E.bbox_of([sh]) if sh.is_valid() else None
            if bb is None:
                continue
            mn, mx = bb
            if mx[0] >= rx0 and mn[0] <= rx1 and mx[1] >= ry0 and mn[1] <= ry1:
                hits.add(i)
        self.sel = self._marq_base | hits
        self.selected = max(self.sel) if self.sel else -1

    # --- edición de puntos ---

    def _edit_shape(self):
        i = self.edit_idx
        if 0 <= i < len(self.win.shapes):
            return self.win.shapes[i]
        return None

    def _hit_vertex(self, x, y):
        """Punto más cercano al clic (dentro de 7 px), como (anillo, punto)."""
        sh = self._edit_shape()
        if sh is None:
            return None
        tol = 7.0 / self.view()[0]
        best, best_d = None, tol
        for ri, ring in enumerate(sh.rings):
            d = np.hypot(ring[:, 0] - x, ring[:, 1] - y)
            vi = int(np.argmin(d))
            if d[vi] <= best_d:
                best, best_d = (ri, vi), d[vi]
        return best

    def _select_vertices_in_rect(self, a, b):
        sh = self._edit_shape()
        if sh is None:
            return
        rx0, rx1 = sorted((a[0], b[0]))
        ry0, ry1 = sorted((a[1], b[1]))
        hits = set()
        for ri, ring in enumerate(sh.rings):
            m = ((ring[:, 0] >= rx0) & (ring[:, 0] <= rx1)
                 & (ring[:, 1] >= ry0) & (ring[:, 1] <= ry1))
            hits |= {(ri, int(i)) for i in np.nonzero(m)[0]}
        self.vsel = self._marq_base | hits

    def _edit_press(self, e, x, y):
        sh = self._edit_shape()
        if sh is None:
            return
        shift = bool(e.modifiers() & Qt.ShiftModifier)
        hit = self._hit_vertex(x, y)
        if hit is not None:
            if shift:
                self.vsel ^= {hit}          # Shift + clic: suma o quita el punto
                self.update()
                return
            if hit not in self.vsel:
                self.vsel = {hit}
            origs = {v: np.array(sh.rings[v[0]][v[1]], dtype=float) for v in self.vsel}
            self._drag = ("verts", (x, y), origs, self.win.snapshot())
        else:
            # Espacio vacío: recuadro para elegir una parte de puntos.
            self._marq_base = set(self.vsel) if shift else set()
            if not shift:
                self.vsel = set()
            self._drag = ("vmarquee", (x, y), (x, y), None)
            self._marq_now = (x, y)
        self._moved = False
        self.update()

    # --- vista: mm <-> píxeles ---

    def _layout(self, zoom, pan):
        W, H = self.width(), self.height()
        hw, hh = self.win.hoop
        avail_w = W - 2 * (RULER + PAD)
        avail_h = H - (TOP + PAD) - PAD
        s = max(0.01, min(avail_w / hw, avail_h / hh)) * zoom
        ox = (W - hw * s) / 2 + pan[0]
        oy = TOP + PAD + (avail_h - hh * s) / 2 + pan[1]
        return s, ox, oy

    def view(self):
        return self._layout(self.zoom, self.pan)

    def to_mm(self, pos):
        s, ox, oy = self.view()
        return ((pos.x() - ox) / s, (pos.y() - oy) / s)

    def zoom_at(self, pos, factor):
        """Acerca o aleja manteniendo fijo el punto bajo el cursor."""
        mm = self.to_mm(pos)
        self.zoom = min(ZOOM_MAX, max(ZOOM_MIN, self.zoom * factor))
        s, ox, oy = self._layout(self.zoom, (0.0, 0.0))
        self.pan = [pos.x() - ox - mm[0] * s, pos.y() - oy - mm[1] * s]
        self.update()

    def zoom_center(self, factor):
        self.zoom_at(QPointF(self.width() / 2, self.height() / 2), factor)

    def reset_view(self):
        self.zoom = 1.0
        self.pan = [0.0, 0.0]
        self.update()

    @staticmethod
    def _poly(arr, v):
        s, ox, oy = v
        pts = (np.asarray(arr, dtype=float) * s + [ox, oy]).tolist()
        return QPolygonF([QPointF(x, y) for x, y in pts])

    def _stitch_polys(self, sh, v):
        """Trazos de puntadas ya pasados a píxeles. Se reutilizan mientras no cambie la forma ni la vista."""
        if not hasattr(self, "_pcache"):
            self._pcache = {}
        lines = sh.polylines()
        hit = self._pcache.get(id(sh))
        if hit and hit[0] is lines and hit[1] == v:
            return hit[2]
        polys = [self._poly(line, v) for line in lines if len(line) > 1]
        self._pcache[id(sh)] = (lines, v, polys)
        return polys

    # --- dibujo ---

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        v = self.view()
        s, ox, oy = v
        hw, hh = self.win.hoop
        p.fillRect(self.rect(), QColor("#f1f5f9"))

        hoop = QRectF(ox, oy, hw * s, hh * s)
        p.fillRect(hoop, QColor("white"))

        bg = self.win.bg
        if bg:
            img = bg["img"]
            hgt = bg["w"] * img.height() / img.width()
            p.setOpacity(bg["opacity"])
            p.drawImage(QRectF(ox + bg["x"] * s, oy + bg["y"] * s, bg["w"] * s, hgt * s), img)
            p.setOpacity(1.0)

        p.setPen(QPen(QColor("#94a3b8"), 1.5, Qt.DashLine))
        p.setBrush(Qt.NoBrush)
        p.drawRect(hoop)

        for i, sh in enumerate(self.win.shapes):
            if not sh.is_valid():
                continue
            col = QColor(sh.color)
            path = QPainterPath()
            path.setFillRule(Qt.OddEvenFill)   # agujeros como en las letras
            for r in sh.rings:
                if len(r) >= 3:
                    path.addPolygon(self._poly(r, v))
                    path.closeSubpath()
            if sh.kind == "satin":
                # La banda muestra el ancho real del satén (en píxeles).
                band = QColor(col.red(), col.green(), col.blue(), 55)
                p.setBrush(Qt.NoBrush)
                p.setPen(QPen(band, max(2.0, sh.width * s), Qt.SolidLine,
                              Qt.RoundCap, Qt.RoundJoin))
                p.drawPolyline(self._poly(sh.rings[0], v))
                p.setPen(QPen(col, 1))
                p.drawPolyline(self._poly(sh.rings[0], v))
            else:
                p.setBrush(QColor(col.red(), col.green(), col.blue(), 45)
                           if sh.kind == "fill" else Qt.NoBrush)
                p.setPen(QPen(col, 1.5))
                p.drawPath(path)

            # Vista previa de las puntadas (no se dibuja mientras la mueves).
            if i not in self._dragged:
                p.setBrush(Qt.NoBrush)
                p.setPen(QPen(QColor(col.red(), col.green(), col.blue(), 170), 1))
                for poly in self._stitch_polys(sh, v):
                    p.drawPolyline(poly)

            if i in self.sel:
                p.setBrush(Qt.NoBrush)
                p.setPen(QPen(QColor("#2563eb"), 2, Qt.DashLine))
                p.drawPath(path)

        # Medidas del diseño completo.
        b = E.bbox_of(self.win.shapes)
        if b is not None:
            mn, mx = b
            rect = QRectF(QPointF(ox + mn[0] * s, oy + mn[1] * s),
                          QPointF(ox + mx[0] * s, oy + mx[1] * s))
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor("#475569"), 1, Qt.DashDotLine))
            p.drawRect(rect)
            p.setPen(QColor("#334155"))
            p.drawText(QPointF(rect.left(), rect.top() - 6),
                       f"Diseño: {mx[0] - mn[0]:.0f} × {mx[1] - mn[1]:.0f} mm")

        # Recuadro de selección que se está dibujando.
        if self._drag and self._drag[0] in ("marquee", "vmarquee"):
            x0, y0 = self._drag[1]
            x1, y1 = self._marq_now
            r = QRectF(QPointF(ox + x0 * s, oy + y0 * s),
                       QPointF(ox + x1 * s, oy + y1 * s)).normalized()
            p.setPen(QPen(QColor("#2563eb"), 1, Qt.DashLine))
            p.setBrush(QColor(37, 99, 235, 30))
            p.drawRect(r)

        sh_edit = self._edit_shape() if self.mode == "edit" else None
        if sh_edit is not None:
            p.setPen(QPen(QColor("#2563eb"), 1))
            for ri, ring in enumerate(sh_edit.rings):
                for vi, (x, y) in enumerate(ring):
                    on = (ri, vi) in self.vsel
                    p.setBrush(QColor("#2563eb") if on else QColor("white"))
                    p.drawRect(QRectF(ox + x * s - 3.5, oy + y * s - 3.5, 7, 7))

        if self.in_progress:
            pts = np.asarray(self.in_progress, dtype=float)
            p.setPen(QPen(QColor("#2563eb"), 2))
            p.setBrush(Qt.NoBrush)
            p.drawPolyline(self._poly(pts, v))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#2563eb"))
            for x, y in self.in_progress:
                p.drawEllipse(QPointF(ox + x * s, oy + y * s), 4, 4)

        self._rulers(p, v)
        p.end()

    def _rulers(self, p, v):
        """Reglas pegadas a los bordes de la vista: muestran los mm que se ven."""
        s, ox, oy = v
        W, H = self.width(), self.height()
        hw, hh = self.win.hoop
        minor, major = _steps(s)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#f8fafc"))
        p.drawRect(QRectF(0, 0, W, TOP))
        p.drawRect(QRectF(0, 0, RULER, H))
        p.drawRect(QRectF(W - RULER, 0, RULER, H))

        font = QFont()
        font.setPixelSize(10)
        p.setFont(font)
        p.setPen(QPen(QColor("#475569"), 1))
        p.drawText(QRectF(0, 0, RULER, TOP), Qt.AlignCenter, "mm")

        # Regla de arriba: a lo largo del ancho del bastidor.
        for mm in _ticks((RULER - ox) / s, (W - RULER - ox) / s, minor, hw):
            x = ox + mm * s
            big = mm % major == 0
            p.drawLine(QPointF(x, TOP - 4), QPointF(x, TOP - (12 if big else 7)))
            if big:
                p.drawText(QPointF(x + 3, TOP - 8), str(mm))

        # Reglas de los lados: a lo largo del alto del bastidor.
        for mm in _ticks((TOP - oy) / s, (H - oy) / s, minor, hh):
            y = oy + mm * s
            big = mm % major == 0
            p.drawLine(QPointF(RULER - 4, y), QPointF(RULER - (12 if big else 7), y))
            p.drawLine(QPointF(W - RULER + 4, y), QPointF(W - RULER + (12 if big else 7), y))
            if big:
                p.drawText(QRectF(0, y + 1, RULER - 14, 12),
                           Qt.AlignRight | Qt.AlignVCenter, str(mm))
                p.drawText(QRectF(W - RULER + 14, y + 1, RULER - 14, 12),
                           Qt.AlignLeft | Qt.AlignVCenter, str(mm))

    # --- ratón y teclado ---

    def _in_bg(self, x, y):
        bg = self.win.bg
        hgt = bg["w"] * bg["img"].height() / bg["img"].width()
        return bg["x"] <= x <= bg["x"] + bg["w"] and bg["y"] <= y <= bg["y"] + hgt

    def wheelEvent(self, e):
        dy = e.angleDelta().y()
        if dy:
            self.zoom_at(e.position(), 1.2 if dy > 0 else 1 / 1.2)

    def mousePressEvent(self, e):
        ctrl = bool(e.modifiers() & Qt.ControlModifier)
        if e.button() == Qt.MiddleButton or (e.button() == Qt.LeftButton and ctrl):
            # Botón del medio, o Ctrl + arrastrar: mover la vista (sin tocar las formas)
            self._drag = ("pan", e.position(), list(self.pan), None)
            return
        if e.button() != Qt.LeftButton:
            return
        x, y = self.to_mm(e.position())
        if self.mode.startswith("draw"):
            if (self.mode == "draw_fill" and len(self.in_progress) >= 3
                    and _dist(self.in_progress[0], (x, y)) < 2.5):
                self.finish_shape()
                return
            if not self.in_progress or _dist(self.in_progress[-1], (x, y)) > 0.5:
                self.in_progress.append((x, y))
            self.update()
            return

        if self.mode == "edit":
            self._edit_press(e, x, y)
            return

        # modo mover / elegir
        shift = bool(e.modifiers() & Qt.ShiftModifier)
        hit = -1
        for i in reversed(range(len(self.win.shapes))):
            sh = self.win.shapes[i]
            if sh.is_valid() and sh.contains(x, y):
                hit = i
                break

        if hit >= 0 and shift:
            # Shift + clic: suma o quita esa forma de la selección.
            self.toggle(hit)
            self.win.sync_panel()
            return
        if hit >= 0:
            if hit not in self.sel:
                self.select_only(hit)
            else:
                self.selected = hit           # el grupo sigue seleccionado
            ids = sorted(self.sel)
            origs = {i: [r.copy() for r in self.win.shapes[i].rings] for i in ids}
            self._drag = ("shape", (x, y), origs, self.win.snapshot())
            self._dragged = set(ids)
        elif self.win.bg and self._in_bg(x, y) and not shift:
            self.clear_sel()
            bg = self.win.bg
            self._drag = ("bg", (x, y), (bg["x"], bg["y"]), None)
        else:
            # Espacio vacío: arrastra un recuadro para elegir varias formas.
            self._marq_base = set(self.sel) if shift else set()
            if not shift:
                self.clear_sel()
            self._drag = ("marquee", (x, y), (x, y), None)
            self._marq_now = (x, y)
        self._moved = False
        self.win.sync_panel()
        self.update()

    def mouseMoveEvent(self, e):
        if not self._drag:
            return
        kind, start, orig, _ = self._drag
        if kind == "pan":
            dx = e.position().x() - start.x()
            dy = e.position().y() - start.y()
            self.pan = [orig[0] + dx, orig[1] + dy]
            self.update()
            return
        x, y = self.to_mm(e.position())
        dx, dy = x - start[0], y - start[1]
        if dx or dy:
            self._moved = True
        if kind == "verts":
            sh = self._edit_shape()
            if sh is not None:
                rings = [r.copy() for r in sh.rings]
                for (ri, vi), p0 in orig.items():
                    rings[ri][vi] = p0 + (dx, dy)
                sh.rings = rings
        elif kind == "shape":
            for i, rings in orig.items():
                self.win.shapes[i].rings = [r + np.array([dx, dy]) for r in rings]
        elif kind == "marquee":
            self._marq_now = (x, y)
            self._select_in_rect(start, (x, y))
        elif kind == "vmarquee":
            self._marq_now = (x, y)
            self._select_vertices_in_rect(start, (x, y))
        else:
            bg = self.win.bg
            bg["x"], bg["y"] = orig[0] + dx, orig[1] + dy
        self.update()

    def mouseReleaseEvent(self, _e):
        if not self._drag:
            return
        kind, _, _, before = self._drag
        if kind != "pan" and self._moved and before is not None:
            self.win.push_history(before)
        self._drag = None
        self._dragged = set()
        if kind in ("marquee", "vmarquee"):
            self.win.sync_panel()
        else:
            self.win.refresh()

    def mouseDoubleClickEvent(self, e):
        if self.mode.startswith("draw") and len(self.in_progress) >= self._min_points():
            self.finish_shape()

    def _min_points(self):
        return 2 if self.mode == "draw_satin" else 3

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.finish_shape()
        elif e.key() == Qt.Key_Escape:
            if self.in_progress:
                self.in_progress = []
                self.update()
            elif self.mode == "edit":
                self.win.set_mode("select")
            else:
                self.clear_sel()
                self.win.sync_panel()
        else:
            super().keyPressEvent(e)

    def finish_shape(self):
        if len(self.in_progress) < self._min_points():
            return
        pts = np.array(self.in_progress, dtype=float)
        if self.mode == "draw_satin":
            shape = E.Shape(pts, "satin", width=self.win.satin_width)
        else:
            shape = E.Shape(pts, "fill")
        self.win.add_shape(shape)
        self.reopen = ([tuple(p) for p in pts], len(self.win.shapes) - 1)
        self.in_progress = []
        self.select_only(len(self.win.shapes) - 1)
        self.win.sync_panel()
        self.update()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Bordado simple")
        self.shapes = []
        self.history = []
        self.hoop = list(E.DEFAULT_HOOP)   # (ancho, alto) en mm
        self.satin_width = E.DEFAULT_SATIN_WIDTH_MM
        self.bg = None                     # foto de fondo para calcar
        self.current_color = COLORS["Azul"]
        self._updating = False

        self.canvas = Canvas(self)
        panel = self._build_panel()
        scroll = QScrollArea()
        scroll.setWidget(panel)
        scroll.setWidgetResizable(True)
        scroll.setFixedWidth(300)
        scroll.setFrameShape(QFrame.NoFrame)

        root = QWidget()
        lay = QHBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(scroll)
        lay.addWidget(self.canvas, 1)
        self.setCentralWidget(root)
        self.setStyleSheet(STYLE)

        QShortcut(QKeySequence("Ctrl+Z"), self, activated=self.undo)
        QShortcut(QKeySequence("Ctrl+S"), self, activated=self.save)
        QShortcut(QKeySequence("Ctrl+A"), self, activated=self.select_all)
        QShortcut(QKeySequence(Qt.Key_Delete), self, activated=self.delete_selected)
        QShortcut(QKeySequence(QKeySequence.StandardKey.ZoomIn), self,
                  activated=lambda: self.canvas.zoom_center(1.25))
        QShortcut(QKeySequence("Ctrl+="), self,
                  activated=lambda: self.canvas.zoom_center(1.25))
        QShortcut(QKeySequence(QKeySequence.StandardKey.ZoomOut), self,
                  activated=lambda: self.canvas.zoom_center(0.8))
        QShortcut(QKeySequence("Ctrl+0"), self, activated=lambda: self.canvas.reset_view())

        self.resize(1280, 800)
        self.sync_panel()

    # --- panel izquierdo ---

    def _title(self, text):
        lab = QLabel(text)
        lab.setObjectName("title")
        return lab

    def _hint(self, text):
        lab = QLabel(text)
        lab.setObjectName("hint")
        lab.setWordWrap(True)
        return lab

    def _build_panel(self):
        panel = QWidget()
        panel.setObjectName("panel")
        v = QVBoxLayout(panel)
        v.setContentsMargins(14, 8, 14, 14)
        v.setSpacing(6)

        # Tamaño del diseño: lo que vas a bordar
        v.addWidget(self._title("Tamaño del diseño (mm)"))
        dgrid = QGridLayout()
        self.design_w = QDoubleSpinBox()
        self.design_h = QDoubleSpinBox()
        for box in (self.design_w, self.design_h):
            box.setRange(1, 600)
            box.setSingleStep(5)
            box.setDecimals(0)
            box.setSuffix(" mm")
            box.setValue(100)
        self.design_w.valueChanged.connect(lambda _v: self.on_design("w"))
        self.design_h.valueChanged.connect(lambda _v: self.on_design("h"))
        dgrid.addWidget(QLabel("Ancho"), 0, 0)
        dgrid.addWidget(self.design_w, 0, 1)
        dgrid.addWidget(QLabel("Alto"), 1, 0)
        dgrid.addWidget(self.design_h, 1, 1)
        v.addLayout(dgrid)
        self.keep_ratio = QCheckBox("Mantener proporción")
        self.keep_ratio.setChecked(True)
        v.addWidget(self.keep_ratio)
        v.addWidget(self._hint("Pon el tamaño que quieres bordar y el diseño se ajusta. "
                               "El bastidor de abajo es el máximo: el diseño tiene que caber."))

        # Bastidor: el máximo que tienes
        v.addWidget(self._title("Bastidor (mm)"))
        grid = QGridLayout()
        self.hoop_w = QDoubleSpinBox()
        self.hoop_h = QDoubleSpinBox()
        for box, val in ((self.hoop_w, self.hoop[0]), (self.hoop_h, self.hoop[1])):
            box.setRange(20, 600)
            box.setSingleStep(5)
            box.setDecimals(0)
            box.setSuffix(" mm")
            box.setValue(val)
            box.valueChanged.connect(self.on_hoop)
        grid.addWidget(QLabel("Ancho"), 0, 0)
        grid.addWidget(self.hoop_w, 0, 1)
        grid.addWidget(QLabel("Alto"), 1, 0)
        grid.addWidget(self.hoop_h, 1, 1)
        v.addLayout(grid)
        v.addWidget(self._hint("Pon el tamaño del bastidor que vas a usar. "
                               "El máximo es 380 × 260 mm."))

        # Zoom: para ver de cerca los detalles
        v.addWidget(self._title("Zoom"))
        zrow = QHBoxLayout()
        for text, fn in (("－ Alejar", lambda: self.canvas.zoom_center(0.8)),
                         ("＋ Acercar", lambda: self.canvas.zoom_center(1.25)),
                         ("Ver todo", lambda: self.canvas.reset_view())):
            b = QPushButton(text)
            b.clicked.connect(fn)
            zrow.addWidget(b)
        v.addLayout(zrow)
        v.addWidget(self._hint("Rueda del ratón o Ctrl + / Ctrl −. "
                               "Para mover la vista, mantén Ctrl y arrastra "
                               "(o usa el botón del medio)."))

        # 1. Dibujar o mover
        v.addWidget(self._title("1. Dibuja o mueve"))
        self.btn_draw = QPushButton("✏  Dibujar forma")
        self.btn_draw.setCheckable(True)
        self.btn_draw.setChecked(True)
        self.btn_draw.clicked.connect(lambda: self.set_mode("draw_fill"))
        self.btn_satin = QPushButton("〰  Dibujar línea de satén")
        self.btn_satin.setCheckable(True)
        self.btn_satin.clicked.connect(lambda: self.set_mode("draw_satin"))
        self.btn_select = QPushButton("✋  Mover / elegir")
        self.btn_select.setCheckable(True)
        self.btn_select.clicked.connect(lambda: self.set_mode("select"))
        self.btn_edit = QPushButton("✎  Editar puntos")
        self.btn_edit.setCheckable(True)
        self.btn_edit.clicked.connect(lambda: self.set_mode("edit"))
        v.addWidget(self.btn_draw)
        v.addWidget(self.btn_satin)
        v.addWidget(self.btn_select)
        v.addWidget(self.btn_edit)
        v.addWidget(self._hint("Forma: clic en cada punto; doble clic o Enter para cerrarla. "
                               "Ctrl+Z quita el último punto, o reabre la forma si la cerraste mal. "
                               "Satén: clic en la línea; doble clic o Enter para terminar. "
                               "Para elegir varias: Shift + clic, o arrastra un recuadro "
                               "en el espacio vacío. Ctrl+A elige todo. "
                               "Editar puntos: elige la forma, arrastra un recuadro sobre "
                               "los puntos que sobran y presiona Supr."))

        # 2. Ajustar la forma elegida
        v.addWidget(self._title("2. Ajusta la forma elegida"))
        self.sel_buttons = []
        for pair in ([("↺ Girar", -15, 0), ("↻ Girar", 15, 0)],
                     [("－ Achicar", 0, 0.9), ("＋ Agrandar", 0, 1.1)]):
            row = QHBoxLayout()
            for text, deg, factor in pair:
                b = QPushButton(text)
                b.clicked.connect(lambda _=False, d=deg, f=factor: self.transform(d, f))
                row.addWidget(b)
                self.sel_buttons.append(b)
            v.addLayout(row)

        # 3. Cómo se borda
        v.addWidget(self._title("3. Cómo se borda"))
        self.kind_box = QComboBox()
        self.kind_box.addItems(["Relleno (llena la forma)",
                                "Contorno (solo la línea)",
                                "Satén (línea gruesa)"])
        self.kind_box.currentIndexChanged.connect(self.on_kind)
        v.addWidget(self.kind_box)

        # Grupo del relleno: dirección y separación
        self.fill_box = QWidget()
        fb = QVBoxLayout(self.fill_box)
        fb.setContentsMargins(0, 0, 0, 0)
        fb.setSpacing(6)
        self.angle_label = QLabel("Dirección de las puntadas: 45°")
        self.angle_slider = QSlider(Qt.Horizontal)
        self.angle_slider.setRange(0, 179)
        self.angle_slider.setValue(45)
        self.angle_slider.sliderPressed.connect(self.remember)
        self.angle_slider.valueChanged.connect(self.on_angle)
        fb.addWidget(self.angle_label)
        fb.addWidget(self.angle_slider)
        fb.addWidget(QLabel("Separación entre líneas"))
        self.spacing_box = QDoubleSpinBox()
        self.spacing_box.setRange(0.25, 1.2)
        self.spacing_box.setSingleStep(0.05)
        self.spacing_box.setDecimals(2)
        self.spacing_box.setSuffix(" mm")
        self.spacing_box.setValue(E.DEFAULT_SPACING_MM)
        self.spacing_box.valueChanged.connect(self.on_spacing)
        fb.addWidget(self.spacing_box)
        v.addWidget(self.fill_box)

        # Grupo del satén: ancho de la línea
        self.satin_box = QWidget()
        sb = QVBoxLayout(self.satin_box)
        sb.setContentsMargins(0, 0, 0, 0)
        sb.setSpacing(6)
        sb.addWidget(QLabel("Ancho del satén"))
        self.satin_spin = QDoubleSpinBox()
        self.satin_spin.setRange(0.5, 10)
        self.satin_spin.setSingleStep(0.1)
        self.satin_spin.setDecimals(1)
        self.satin_spin.setSuffix(" mm")
        self.satin_spin.setValue(self.satin_width)
        self.satin_spin.valueChanged.connect(self.on_satin_width)
        sb.addWidget(self.satin_spin)
        sb.addWidget(self._hint("Las letras con borde grueso quedan mejor en satén (3 a 5 mm)."))
        v.addWidget(self.satin_box)

        v.addWidget(QLabel("Color"))
        swatches = QGridLayout()
        self.swatches = {}
        for i, (name, hexcol) in enumerate(COLORS.items()):
            b = QPushButton()
            b.setToolTip(name)
            b.setFixedHeight(30)
            b.clicked.connect(lambda _=False, h=hexcol: self.set_color(h))
            swatches.addWidget(b, i // 4, i % 4)
            self.swatches[hexcol] = b
        v.addLayout(swatches)

        # 4. Importar
        v.addWidget(self._title("4. Importar"))
        self.btn_import = QPushButton("🪄  Foto o vector → bordado")
        self.btn_import.clicked.connect(self.import_file)
        v.addWidget(self.btn_import)
        v.addWidget(self._hint("Acepta .svg, .png o .jpg. Si tienes .ai o .pdf, "
                               "ábrelos en Inkscape y guárdalos como SVG."))

        # 5. Foto de fondo para calcar
        v.addWidget(self._title("5. Foto de fondo para calcar"))
        self.btn_bg = QPushButton("📷  Cargar foto de fondo")
        self.btn_bg.clicked.connect(self.load_bg)
        v.addWidget(self.btn_bg)
        self.bg_opacity = QSlider(Qt.Horizontal)
        self.bg_opacity.setRange(10, 100)
        self.bg_opacity.valueChanged.connect(self.on_bg_opacity)
        v.addWidget(QLabel("Transparencia de la foto"))
        v.addWidget(self.bg_opacity)
        self.bg_width = QDoubleSpinBox()
        self.bg_width.setRange(10, 600)
        self.bg_width.setDecimals(0)
        self.bg_width.setSuffix(" mm")
        self.bg_width.valueChanged.connect(self.on_bg_width)
        v.addWidget(QLabel("Ancho de la foto"))
        v.addWidget(self.bg_width)
        self.bg_remove = QPushButton("Quitar foto")
        self.bg_remove.clicked.connect(self.remove_bg)
        v.addWidget(self.bg_remove)
        v.addWidget(self._hint("Puedes arrastrar la foto sobre el bastidor."))

        # Acciones
        v.addWidget(self._title("Acciones"))
        row = QHBoxLayout()
        self.btn_undo = QPushButton("↶ Deshacer")
        self.btn_undo.clicked.connect(self.undo)
        self.btn_delete = QPushButton("🗑 Borrar")
        self.btn_delete.clicked.connect(self.delete_selected)
        row.addWidget(self.btn_undo)
        row.addWidget(self.btn_delete)
        v.addLayout(row)

        self.status = QLabel()
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        v.addWidget(self.status)

        save = QPushButton("💾  Guardar bordado (.dst)")
        save.setObjectName("save")
        save.clicked.connect(self.save)
        v.addWidget(save)
        v.addStretch(1)
        return panel

    # --- estado ---

    def selected_shape(self):
        """La forma que muestra el panel (la última tocada)."""
        i = self.canvas.selected
        if 0 <= i < len(self.shapes):
            return self.shapes[i]
        return None

    def selected_shapes(self):
        """Todas las formas seleccionadas."""
        return [self.shapes[i] for i in sorted(self.canvas.sel) if i < len(self.shapes)]

    def select_all(self):
        if not self.shapes:
            return
        self.set_mode("select")
        self.canvas.sel = set(range(len(self.shapes)))
        self.canvas.selected = len(self.shapes) - 1
        self.sync_panel()

    def snapshot(self):
        return [s.copy() for s in self.shapes]

    def push_history(self, snap):
        self.canvas.reopen = None       # cualquier cambio cierra la opción de reabrir
        self.history.append(snap)
        del self.history[:-50]

    def remember(self):
        self.push_history(self.snapshot())

    def add_shape(self, shape):
        self.remember()
        shape.color = self.current_color
        self.shapes.append(shape)

    def undo(self):
        cv = self.canvas
        if cv.mode.startswith("draw") and cv.in_progress:
            cv.in_progress.pop()                 # quita el último punto
            cv.update()
            return
        if cv.mode.startswith("draw") and cv.reopen is not None and self.history:
            # Cerraste la forma sin querer: la reabrimos para seguir con sus puntos.
            pts, idx = cv.reopen
            cv.reopen = None
            if idx == len(self.shapes) - 1:
                self.shapes.pop()
                self.history.pop()
                cv.in_progress = pts
                cv.clear_sel()
                self.sync_panel()
                return
        if not self.history:
            return
        self.shapes = self.history.pop()
        cv.vsel = set()
        cv.clear_sel()
        self.sync_panel()

    def delete_selected(self):
        if self.canvas.mode == "edit":
            self.delete_vertices()
            return
        idx = [i for i in sorted(self.canvas.sel) if i < len(self.shapes)]
        if not idx:
            return
        self.remember()
        for i in reversed(idx):
            del self.shapes[i]
        self.canvas.clear_sel()
        self.sync_panel()

    def delete_vertices(self):
        """Borra los puntos seleccionados de la forma en edición (con Ctrl+Z se recuperan)."""
        cv = self.canvas
        sh = cv._edit_shape()
        if sh is None or not cv.vsel:
            return
        self.remember()
        min_pts = 2 if sh.kind == "satin" else 3
        rings = []
        for ri, ring in enumerate(sh.rings):
            drop = sorted(vi for (r, vi) in cv.vsel if r == ri)
            keep = np.delete(ring, drop, axis=0) if drop else ring
            if len(keep) >= min_pts:
                rings.append(keep)
        cv.vsel = set()
        if rings:
            sh.rings = rings
            self.sync_panel()
        else:
            # Se borraron todos los puntos: la forma desaparece.
            self.shapes.pop(cv.edit_idx)
            self.set_mode("select")

    def set_mode(self, mode):
        if mode == "edit" and self.selected_shape() is None:
            self.statusBar().showMessage("Primero haz clic en la forma que quieres editar.", 6000)
            self.btn_edit.setChecked(self.canvas.mode == "edit")
            return
        cv = self.canvas
        cv.mode = mode
        cv.in_progress = []
        cv.reopen = None
        cv.vsel = set()
        cv.edit_idx = cv.selected if mode == "edit" else -1
        if mode not in ("select", "edit"):
            cv.clear_sel()                 # al dibujar, nada queda seleccionado
        for btn, m in ((self.btn_draw, "draw_fill"), (self.btn_satin, "draw_satin"),
                       (self.btn_select, "select"), (self.btn_edit, "edit")):
            btn.setChecked(mode == m)
        self.sync_panel()
        cv.update()

    def transform(self, deg, factor):
        shs = self.selected_shapes()
        if not shs:
            return
        self.remember()
        f = factor if factor else 1.0
        if len(shs) == 1:
            shs[0].transform(deg, f)
        else:
            # Varias formas: giran y crecen alrededor del centro del grupo.
            mn, mx = E.bbox_of(shs)
            c = (mn + mx) / 2
            t = np.radians(deg)
            rot = np.array([[np.cos(t), -np.sin(t)], [np.sin(t), np.cos(t)]])
            for sh in shs:
                sh.rings = [((r - c) @ rot.T) * f + c for r in sh.rings]
                if sh.kind == "satin":
                    sh.width *= f
        self.refresh()

    def on_hoop(self, _value=None):
        if self._updating:
            return
        self.hoop = [self.hoop_w.value(), self.hoop_h.value()]
        self.refresh()

    def on_design(self, which):
        """El usuario cambió el tamaño del diseño: escalamos todo."""
        if self._updating or not self.shapes:
            return
        b = E.bbox_of(self.shapes)
        if b is None:
            return
        mn, mx = b
        w, h = mx[0] - mn[0], mx[1] - mn[1]
        nw, nh = self.design_w.value(), self.design_h.value()
        if self.keep_ratio.isChecked() and w > 1e-9 and h > 1e-9:
            if which == "w":
                nh = nw * h / w
            else:
                nw = nh * w / h
        self.remember()
        E.resize_shapes(self.shapes, nw, nh)
        self.refresh()

    def on_kind(self, idx):
        shs = self.selected_shapes()
        if self._updating or not shs:
            return
        self.remember()
        kind = ("fill", "run", "satin")[idx]
        for sh in shs:
            sh.kind = kind
        self.sync_panel()

    def on_angle(self, value):
        self.angle_label.setText(f"Dirección de las puntadas: {value}°")
        shs = self.selected_shapes()
        if self._updating or not shs:
            return
        for sh in shs:
            sh.fill_angle = float(value)
        self.refresh()

    def on_satin_width(self, value):
        if self._updating:
            return
        self.satin_width = float(value)
        sats = [sh for sh in self.selected_shapes() if sh.kind == "satin"]
        if not sats:
            return
        self.remember()
        for sh in sats:
            sh.width = float(value)
        self.refresh()

    def on_spacing(self, value):
        shs = self.selected_shapes()
        if self._updating or not shs:
            return
        self.remember()
        for sh in shs:
            sh.spacing = float(value)
        self.refresh()

    def set_color(self, hexcol):
        self.current_color = hexcol
        shs = self.selected_shapes()
        if shs:
            self.remember()
            for sh in shs:
                sh.color = hexcol
        self.refresh()

    # --- importar y fondo ---

    def import_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Elegir foto o vector", "",
            "Fotos y vectores (*.svg *.png *.jpg *.jpeg *.bmp *.webp)")
        if not path:
            return
        hw, hh = self.hoop
        width, ok = QInputDialog.getDouble(
            self, "Tamaño del diseño", "Ancho del diseño (mm):",
            round(min(hw, hh) * 0.8), 5, hw, 0)
        if not ok:
            return
        photo = not path.lower().endswith(".svg")
        try:
            if photo:
                n, ok = QInputDialog.getInt(self, "Colores",
                                            "¿Cuántos colores tiene la foto? (2 a 8)",
                                            4, 2, 8)
                if not ok:
                    return
                shapes = E.photo_to_shapes(path, n, width)
            else:
                shapes = E.svg_to_shapes(path, width)
        except Exception as ex:  # noqa: BLE001 - mostramos el error al usuario
            QMessageBox.warning(self, "No se pudo importar", str(ex))
            return
        if not shapes:
            QMessageBox.information(self, "Nada que importar",
                                    "No encontré contornos en ese archivo.")
            return
        self.remember()
        E.center_shapes(shapes, hw / 2, hh / 2)
        self.shapes.extend(shapes)
        self.canvas.clear_sel()
        self.sync_panel()
        if photo:
            QMessageBox.information(
                self, "Listo",
                "La foto quedó convertida en formas de color.\n"
                "Revisa el resultado: el fondo también se borda. "
                "Si no lo quieres, selecciónalo y bórralo.")

    def load_bg(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Elegir foto de fondo", "",
            "Imágenes (*.png *.jpg *.jpeg *.bmp *.webp)")
        if not path:
            return
        img = QImage(path)
        if img.isNull():
            QMessageBox.warning(self, "No se pudo abrir", "No pude abrir esa imagen.")
            return
        hw, hh = self.hoop
        ratio = img.height() / img.width()
        w = min(hw * 0.9, hh * 0.9 / ratio)   # que quepa en el bastidor
        self.bg = {"img": img, "x": (hw - w) / 2, "y": (hh - w * ratio) / 2,
                   "w": w, "opacity": 0.5}
        self.sync_panel()

    def remove_bg(self):
        self.bg = None
        self.sync_panel()

    def on_bg_opacity(self, value):
        if self._updating or self.bg is None:
            return
        self.bg["opacity"] = value / 100
        self.canvas.update()

    def on_bg_width(self, value):
        if self._updating or self.bg is None:
            return
        self.bg["w"] = float(value)
        self.canvas.update()

    # --- panel y estado ---

    def sync_panel(self):
        """Pone los controles de acuerdo con la forma elegida y la foto."""
        self._updating = True
        sh = self.selected_shape()
        has = sh is not None
        for b in self.sel_buttons:
            b.setEnabled(has)
        self.btn_delete.setEnabled(has)
        self.angle_slider.setEnabled(has)
        self.spacing_box.setEnabled(has)
        self.satin_spin.setEnabled(has)
        if has:
            self.kind_box.setCurrentIndex({"fill": 0, "run": 1, "satin": 2}[sh.kind])
            self.angle_slider.setValue(int(sh.fill_angle) % 180)
            self.spacing_box.setValue(sh.spacing)
            self.satin_spin.setValue(sh.width if sh.kind == "satin" else self.satin_width)
            self.current_color = sh.color
        # Mostrar solo los controles que sirven para lo que está activo.
        satin_now = (has and sh.kind == "satin") or (not has and self.canvas.mode == "draw_satin")
        self.fill_box.setVisible(not satin_now)
        self.satin_box.setVisible(satin_now)
        self.kind_box.setEnabled(has)

        has_bg = self.bg is not None
        for w in (self.bg_opacity, self.bg_width, self.bg_remove):
            w.setEnabled(has_bg)
        if has_bg:
            self.bg_opacity.setValue(int(self.bg["opacity"] * 100))
            self.bg_width.setValue(self.bg["w"])
        self._updating = False
        self.refresh()

    def refresh(self):
        # Mostrar el tamaño actual del diseño (sin volver a escalar).
        old = self._updating
        self._updating = True
        b = E.bbox_of(self.shapes)
        has = b is not None
        self.design_w.setEnabled(has)
        self.design_h.setEnabled(has)
        self.keep_ratio.setEnabled(has)
        if has:
            mn, mx = b
            self.design_w.setValue(float(mx[0] - mn[0]))
            self.design_h.setValue(float(mx[1] - mn[1]))
        self._updating = old
        for hexcol, b in self.swatches.items():
            border = "3px solid #0f172a" if hexcol == self.current_color else "2px solid #cbd5e1"
            b.setStyleSheet(f"background:{hexcol}; border:{border}; border-radius:6px;")
        self.btn_undo.setEnabled(bool(self.history))
        if not self.shapes:
            text = "Todavía no hay formas.\nDibuja una o importa una foto o vector."
        else:
            info = E.analyze(self.shapes, self.hoop)
            cabe = "✔ cabe en el bastidor" if info["fits"] else "⚠ se sale del bastidor"
            text = (f"Puntadas: {info['stitches']:,}\n"
                    f"Diseño: {info['width']:.0f} × {info['height']:.0f} mm\n"
                    f"Bastidor: {self.hoop[0]:g} × {self.hoop[1]:g} mm\n{cabe}")
        n = len(self.canvas.sel)
        if n > 1:
            text = f"Seleccionadas: {n} formas\n" + text
        self.status.setText(text)
        self.canvas.update()

    def save(self):
        if not self.shapes:
            QMessageBox.information(self, "Nada que guardar",
                                    "Dibuja o importa al menos una forma primero.")
            return
        info = E.analyze(self.shapes, self.hoop)
        if not info["fits"]:
            r = QMessageBox.question(
                self, "Se sale del bastidor",
                f"El diseño mide {info['width']:.0f} × {info['height']:.0f} mm y el "
                f"bastidor es de {self.hoop[0]:g} × {self.hoop[1]:g} mm.\n¿Guardar igual?")
            if r != QMessageBox.Yes:
                return
        path, _ = QFileDialog.getSaveFileName(self, "Guardar bordado", "bordado.dst",
                                              "Tajima (*.dst)")
        if not path:
            return
        if not path.lower().endswith(".dst"):
            path += ".dst"
        E.write_dst(self.shapes, path, self.hoop)
        self.statusBar().showMessage(f"Guardado: {path}", 8000)


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
