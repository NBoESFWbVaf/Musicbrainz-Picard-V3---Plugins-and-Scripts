"""Scripts & Plugins — Einstiegspunkt des Plugins

Fügt der Picard-Symbolleiste eine eigene Schaltfläche hinzu, über die
sich das Fenster "Scripts & Plugins" öffnen lässt. Das Fenster mit
seinen Listen und der Ausführungslogik liegt in
window.py, allgemeine Hilfsfunktionen und Konstanten in helpers.py,
die Einstellungsseite in options_page.py. Die Cover-Informationen im
Cover-Panel des Hauptfensters (Modul coverinfo.py) werden hier mit
aktiviert und deaktiviert.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QToolBar

from .coverinfo import disable_cover_info, enable_cover_info
from .helpers import _config_value, _DEFAULT_GENRE_LIST
from .options_page import ScriptsPluginsOptionsPage
from .window import ScriptsPluginsWindow

# Fenster und Widgets global halten, damit Qt sie nicht wegräumt
# und disable() sie sauber entfernen kann.
_window = None
_toolbar = None
_action = None
# PluginApi-Objekt aus enable() — Picard 3.0.2 ruft disable() ohne
# Argumente auf (verifiziert gegen picard/plugin3/plugin.py), deshalb
# halten wir uns das API-Objekt selbst.
_api = None
# Live-Handler für die Cover-Option (für das saubere Trennen der
# Signal-Verbindung in disable()).
_cover_info_setting_handler = None


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
    Zeitpunkt bereits verfügbar). Das PluginApi-Objekt wird in _api
    gehalten, weil Picard 3.0.2 disable() ohne Argumente aufruft."""
    global _toolbar, _action, _cover_info_setting_handler, _api

    _api = api

    # --- Optionen registrieren (Plugin-Konfiguration, profilfähig) ---
    api.plugin_config.register_option(
        "show_disabled_scripts",
        True,
        title="Deaktivierte Scripte in der Liste anzeigen",
        in_profile=True,
    )
    api.plugin_config.register_option(
        "show_scripts_list",
        True,
        title="Tagging-Scripte anzeigen",
        in_profile=True,
    )
    api.plugin_config.register_option(
        "show_actions_list",
        True,
        title="Plugin-Aktionen anzeigen",
        in_profile=True,
    )
    api.plugin_config.register_option(
        "show_genre",
        True,
        title="Genre-Auswahl anzeigen",
        in_profile=True,
    )
    api.plugin_config.register_option(
        "show_numbering",
        True,
        title="Nummerierung anzeigen",
        in_profile=True,
    )
    api.plugin_config.register_option(
        "show_date",
        True,
        title="Datum anzeigen",
        in_profile=True,
    )
    api.plugin_config.register_option(
        "show_cover_info",
        True,
        title="Cover-Informationen anzeigen",
        in_profile=True,
    )
    api.plugin_config.register_option(
        "genre_list",
        _DEFAULT_GENRE_LIST,
        title="Genre-Liste (eine pro Zeile)",
        in_profile=True,
    )
    api.plugin_config.register_option(
        "list_row_spacing",
        6,
        title="Zusätzlicher Zeilenabstand (Pixel)",
        in_profile=True,
        bounds=(0, 30),
    )
    api.plugin_config.register_option(
        "window_width",
        640,
        title="Fensterbreite (Pixel)",
        in_profile=True,
        bounds=(640, 3840),
    )
    api.register_options_page(ScriptsPluginsOptionsPage)

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

    # --- Cover-Informationen im Cover-Panel (Modul coverinfo.py) ---
    # Kümmert sich selbst um Thread-Sicherheit (Verschiebung in den
    # Haupt-Thread über to_main) und ist intern gegen fehlende
    # Cover-Panel-Interna abgesichert. Die Anzeige lässt sich über die
    # Option „show_cover_info“ ein- und ausschalten — auch live, ohne
    # Neustart: Die Plugin-Konfiguration sendet setting_changed, sobald
    # der Optionsdialog den Wert schreibt.
    def _on_cover_info_setting_changed(name, old_value, new_value):
        if name != "show_cover_info":
            return
        if new_value:
            enable_cover_info(api)
        else:
            disable_cover_info()

    try:
        api.plugin_config.setting_changed.connect(_on_cover_info_setting_changed)
        _cover_info_setting_handler = _on_cover_info_setting_changed
    except Exception:
        # Signal nicht verfügbar: Die Option greift dann erst nach
        # einem Neustart (enable() liest sie beim Start aus).
        _cover_info_setting_handler = None

    if _config_value(api.plugin_config, "show_cover_info", True):
        enable_cover_info(api)


def disable():
    """Aufräumen: Symbolleiste entfernen, Fenster schließen.

    Picard 3.0.2 ruft disable() ohne Argumente auf (verifiziert gegen
    picard/plugin3/plugin.py: Plugin.disable() ruft
    self._module.disable() ohne Parameter). Das PluginApi-Objekt
    kommt deshalb aus der Modul-Variable _api (gesetzt in enable()).
    """
    global _toolbar, _action, _window, _cover_info_setting_handler

    api = _api

    # Live-Handler für die Cover-Option lösen, falls er verbunden wurde.
    if _cover_info_setting_handler is not None and api is not None:
        try:
            api.plugin_config.setting_changed.disconnect(
                _cover_info_setting_handler
            )
        except Exception:
            # Verbindung bestand nicht mehr (z. B. nach Reload).
            pass
        _cover_info_setting_handler = None

    # Cover-Info-Widgets und CoverArtBox-Patch aus coverinfo.py entfernen
    disable_cover_info()

    window = api.tagger.window if api is not None else None

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