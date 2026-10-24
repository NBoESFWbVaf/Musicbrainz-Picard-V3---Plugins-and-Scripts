"""Hilfsfunktionen und Konstanten für das Plugin „Scripts & Plugins“."""

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