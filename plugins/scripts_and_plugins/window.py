"""Fenster „Scripts & Plugins“: Listen, Protokoll und Ausführungslogik."""

from PyQt6.QtCore import QDateTime, Qt, QTimer
from PyQt6.QtGui import QFont
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
    QTextEdit,
    QVBoxLayout,
)

from picard.album import Album
from picard.cluster import Cluster
from picard.file import File
from picard.script import (
    ScriptError,
    ScriptParser,
    iter_tagging_scripts_from_config,
)
from picard.track import Track

from .helpers import (
    _ACTION_POINTS,
    _action_title,
    _config_value,
    _points_for_object,
)


class ListItemSpacingDelegate(QStyledItemDelegate):
    """Zeilenabstand in den Listen vergrößern."""

    def __init__(self, parent=None, extra_spacing=6):
        super().__init__(parent)
        self.extra_spacing = extra_spacing

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        size.setHeight(size.height() + self.extra_spacing)
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

        # Ausgangsschrift merken; Größe und Zeilenabstand werden über
        # _apply_display_settings() aus den Plugin-Optionen gesetzt.
        self._base_font = self.font()

        # --- Script-Liste ---
        self.script_list = QListWidget(self)
        self.script_list.setItemDelegate(
            ListItemSpacingDelegate(self.script_list)
        )
        scripts_box = QGroupBox("Tagging-Scripte", self)
        scripts_layout = QVBoxLayout(scripts_box)
        # Rechtsbündige Kopfzeile über der Script-Liste
        scripts_header = QHBoxLayout()
        scripts_header.addStretch(1)
        self.run_all_button = QPushButton("Alle aktiven Scripte ausführen", self)
        self.run_all_button.setToolTip(
            "Führt alle aktivierten Tagging-Scripte in "
            "Positions-Reihenfolge nacheinander auf der Auswahl aus"
        )
        scripts_header.addWidget(self.run_all_button)
        scripts_layout.addLayout(scripts_header)
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
        self.clear_log_button = QPushButton("Leeren", self)
        self.clear_log_button.setToolTip("Protokoll leeren")
        self.run_script_button = QPushButton("Script ausführen", self)
        self.run_action_button = QPushButton("Aktion ausführen", self)
        self.run_script_button.setEnabled(False)
        self.run_action_button.setEnabled(False)

        button_layout = QHBoxLayout()
        button_layout.addWidget(self.refresh_button)
        button_layout.addWidget(self.clear_log_button)
        button_layout.addStretch(1)
        button_layout.addWidget(self.run_script_button)
        button_layout.addWidget(self.run_action_button)

        self._status = QLabel("Öffne das Fenster oder klicke auf „Aktualisieren“.", self)
        self._status.setWordWrap(True)

        # --- Protokollfenster ---
        self.log_view = QTextEdit(self)
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(60)
        self.log_view.setPlaceholderText(
            "Start, Erfolg und Fehlschlag ausgeführter Scripte und Aktionen …"
        )
        log_box = QGroupBox("Protokoll", self)
        log_layout = QVBoxLayout(log_box)
        log_layout.addWidget(self.log_view)

        # Vertikaler Splitter zwischen Listen und Protokoll: Die Höhe
        # des Protokollfensters lässt sich mit der Maus frei verstellen,
        # ohne dass eines der beiden Bereiche ganz verschwindet.
        main_splitter = QSplitter(Qt.Orientation.Vertical, self)
        main_splitter.addWidget(splitter)
        main_splitter.addWidget(log_box)
        main_splitter.setStretchFactor(0, 1)
        main_splitter.setStretchFactor(1, 0)
        main_splitter.setCollapsible(0, False)
        main_splitter.setCollapsible(1, False)
        main_splitter.setSizes([520, 160])

        layout = QVBoxLayout(self)
        layout.addWidget(main_splitter, 1)
        layout.addLayout(button_layout)
        layout.addWidget(self._status)

        # --- Signale verbinden ---
        self.refresh_button.clicked.connect(self.refresh)
        self.clear_log_button.clicked.connect(self.log_view.clear)
        self.run_all_button.clicked.connect(self._run_all_scripts)
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
        self._last_selection_signature = None
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

    def _log_message(self, text):
        """Startmeldung im Protokoll festhalten.

        Standardfarbe, kein Symbol — die Bewertung der Ausführung
        erfolgt erst mit der Abschlussmeldung über _log_result().
        """
        timestamp = QDateTime.currentDateTime().toString("HH:mm:ss")
        self.log_view.append("[%s] %s" % (timestamp, text))

    def _log_result(self, success, text):
        """Abschlussmeldung im Protokoll festhalten."""
        symbol = "✓" if success else "✗"
        color = "green" if success else "red"
        timestamp = QDateTime.currentDateTime().toString("HH:mm:ss")
        self.log_view.append(
            "[%s] <span style=\"color:%s;\">%s %s</span>"
            % (timestamp, color, symbol, text)
        )

    def _apply_display_settings(self):
        """Schriftgröße und Zeilenabstand aus den Plugin-Optionen anwenden.

        Wird beim Anzeigen des Fensters aufgerufen, damit Änderungen aus
        den Picard-Optionen beim nächsten Öffnen greifen, ohne dass
        Picard neu gestartet werden muss.
        """
        offset = _config_value(self.api.plugin_config, "font_size_offset", 1)
        font = QFont(self._base_font)
        if offset > 0 and font.pointSize() > 0:
            font.setPointSize(font.pointSize() + offset)
        self.setFont(font)
        spacing = _config_value(self.api.plugin_config, "list_row_spacing", 6)
        self.script_list.setItemDelegate(
            ListItemSpacingDelegate(self.script_list, spacing)
        )
        self.action_list.setItemDelegate(
            ListItemSpacingDelegate(self.action_list, spacing)
        )

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
        if signature == self._last_selection_signature:
            return
        self._last_selection_signature = signature
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
        show_disabled = _config_value(
            self.api.plugin_config, "show_disabled_scripts", True
        )
        for script in scripts:
            if not script.enabled and not show_disabled:
                continue
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
        self._last_selection_signature = self._selection_signature(objs)
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
        Gibt (geänderte Metadaten, fehlgeschlagene Auswertungen) zurück.
        """
        parser = ScriptParser()
        changed = 0
        failed = 0
        for obj in objs:
            count = 0
            if isinstance(obj, Album):
                for track in obj.tracks:
                    if self._eval_script(parser, script, track.metadata):
                        count += 1
                    else:
                        failed += 1
                if self._eval_script(parser, script, obj.metadata):
                    count += 1
                else:
                    failed += 1
            elif isinstance(obj, (Track, File)):
                if self._eval_script(parser, script, obj.metadata):
                    count += 1
                else:
                    failed += 1
            elif isinstance(obj, Cluster):
                for file in obj.files:
                    if self._eval_script(parser, script, file.metadata):
                        count += 1
                    else:
                        failed += 1
            else:
                # Fallback für sonstige Objekte mit Metadaten (z. B. NATs)
                metadata = getattr(obj, "metadata", None)
                if metadata is not None:
                    if self._eval_script(parser, script, metadata):
                        count += 1
                    else:
                        failed += 1
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
        return changed, failed

    def _run_selected_script(self, item=None):
        # Achtung: Beim Doppelklick liefert Qt das QListWidgetItem,
        # beim Button-Klick jedoch ein bool (checked-Argument des
        # clicked-Signals). Daher explizit auf den Typ prüfen.
        if not isinstance(item, QListWidgetItem):
            item = self.script_list.currentItem()
        if item is None:
            return
        script = item.data(Qt.ItemDataRole.UserRole)
        objs = self._selected_objects()
        if not objs:
            self._log_result(
                False,
                "Keine Auswahl im Hauptfenster — bitte zuerst Objekte markieren.",
            )
            return
        self._log_message("Script „%s“ gestartet …" % script.name)
        try:
            changed, failed = self._apply_script(script, objs)
        except Exception:
            self.api.logger.exception(
                "Unerwarteter Fehler beim Ausführen des Scriptes %s", script.name
            )
            self._log_result(
                False,
                "Script „%s“ — unerwarteter Fehler, Details im Picard-Log."
                % script.name,
            )
            return
        if failed:
            self._log_result(
                False,
                "Script „%s“ mit Fehlern abgeschlossen: %d Metadaten geändert, %d Fehler — Details im Picard-Log."
                % (script.name, changed, failed),
            )
        else:
            self._log_result(
                True,
                "Script „%s“ ausgeführt: %d Metadaten in %d Objekt(en) aktualisiert."
                % (script.name, changed, len(objs)),
            )

    def _run_all_scripts(self, _checked=False):
        """Alle aktivierten Scripte nacheinander auf der Auswahl ausführen.

        Die Reihenfolge entspricht der Position der Scripte — dieselbe
        Reihenfolge, die Picard auch beim Release-Import verwendet.
        Deaktivierte Scripte werden übersprungen.
        """
        objs = self._selected_objects()
        if not objs:
            self._log_result(
                False,
                "Keine Auswahl im Hauptfenster — bitte zuerst Objekte markieren.",
            )
            return
        scripts = []
        for row in range(self.script_list.count()):
            data = self.script_list.item(row).data(Qt.ItemDataRole.UserRole)
            if data is not None and getattr(data, "enabled", False):
                scripts.append(data)
        if not scripts:
            self._log_result(False, "Keine aktiven Tagging-Scripte gefunden.")
            return
        self._log_message(
            "Starte %d aktive(s) Script(e) auf %d Objekt(en) …"
            % (len(scripts), len(objs))
        )
        total_changed = 0
        total_failed = 0
        for script in scripts:
            self._log_message("Script „%s“ gestartet …" % script.name)
            try:
                changed, failed = self._apply_script(script, objs)
            except Exception:
                self.api.logger.exception(
                    "Unerwarteter Fehler beim Ausführen des Scriptes %s", script.name
                )
                self._log_result(
                    False,
                    "Script „%s“ — unerwarteter Fehler, Details im Picard-Log."
                    % script.name,
                )
                total_failed += 1
                continue
            total_changed += changed
            total_failed += failed
            if failed:
                self._log_result(
                    False,
                    "Script „%s“ mit Fehlern abgeschlossen: %d Metadaten geändert, %d Fehler — Details im Picard-Log."
                    % (script.name, changed, failed),
                )
            else:
                self._log_result(
                    True,
                    "Script „%s“ ausgeführt: %d Metadaten in %d Objekt(en) aktualisiert."
                    % (script.name, changed, len(objs)),
                )
        if total_failed:
            self._log_result(
                False,
                "Alle Scripte abgeschlossen: %d Metadaten geändert, %d Fehler insgesamt — Details im Picard-Log."
                % (total_changed, total_failed),
            )
        else:
            self._log_result(
                True,
                "Alle Scripte abgeschlossen: %d Metadaten in %d Objekt(en) aktualisiert."
                % (total_changed, len(objs)),
            )

    # ------------------------------------------------------------------
    # Ausführen: Plugin-Aktionen

    def _run_selected_action(self, item=None):
        # Gleiche Vorsicht wie in _run_selected_script: Das Signal
        # itemDoubleClicked liefert ein QListWidgetItem, das Signal
        # clicked ein bool — hier darf das bool nicht als Item durchgehen.
        if not isinstance(item, QListWidgetItem):
            item = self.action_list.currentItem()
        if item is None:
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        action_class, point = data
        objs = [obj for obj in self._selected_objects() if point in _points_for_object(obj)]
        if not objs:
            self._log_result(
                False,
                "Die aktuelle Auswahl enthält keine Objekte für diese Aktion.",
            )
            return
        self._log_message(
            "Aktion „%s“ gestartet …" % _action_title(action_class)
        )
        try:
            # Gleicher Instanziierungsweg wie im Kontextmenü von Picard.
            instance = action_class()
            instance.callback(objs)
        except Exception:
            self.api.logger.exception(
                "Fehler beim Ausführen der Plugin-Aktion %s",
                _action_title(action_class),
            )
            self._log_result(
                False,
                "Aktion „%s“ — Fehler beim Ausführen, Details im Picard-Log."
                % _action_title(action_class),
            )
            return
        self._log_result(
            True,
            "Aktion „%s“ auf %d Objekt(en) ausgeführt."
            % (_action_title(action_class), len(objs)),
        )

    # ------------------------------------------------------------------
    # Qt-Ereignisse

    def showEvent(self, event):
        super().showEvent(event)
        self._apply_display_settings()
        self.refresh()
        if self._use_poll_timer and not self._poll_timer.isActive():
            self._poll_timer.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        if self._poll_timer.isActive():
            self._poll_timer.stop()