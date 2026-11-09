"""Erzeugt app/assets/icon.png und icon.ico (Schneeflocke auf Eisblau-Verlauf)."""
import math
import sys
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QPen

OUT = Path(__file__).resolve().parent.parent / "app" / "assets"


def draw(size: int) -> QImage:
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    grad = QLinearGradient(0, 0, size, size)
    grad.setColorAt(0, QColor("#3BA7F0"))
    grad.setColorAt(1, QColor("#2EC4B6"))
    p.setBrush(grad)
    p.setPen(Qt.NoPen)
    r = size * 0.22
    p.drawRoundedRect(QRectF(0, 0, size, size), r, r)
    c = QPointF(size / 2, size / 2)
    pen = QPen(QColor("white"), max(1.5, size * 0.065), Qt.SolidLine, Qt.RoundCap)
    p.setPen(pen)
    arm = size * 0.33
    for i in range(6):
        a = math.radians(i * 60 - 90)
        end = QPointF(c.x() + arm * math.cos(a), c.y() + arm * math.sin(a))
        p.drawLine(c, end)
        for frac in (0.55,):
            base = QPointF(c.x() + arm * frac * math.cos(a), c.y() + arm * frac * math.sin(a))
            for side in (-1, 1):
                b = a + side * math.radians(40)
                tip = QPointF(base.x() + arm * 0.35 * math.cos(b), base.y() + arm * 0.35 * math.sin(b))
                p.drawLine(base, tip)
    p.end()
    return img


def arrow(up: bool) -> QImage:
    """Kleine Pfeile für die Zahlenfelder."""
    from PySide6.QtGui import QPolygonF
    img = QImage(10, 6, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#8A9AAD"))
    pts = [QPointF(0, 6), QPointF(10, 6), QPointF(5, 0)] if up else [QPointF(0, 0), QPointF(10, 0), QPointF(5, 6)]
    p.drawPolygon(QPolygonF(pts))
    p.end()
    return img


if __name__ == "__main__":
    app = QGuiApplication(sys.argv)
    OUT.mkdir(parents=True, exist_ok=True)
    arrow(True).save(str(OUT / "arrow_up.png"))
    arrow(False).save(str(OUT / "arrow_down.png"))
    draw(256).save(str(OUT / "icon.png"))
    try:
        from PIL import Image
        im = Image.open(OUT / "icon.png")
        im.save(OUT / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    except ImportError:
        if not draw(256).save(str(OUT / "icon.ico")):
            print("Hinweis: Für icon.ico bitte Pillow installieren (pip install pillow).")
    print("Icon erstellt:", OUT)
