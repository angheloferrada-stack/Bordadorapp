"""Diseñador de bordados simple (inspirado en Wings XP).

Flujo:
  1. Dibuja una forma (clic en cada punto, doble clic para cerrarla).
  2. Elige si es relleno o contorno, el color y la dirección de las puntadas.
  3. Guarda el .dst y pásalo a la bordadora por USB.
"""
import sys

from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPen, QPolygonF, QShortcut
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDoubleSpinBox, QFileDialog, QGridLayout,
    QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton, QSlider,
    QVBoxLayout, QWidget,
)

import engine as E

COLORS = {
    "Azul": "#1e3a8a", "Rojo": "#b91c1c", "Verde": "#15803d",
    "Amarillo": "#eab308", "Negro": "#111827", "Naranja": "#ea580c",
    "Morado": "#7e22ce", "Café": "#78350f",
}

STYLE = """
QWidget#panel { background: #ffffff; }
QPushButton {
    background: #f1f5f9; border: 1px solid #cbd5e1; border-radius: 8px;
    padding: 8px; font-size: 13px; color: #0f172a;
}
QPushButton:hover   { background: #e2e8f0; }
QPushButton:checked { background: #2563eb; color: white; border-color: #2563eb; }
QPushButton:disabled { color: #94a3b8; background: #f8fafc; }
QPushButton#save {
    background: #16a34a; color: white; border: none; font-weight: 600; padding: 12px;
}
QPushButton#save:hover { background: #15803d; }
QLabel#status { background: #f8fafc; border-radius: 8px; padding: 8px; color: #334155; }
"""


class Canvas(QWidget):
    """El bastidor donde se dibuja. Todo se trabaja en milímetros."""

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.mode = "draw"        # "draw" o "select"
        self.in_progress = []     # puntos de la forma que se está dibujando
        self.selected = -1
        self._drag_start = None
        self._drag_orig = None
        self._drag_before = None
        self.setMinimumSize(700, 500)
        self.setFocusPolicy(Qt.StrongFocus)

    # --- conversión mm <-> píxeles ---

    def _scale(self):
        m = 36
        s = min((self.width() - 2 * m) / E.HOOP_W_MM,
                (self.height() - 2 * m) / E.HOOP_H_MM)
        return s, (self.width() - E.HOOP_W_MM * s) / 2, (self.height() - E.HOOP_H_MM * s) / 2

    def to_px(self, x, y):
        s, ox, oy = self._scale()
        return QPointF(ox + x * s, oy + y * s)

    def to_mm(self, pos):
        s, ox, oy = self._scale()
        return ((pos.x() - ox) / s, (pos.y() - oy) / s)

    # --- dibujo ---

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#f1f5f9"))

        s, ox, oy = self._scale()
        hoop = QRectF(ox, oy, E.HOOP_W_MM * s, E.HOOP_H_MM * s)
        p.fillRect(hoop, QColor("white"))
        p.setPen(QPen(QColor("#94a3b8"), 1.5, Qt.DashLine))
        p.drawRect(hoop)
        p.setPen(QColor("#64748b"))
        p.drawText(hoop.adjusted(10, 6, 0, 0), Qt.AlignTop | Qt.AlignLeft,
                   "Bastidor 380 × 260 mm")

        for i, sh in enumerate(self.win.shapes):
            col = QColor(sh.color)
            fill = QColor(col.red(), col.green(), col.blue(), 45)
            poly = QPolygonF([self.to_px(x, y) for x, y in sh.points])

            # Vista previa de las puntadas: así se ve hacia dónde van.
            p.setPen(QPen(QColor(col.red(), col.green(), col.blue(), 140), 1))
            for line in E.shape_polylines(sh):
                for (x1, y1), (x2, y2) in zip(line, line[1:]):
                    p.drawLine(self.to_px(x1, y1), self.to_px(x2, y2))

            p.setBrush(fill)
            p.setPen(QPen(col, 2))
            p.drawPolygon(poly)
            if i == self.selected:
                p.setBrush(Qt.NoBrush)
                p.setPen(QPen(QColor("#2563eb"), 2.5, Qt.DashLine))
                p.drawPolygon(poly)

        if self.in_progress:
            pts = [self.to_px(x, y) for x, y in self.in_progress]
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor("#2563eb"), 2))
            p.drawPolyline(QPolygonF(pts))
            p.setBrush(QColor("#2563eb"))
            for q in pts:
                p.drawEllipse(q, 4, 4)
        p.end()

    # --- ratón y teclado ---

    @staticmethod
    def _dist(a, b):
        return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        x, y = self.to_mm(e.position())
        if self.mode == "draw":
            if (len(self.in_progress) >= 3
                    and self._dist(self.in_progress[0], (x, y)) < 2.5):
                self.finish_shape()
                return
            if not self.in_progress or self._dist(self.in_progress[-1], (x, y)) > 0.5:
                self.in_progress.append((x, y))
            self.update()
            return

        # modo mover / elegir
        self.selected = -1
        for i in reversed(range(len(self.win.shapes))):
            if E.contains(self.win.shapes[i].points, x, y):
                self.selected = i
                break
        if self.selected >= 0:
            self._drag_start = (x, y)
            self._drag_orig = list(self.win.shapes[self.selected].points)
            self._drag_before = self.win.snapshot()
        self.win.sync_panel()
        self.update()

    def mouseMoveEvent(self, e):
        if self._drag_start is None:
            return
        x, y = self.to_mm(e.position())
        dx, dy = x - self._drag_start[0], y - self._drag_start[1]
        self.win.shapes[self.selected].points = E.translate(self._drag_orig, dx, dy)
        self.update()

    def mouseReleaseEvent(self, _e):
        if self._drag_start is not None:
            moved = self.win.shapes[self.selected].points != self._drag_orig
            if moved:
                self.win.push_history(self._drag_before)
            self._drag_start = None
            self._drag_orig = None
            self.win.refresh()

    def mouseDoubleClickEvent(self, e):
        if self.mode == "draw" and len(self.in_progress) >= 3:
            self.finish_shape()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.finish_shape()
        elif e.key() == Qt.Key_Escape:
            self.in_progress = []
            self.update()
        else:
            super().keyPressEvent(e)

    def finish_shape(self):
        if len(self.in_progress) < 3:
            return
        self.win.add_shape(E.Shape(self.in_progress))
        self.in_progress = []
        self.selected = len(self.win.shapes) - 1
        self.win.sync_panel()
        self.update()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Bordado simple")
        self.shapes = []
        self.history = []
        self.current_color = COLORS["Azul"]
        self._updating = False

        self.canvas = Canvas(self)
        root = QWidget()
        lay = QHBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._build_panel())
        lay.addWidget(self.canvas, 1)
        self.setCentralWidget(root)
        self.setStyleSheet(STYLE)

        QShortcut(QKeySequence("Ctrl+Z"), self, activated=self.undo)
        QShortcut(QKeySequence("Ctrl+S"), self, activated=self.save)
        QShortcut(QKeySequence(Qt.Key_Delete), self, activated=self.delete_selected)

        self.resize(1200, 780)
        self.refresh()

    # --- panel izquierdo ---

    def _title(self, text):
        lab = QLabel(text)
        lab.setStyleSheet("font-weight:600; font-size:13px; margin-top:10px;")
        return lab

    def _hint(self, text):
        lab = QLabel(text)
        lab.setWordWrap(True)
        lab.setStyleSheet("color:#64748b; font-size:11px;")
        return lab

    def _build_panel(self):
        panel = QWidget()
        panel.setObjectName("panel")
        panel.setFixedWidth(270)
        v = QVBoxLayout(panel)
        v.setContentsMargins(14, 10, 14, 14)
        v.setSpacing(6)

        # 1. Dibujar o mover
        v.addWidget(self._title("1. Dibuja o mueve"))
        self.btn_draw = QPushButton("✏  Dibujar forma")
        self.btn_draw.setCheckable(True)
        self.btn_draw.setChecked(True)
        self.btn_draw.clicked.connect(lambda: self.set_mode("draw"))
        self.btn_select = QPushButton("✋  Mover / elegir")
        self.btn_select.setCheckable(True)
        self.btn_select.clicked.connect(lambda: self.set_mode("select"))
        v.addWidget(self.btn_draw)
        v.addWidget(self.btn_select)
        v.addWidget(self._hint("Haz clic para poner puntos. "
                               "Doble clic o Enter para cerrar la forma."))

        # 2. Ajustar la forma seleccionada
        v.addWidget(self._title("2. Ajusta la forma elegida"))
        self.sel_buttons = []
        row = QHBoxLayout()
        for text, fn in [("↺ Girar", lambda: self.rotate(-15)),
                         ("↻ Girar", lambda: self.rotate(15))]:
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
            self.sel_buttons.append(b)
        v.addLayout(row)
        row = QHBoxLayout()
        for text, fn in [("－ Achicar", lambda: self.scale(0.9)),
                         ("＋ Agrandar", lambda: self.scale(1.1))]:
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
            self.sel_buttons.append(b)
        v.addLayout(row)

        # 3. Puntadas
        v.addWidget(self._title("3. Cómo se borda"))
        self.kind_box = QComboBox()
        self.kind_box.addItems(["Relleno (llena la forma)", "Contorno (solo la línea)"])
        self.kind_box.currentIndexChanged.connect(self.on_kind)
        v.addWidget(self.kind_box)

        self.angle_label = QLabel("Dirección de las puntadas: 45°")
        self.angle_slider = QSlider(Qt.Horizontal)
        self.angle_slider.setRange(0, 179)
        self.angle_slider.setValue(45)
        self.angle_slider.sliderPressed.connect(lambda: self.remember())
        self.angle_slider.valueChanged.connect(self.on_angle)
        v.addWidget(self.angle_label)
        v.addWidget(self.angle_slider)

        self.spacing_label = QLabel("Separación entre líneas")
        self.spacing_box = QDoubleSpinBox()
        self.spacing_box.setRange(0.25, 1.2)
        self.spacing_box.setSingleStep(0.05)
        self.spacing_box.setDecimals(2)
        self.spacing_box.setSuffix(" mm")
        self.spacing_box.setValue(E.DEFAULT_SPACING_MM)
        self.spacing_box.valueChanged.connect(self.on_spacing)
        v.addWidget(self.spacing_label)
        v.addWidget(self.spacing_box)

        v.addWidget(QLabel("Color"))
        grid = QGridLayout()
        self.swatches = {}
        for i, (name, hexcol) in enumerate(COLORS.items()):
            b = QPushButton()
            b.setToolTip(name)
            b.setFixedHeight(30)
            b.setStyleSheet(f"background:{hexcol}; border:2px solid #cbd5e1; border-radius:6px;")
            b.clicked.connect(lambda _=False, h=hexcol: self.set_color(h))
            grid.addWidget(b, i // 4, i % 4)
            self.swatches[hexcol] = b
        v.addLayout(grid)

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

        v.addStretch(1)

        self.status = QLabel()
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        v.addWidget(self.status)

        save = QPushButton("💾  Guardar bordado (.dst)")
        save.setObjectName("save")
        save.clicked.connect(self.save)
        v.addWidget(save)
        return panel

    # --- estado y acciones ---

    def selected_shape(self):
        i = self.canvas.selected
        if 0 <= i < len(self.shapes):
            return self.shapes[i]
        return None

    def snapshot(self):
        return [s.copy() for s in self.shapes]

    def push_history(self, snap):
        self.history.append(snap)
        del self.history[:-50]

    def remember(self):
        self.push_history(self.snapshot())

    def add_shape(self, shape):
        self.remember()
        shape.color = self.current_color
        self.shapes.append(shape)

    def undo(self):
        if not self.history:
            return
        self.shapes = self.history.pop()
        self.canvas.selected = -1
        self.refresh()

    def delete_selected(self):
        i = self.canvas.selected
        if i < 0 or i >= len(self.shapes):
            return
        self.remember()
        del self.shapes[i]
        self.canvas.selected = -1
        self.refresh()

    def set_mode(self, mode):
        self.canvas.mode = mode
        self.canvas.in_progress = []
        self.btn_draw.setChecked(mode == "draw")
        self.btn_select.setChecked(mode == "select")
        self.canvas.update()

    def rotate(self, deg):
        sh = self.selected_shape()
        if sh is None:
            return
        self.remember()
        sh.points = E.rotate_scale(sh.points, deg)
        self.refresh()

    def scale(self, factor):
        sh = self.selected_shape()
        if sh is None:
            return
        self.remember()
        sh.points = E.rotate_scale(sh.points, 0, factor)
        self.refresh()

    def on_kind(self, idx):
        if self._updating:
            return
        sh = self.selected_shape()
        if sh is None:
            return
        self.remember()
        sh.kind = "fill" if idx == 0 else "run"
        self.refresh()

    def on_angle(self, value):
        self.angle_label.setText(f"Dirección de las puntadas: {value}°")
        if self._updating:
            return
        sh = self.selected_shape()
        if sh is None:
            return
        sh.fill_angle = float(value)
        self.refresh()

    def on_spacing(self, value):
        if self._updating:
            return
        sh = self.selected_shape()
        if sh is None:
            return
        self.remember()
        sh.spacing = float(value)
        self.refresh()

    def set_color(self, hexcol):
        self.current_color = hexcol
        sh = self.selected_shape()
        if sh is not None:
            self.remember()
            sh.color = hexcol
        self.refresh()

    def sync_panel(self):
        """Pone los controles de acuerdo con la forma elegida."""
        self._updating = True
        sh = self.selected_shape()
        has = sh is not None
        for b in self.sel_buttons:
            b.setEnabled(has)
        self.btn_delete.setEnabled(has)
        self.kind_box.setEnabled(has)
        self.angle_slider.setEnabled(has)
        self.spacing_box.setEnabled(has)
        if has:
            self.kind_box.setCurrentIndex(0 if sh.kind == "fill" else 1)
            self.angle_slider.setValue(int(sh.fill_angle) % 180)
            self.spacing_box.setValue(sh.spacing)
            self.current_color = sh.color
        self._updating = False
        self.refresh()

    def refresh(self):
        for hexcol, b in self.swatches.items():
            border = "3px solid #0f172a" if hexcol == self.current_color else "2px solid #cbd5e1"
            b.setStyleSheet(f"background:{hexcol}; border:{border}; border-radius:6px;")
        self.btn_undo.setEnabled(bool(self.history))
        _, info = E.build_pattern(self.shapes)
        if not self.shapes:
            text = "Todavía no hay formas. Empieza dibujando una."
        else:
            cabe = "✔ cabe en el bastidor" if info["fits"] else "⚠ se sale del bastidor"
            text = (f"Puntadas: {info['stitches']}\n"
                    f"Tamaño: {info['width']:.0f} × {info['height']:.0f} mm\n{cabe}")
        self.status.setText(text)
        self.canvas.update()

    def save(self):
        if not self.shapes:
            QMessageBox.information(self, "Nada que guardar", "Dibuja al menos una forma primero.")
            return
        _, info = E.build_pattern(self.shapes)
        if not info["fits"]:
            r = QMessageBox.question(
                self, "Se sale del bastidor",
                "El diseño es más grande que el bastidor de 380 × 260 mm.\n"
                "¿Guardar igual?")
            if r != QMessageBox.Yes:
                return
        path, _ = QFileDialog.getSaveFileName(self, "Guardar bordado", "bordado.dst",
                                              "Tajima (*.dst)")
        if not path:
            return
        if not path.lower().endswith(".dst"):
            path += ".dst"
        E.write_dst(self.shapes, path)
        self.status.setText(self.status.text() + f"\n\n✔ Guardado: {path}")


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
