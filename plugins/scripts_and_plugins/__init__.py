"""Scripts & Plugins

Fügt der Picard-Symbolleiste eine eigene Schaltfläche hinzu,
über die sich das Fenster "Scripts & Plugins" öffnen lässt.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QDialog, QLabel, QToolBar, QVBoxLayout

# Fenster und Widgets global halten, damit Qt sie nicht wegräumt
# und disable() sie sauber entfernen kann.
_window = None
_toolbar = None
_action = None


class ScriptsPluginsWindow(QDialog):
    """Das Fenster, das über die Schaltfläche geöffnet wird.

    Bekommt das Picard-Hauptfenster als Parent übergeben, damit es
    an dieses gebunden ist (kein eigenständiges Top-Level-Fenster,
    schließt automatisch mit Picard).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Scripts & Plugins")
        self.setMinimumSize(420, 320)
        # Maximieren-Schaltfläche in der Titelleiste aktivieren.
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)

        layout = QVBoxLayout(self)
        label = QLabel(
            "Hier entsteht später die Übersicht der Scripte und Plugins.",
            self,
        )
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)


def show_scripts_plugins_window(parent):
    """Zeigt das Fenster an (Singleton: wiederverwendet die Instanz)."""
    global _window
    if _window is None:
        _window = ScriptsPluginsWindow(parent)
    _window.show()
    _window.raise_()
    _window.activateWindow()


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
    _action.triggered.connect(lambda: show_scripts_plugins_window(window))

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