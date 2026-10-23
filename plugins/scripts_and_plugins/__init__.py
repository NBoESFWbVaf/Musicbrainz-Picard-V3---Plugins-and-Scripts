"""Scripts & Plugins

Fügt der Picard-Symbolleiste eine eigene Schaltfläche hinzu, über die
sich das Fenster "Scripts & Plugins" öffnen lässt. Das Fenster listet
die eigenen Tagging-Scripte und die registrierten Plugin-Aktionen und
wendet die Auswahl auf die im Hauptfenster markierten Objekte an.
Listen und Statuszeile folgen der Auswahl im Hauptfenster automatisch.
"""

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QStyledItemDelegate,
    QToolBar,
    QVBoxLayout,
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
from picard.script import (
    ScriptError,
    ScriptParser,
    iter_tagging_scripts_from_config,
)
from picard.track import Track

try:
    from picard.cluster import ClusterList
except ImportError:
    ClusterList = None

# Fenster und Widgets global halten, damit Qt sie nicht wegräumt
# und disable() sie sauber entfernen kann.
_window = None
_toolbar = None
_action = None

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


class ListItemSpacingDelegate(QStyledItemDelegate):
    """Zeilenabstand in den Listen vergrößern."""

    EXTRA_SPACING = 6  # zusätzliche Pixel pro Zeile

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        size.setHeight(size.height() + self.EXTRA_SPACING)
        return size


class ScriptsPluginsWindow(QDialog):
    """Fenster mit Script- und Action-Liste.

    Bekommt das Picard-Hauptfenster als Parent übergeben, damit es
    an dieses gebunden ist und mit Picard geschlossen wird.
    """

    def __init__(self, api, parent=None):
        super().__init__(parent)
        self.api = api
        self.setWindowTitle("Scripts & Plugins")
        self.setMinimumSize(640, 420)

        # Fenster als reguläres Qt-Fenster deklarieren (statt Dialog):
        # Nur mit dem Window-Typ zeigen Windows & die meisten
        # Fenstermanager eine funktionierende Maximieren-Schaltfläche.
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowSystemMenuHint
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
            | Qt.WindowType.WindowCloseButtonHint
        )

        # Schrift im gesamten Fenster einen Punkt größer stellen.
        font = self.font()
        if font.pointSize() > 0:
            font.setPointSize(font.pointSize() + 1)
        self.setFont(font)

        # --- Script-Liste ---
        self.script_list = QListWidget(self)
        self.script_list.setItemDelegate(
            ListItemSpacingDelegate(self.script_list)
        )
        scripts_box = QGroupBox("Tagging-Scripte", self)
        scripts_layout = QVBoxLayout(scripts_box)
        scripts_layout.addWidget(self.script_list)

        # --- Action-Liste ---
        self.action_list = QListWidget(self)
        self.action_list.setItemDelegate(
            ListItemSpacingDelegate(self.action_list)
        )
        actions_box = QGroupBox("Plugin-Aktionen", self)
        actions_layout = QVBoxLayout(actions_box)
        actions_layout.addWidget(self.action_list)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.addWidget(scripts_box)
        splitter.addWidget(actions_box)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)

        # --- Schaltflächen ---
        self.refresh_button = QPushButton("Aktualisieren", self)
        self.run_script_button = QPushButton("Script ausführen", self)
        self.run_action_button = QPushButton("Aktion ausführen", self)
        self.run_script_button.setEnabled(False)
        self.run_action_button.setEnabled(False)

        button_layout = QHBoxLayout()
        button_layout.addWidget(self.refresh_button)
        button_layout.addStretch(1)
        button_layout.addWidget(self.run_script_button)
        button_layout.addWidget(self.run_action_button)

        self._status = QLabel("Öffne das Fenster oder klicke auf „Aktualisieren“.", self)
        self._status.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.addWidget(splitter, 1)
        layout.addLayout(button_layout)
        layout.addWidget(self._status)

        # --- Signale verbinden ---
        self.refresh_button.clicked.connect(self.refresh)
        self.run_script_button.clicked.connect(self._run_selected_script)
        self.run_action_button.clicked.connect(self._run_selected_action)
        self.script_list.itemDoubleClicked.connect(self._run_selected_script)
        self.action_list.itemDoubleClicked.connect(self._run_selected_action)
        self.script_list.currentItemChanged.connect(
            lambda *_: self.run_script_button.setEnabled(
                self.script_list.currentItem() is not None
            )
        )
        self.action_list.currentItemChanged.connect(
            lambda *_: self.run_action_button.setEnabled(
                self.action_list.currentItem() is not None
            )
        )

        # --- Automatische Auswahl-Verfolgung ---
        self._selection_signature = None
        self._needed_points = None
        self._use_poll_timer = False
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(500)
        self._poll_timer.timeout.connect(self._check_selection_changed)
        self._install_selection_tracking()

    # ------------------------------------------------------------------
    # Hilfsfunktionen

    def _selected_objects(self):
        """Aktuelle Auswahl im Picard-Hauptfenster."""
        window = self.api.tagger.window
        return list(getattr(window, "selected_objects", None) or [])

    def _set_status(self, text):
        self._status.setText(text)

    # ------------------------------------------------------------------
    # Auswahl-Verfolgung

    def _install_selection_tracking(self):
        """Auf Auswahländerungen im Hauptfenster reagieren.

        Bevorzugt über das itemSelectionChanged-Signal der Ansichten
        des Hauptfenster-Panels — dieselbe Quelle, über die Picard
        selbst window.selected_objects aktualisiert. Als Fallback
        dient ein kurzer Umfrage-Timer, falls die interne Struktur
        nicht zugreifbar ist.
        """
        window = self.api.tagger.window
        hooked = False
        try:
            views = list(getattr(window.panel, "_views", None) or [])
            if views:
                for view in views:
                    view.itemSelectionChanged.connect(
                        self._check_selection_changed
                    )
                hooked = True
        except Exception:
            self.api.logger.exception(
                "Auswahl-Signale des Hauptfensters konnten nicht "
                "verbunden werden."
            )
        if not hooked:
            self._use_poll_timer = True

    def _selection_signature(self, objs):
        return tuple((type(obj).__name__, id(obj)) for obj in objs)

    def _check_selection_changed(self):
        objs = self._selected_objects()
        signature = self._selection_signature(objs)
        if signature == self._selection_signature:
            return
        self._selection_signature = signature
        needed = set()
        for obj in objs:
            needed.update(_points_for_object(obj))
        if needed != self._needed_points:
            # Nur neu aufbauen, wenn sich der Objekttyp-Bereich der
            # Auswahl geändert hat — sonst geht die Listenauswahl
            # des Nutzers verloren.
            self._needed_points = needed
            self._populate_actions(objs)
        self._set_status(
            "Auswahl im Hauptfenster: %d Objekt(e)" % len(objs)
        )

    # ------------------------------------------------------------------
    # Listen füllen

    def _populate_scripts(self):
        self.script_list.clear()
        try:
            scripts = sorted(
                iter_tagging_scripts_from_config(),
                key=lambda s: (s.pos, s.name),
            )
        except Exception:
            self.api.logger.exception("Tagging-Scripte konnten nicht geladen werden.")
            return 0
        for script in scripts:
            label = script.name if script.enabled else "%s (deaktiviert)" % script.name
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, script)
            self.script_list.addItem(item)
        return len(scripts)

    def _populate_actions(self, objs):
        """Aktionen listen, die zur aktuellen Auswahl passen."""
        self.action_list.clear()
        needed_points = set()
        for obj in objs:
            needed_points.update(_points_for_object(obj))
        if not needed_points:
            self.action_list.addItem(QListWidgetItem("— keine Auswahl im Hauptfenster —"))
            return 0
        count = 0
        for point, label in _ACTION_POINTS:
            if point not in needed_points:
                continue
            try:
                action_classes = list(point)
            except Exception:
                self.api.logger.exception(
                    "Plugin-Aktionen (%s) konnten nicht geladen werden.", label
                )
                continue
            for action_class in action_classes:
                if not isinstance(action_class, type):
                    continue
                item = QListWidgetItem("[%s] %s" % (label, _action_title(action_class)))
                item.setData(Qt.ItemDataRole.UserRole, (action_class, point))
                self.action_list.addItem(item)
                count += 1
        if count == 0:
            self.action_list.addItem(
                QListWidgetItem("— keine passenden Plugin-Aktionen gefunden —")
            )
        return count

    def refresh(self):
        """Vollständige Aktualisierung beider Listen und der Statuszeile."""
        objs = self._selected_objects()
        self._selection_signature = self._selection_signature(objs)
        self._needed_points = set()
        for obj in objs:
            self._needed_points.update(_points_for_object(obj))
        num_scripts = self._populate_scripts()
        num_actions = self._populate_actions(objs)
        self._set_status(
            "Auswahl im Hauptfenster: %d Objekt(e) · %d Script(e) · %d Aktion(en)"
            % (len(objs), num_scripts, num_actions)
        )

    # ------------------------------------------------------------------
    # Ausführen: Scripte

    def _eval_script(self, parser, script, metadata):
        try:
            parser.eval(script.content, metadata)
            metadata.strip_whitespace()
            return True
        except ScriptError:
            self.api.logger.exception(
                "Fehler beim Ausführen des Tagging-Scriptes %s", script.name
            )
            return False

    def _apply_script(self, script, objs):
        """Script auf die ausgewählten Objekte anwenden.

        Folgt dem Muster aus Album._finalize_loading_album: pro Script
        ein frischer ScriptParser, Auswertung gegen die Track- bzw.
        Album-Metadaten, danach strip_whitespace() und UI-Update.
        """
        parser = ScriptParser()
        changed = 0
        for obj in objs:
            count = 0
            if isinstance(obj, Album):
                for track in obj.tracks:
                    if self._eval_script(parser, script, track.metadata):
                        count += 1
                if self._eval_script(parser, script, obj.metadata):
                    count += 1
            elif isinstance(obj, (Track, File)):
                if self._eval_script(parser, script, obj.metadata):
                    count += 1
            elif isinstance(obj, Cluster):
                for file in obj.files:
                    if self._eval_script(parser, script, file.metadata):
                        count += 1
            else:
                # Fallback für sonstige Objekte mit Metadaten (z. B. NATs)
                metadata = getattr(obj, "metadata", None)
                if metadata is not None and self._eval_script(
                    parser, script, metadata
                ):
                    count += 1
            if count:
                changed += count
                update = getattr(obj, "update", None)
                if callable(update):
                    try:
                        update()
                    except Exception:
                        self.api.logger.exception(
                            "UI-Update für %r fehlgeschlagen", obj
                        )
        return changed

    def _run_selected_script(self, item=None):
        if item is None:
            item = self.script_list.currentItem()
        if item is None:
            return
        script = item.data(Qt.ItemDataRole.UserRole)
        objs = self._selected_objects()
        if not objs:
            self._set_status("Keine Auswahl im Hauptfenster — bitte zuerst Objekte markieren.")
            return
        changed = self._apply_script(script, objs)
        self._set_status(
            "Script „%s“ ausgeführt: %d Metadaten in %d Objekt(en) aktualisiert."
            % (script.name, changed, len(objs))
        )

    # ------------------------------------------------------------------
    # Ausführen: Plugin-Aktionen

    def _run_selected_action(self, item=None):
        if item is None:
            item = self.action_list.currentItem()
        if item is None:
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        action_class, point = data
        objs = [obj for obj in self._selected_objects() if point in _points_for_object(obj)]
        if not objs:
            self._set_status(
                "Die aktuelle Auswahl enthält keine Objekte für diese Aktion."
            )
            return
        try:
            # Gleicher Instanziierungsweg wie im Kontextmenü von Picard.
            instance = action_class()
            instance.callback(objs)
        except Exception:
            self.api.logger.exception(
                "Fehler beim Ausführen der Plugin-Aktion %s",
                _action_title(action_class),
            )
            self._set_status("Fehler beim Ausführen der Aktion — siehe Log.")
            return
        self._set_status(
            "Aktion „%s“ auf %d Objekt(en) ausgeführt."
            % (_action_title(action_class), len(objs))
        )

    # ------------------------------------------------------------------
    # Qt-Ereignisse

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()
        if self._use_poll_timer and not self._poll_timer.isActive():
            self._poll_timer.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        if self._poll_timer.isActive():
            self._poll_timer.stop()


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