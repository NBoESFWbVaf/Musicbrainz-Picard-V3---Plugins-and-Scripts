"""Scripts & Plugins — Einstiegspunkt des Plugins

Fügt der Picard-Symbolleiste eine eigene Schaltfläche hinzu, über die
sich das Fenster "Scripts & Plugins" öffnen lässt. Das Fenster mit
seinen Listen, dem Protokoll und der Ausführungslogik liegt in
window.py, allgemeine Hilfsfunktionen und Konstanten in helpers.py.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QToolBar

from .window import ScriptsPluginsWindow

# Fenster und Widgets global halten, damit Qt sie nicht wegräumt
# und disable() sie sauber entfernen kann.
_window = None
_toolbar = None
_action = None


def show_scripts_plugins_window(api, parent):
    """Zeigt das Fenster an (Singleton: wiederverwendet die Instanz)."""
    global _window
    if _window is None:
        _window = ScriptsPluginsWindow(api, parent)
    _window.show()
    _window.raise_()
    _window.activateWindow()
    _window.refresh()


def enable(api):
    """Wird beim Aktivieren des Plugins aufgerufen (UI ist zu diesem
    Zeitpunkt bereits verfügbar)."""
    global _toolbar, _action

    window = api.tagger.window
    if window is None:
        # Sicherheitsnetz: ohne Hauptfenster nichts injizieren.
        return

    # --- Schaltfläche in einer eigenen Symbolleiste (Internals) ---
    _action = QAction("Scripts & Plugins", window)
    _action.setToolTip("Öffnet das Fenster „Scripts & Plugins“")
    _action.triggered.connect(lambda: show_scripts_plugins_window(api, window))

    _toolbar = QToolBar("Scripts & Plugins", window)
    _toolbar.setObjectName("scripts_and_plugins_toolbar")
    # Beschriftung neben dem Icon anzeigen statt Icon-only.
    _toolbar.setToolButtonStyle(
        Qt.ToolButtonStyle.ToolButtonTextBesideIcon
    )
    _toolbar.addAction(_action)
    window.addToolBar(_toolbar)


def disable(api):
    """Aufräumen: Symbolleiste entfernen, Fenster schließen."""
    global _toolbar, _action, _window

    window = api.tagger.window

    if _toolbar is not None:
        if window is not None:
            window.removeToolBar(_toolbar)
        _toolbar.deleteLater()
        _toolbar = None

    if _action is not None:
        _action.deleteLater()
        _action = None

    if _window is not None:
        _window.close()
        _window.deleteLater()
        _window = None