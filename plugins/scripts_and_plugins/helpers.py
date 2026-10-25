"""Hilfsfunktionen und Konstanten für das Plugin „Picard Extender“."""

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QIcon,
    QLinearGradient,
    QPainter,
    QPen,
    QPixmap,
)

from picard.album import Album
from picard.cluster import Cluster
from picard.file import File
from picard.extension_points.item_actions import (
    ext_point_album_actions,
    ext_point_cluster_actions,
    ext_point_clusterlist_actions,
    ext_point_file_actions,
    ext_point_track_actions,
)
from picard.track import Track

try:
    from picard.cluster import ClusterList
except ImportError:
    ClusterList = None

# Extension Points nach Objekttyp (Kategorie-Label, ExtPoint).
_ACTION_POINTS = (
    (ext_point_album_actions, "Album"),
    (ext_point_track_actions, "Track"),
    (ext_point_file_actions, "Datei"),
    (ext_point_cluster_actions, "Cluster"),
    (ext_point_clusterlist_actions, "Cluster-Liste"),
)

# Vorbelegung für die Genre-Liste (Option „genre_list“):
# Hauptstilrichtungen der Musik, eine pro Zeile — als Vorschlag frei
# editierbar; das Dropdown im Fenster zeigt genau diese Zeilen.
_DEFAULT_GENRE_LIST = """Rock
Pop
Classical
Jazz
Blues
Hip Hop
Electronic
House
Techno
Metal
Punk
Country
Folk
Soul
Funk
R&B
Reggae
Latin
World
Soundtrack"""


def _points_for_object(obj):
    """Passende Action-Extension-Points für ein Objekt ermitteln."""
    points = []
    if isinstance(obj, Album):
        points.append(ext_point_album_actions)
    if isinstance(obj, Track):
        points.append(ext_point_track_actions)
    if isinstance(obj, File):
        points.append(ext_point_file_actions)
    if isinstance(obj, Cluster):
        points.append(ext_point_cluster_actions)
    if ClusterList is not None and isinstance(obj, ClusterList):
        points.append(ext_point_clusterlist_actions)
    return points


def _action_title(action_class):
    """Anzeigenamen einer Action-Klasse ermitteln (mit Fallback)."""
    try:
        title = action_class.display_title()
    except Exception:
        title = None
    return str(title) if title else action_class.__name__


def _config_value(plugin_config, name, fallback):
    """Wert aus der Plugin-Konfiguration lesen, mit Fallback.

    ProfileConfigSection besitzt in Picard 3.0.2 keine get()-Methode;
    __getitem__ liefert None für unregistrierte Optionen. Da enable()
    alle Optionen mit Default registriert, greift der Fallback nur als
    Sicherheitsnetz (z. B. bei künftigen API-Änderungen).
    """
    try:
        value = plugin_config[name]
    except Exception:
        return fallback
    return fallback if value is None else value


def make_extender_icon():
    """Programmatisch gezeichnetes Plugin-Icon zurückgeben.

    Motiv: Stecker (Kabel nach oben, zwei Stifte nach unten) in Weiß
    auf abgerundeter Kachel mit blau-violem Farbverlauf — passend zum
    Namen „Picard Extender“. Das Icon wird in mehreren Größen
    gerendert, damit es in der Symbolleiste scharf bleibt; es ist
    komplett im Code gezeichnet, es wird keine externe Datei nötig.
    """
    icon = QIcon()
    for size in (16, 20, 24, 32, 48, 64):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Kachel mit vertikalem Farbverlauf (blau → violett)
        gradient = QLinearGradient(0.0, 0.0, 0.0, float(size))
        gradient.setColorAt(0.0, QColor("#4A7FD4"))
        gradient.setColorAt(1.0, QColor("#7B4AC8"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(gradient))
        tile = QRectF(0.5, 0.5, size - 1.0, size - 1.0)
        painter.drawRoundedRect(tile, size * 0.22, size * 0.22)

        # Stecker in Weiß
        white = QColor("#FFFFFF")
        painter.setBrush(QBrush(white))

        def _rrect(x, y, w, h, r):
            painter.drawRoundedRect(
                QRectF(x * size, y * size, w * size, h * size),
                r * size,
                r * size,
            )

        _rrect(0.32, 0.28, 0.36, 0.30, 0.05)  # Stecker-Körper
        _rrect(0.39, 0.58, 0.08, 0.18, 0.02)  # Stift links
        _rrect(0.53, 0.58, 0.08, 0.18, 0.02)  # Stift rechts

        # Kabel nach oben (runde Enden)
        pen = QPen(white, 0.07 * size)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawLine(
            QPointF(0.50 * size, 0.28 * size),
            QPointF(0.50 * size, 0.14 * size),
        )
        painter.end()
        icon.addPixmap(pixmap)
    return icon