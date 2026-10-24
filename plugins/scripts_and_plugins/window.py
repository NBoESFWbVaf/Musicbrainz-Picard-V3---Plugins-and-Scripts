"""Fenster „Scripts & Plugins“: Listen, Protokoll und Ausführungslogik."""

import random

from PyQt6.QtCore import QDateTime, QSize, Qt, QTimer
from PyQt6.QtWidgets import (
    QComboBox,
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

# Qts Größenlimit für "keine Höchstgrenze gesetzt" (QWIDGETSIZE_MAX).
# PyQt6 exportiert die Konstante nicht aus QtCore, deshalb hier als
# literalen Wert definiert (identisch zu Qt: 2**24 - 1).
_WIDGET_SIZE_MAX = 16777215


class ListItemSpacingDelegate(QStyledItemDelegate):
    """Zeilenabstand in den Listen vergrößern."""

    def __init__(self, parent=None, extra_spacing=6):
        super().__init__(parent)
        self.extra_spacing = extra_spacing

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        size.setHeight(size.height() + self.extra_spacing)
        return size


class CompactListWidget(QListWidget):
    """Liste mit inhaltsbasierter Größen-Schätzung.

    QListWidget liefert von Haus aus eine feste Standard-Größen-Schätzung
    (unabhängig vom Inhalt). Für die kompakte Fensterhöhe brauchen wir
    aber die tatsächliche Höhe aller Einträge: sizeHint() bildet sie aus
    den Zeilen-Höhen ab und wird nie größer als die eingestellte
    Höchsthöhe. Darauf bauen die Größen-Schätzungen der Bereichs-Boxen
    und damit die Begrenzung des Listenbereichs auf.
    """

    def sizeHint(self):
        hint = super().sizeHint()
        count = self.count()
        if count == 0:
            height = self.sizeHintForRow(0)
        else:
            height = sum(self.sizeHintForRow(i) for i in range(count))
        height += 2 * self.frameWidth()
        if self.maximumHeight() < _WIDGET_SIZE_MAX:
            height = min(height, self.maximumHeight())
        return QSize(hint.width(), height)


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

        # --- Schaltflächen (früh erstellt, da sie innerhalb der
        #     Bereichs-Boxen platziert werden) ---
        self.refresh_button = QPushButton("Aktualisieren", self)
        self.clear_log_button = QPushButton("Leeren", self)
        self.clear_log_button.setToolTip("Protokoll leeren")
        self.run_script_button = QPushButton("Gewähltes Script ausführen", self)
        self.run_all_button = QPushButton("Alle aktiven Scripte ausführen", self)
        self.run_all_button.setToolTip(
            "Führt alle aktivierten Tagging-Scripte in "
            "Positions-Reihenfolge nacheinander auf der Auswahl aus"
        )
        self.run_action_button = QPushButton("Aktion ausführen", self)
        self.overwrite_genres_button = QPushButton("Alle Genre überschreiben", self)
        self.append_genre_button = QPushButton("Dieses Genre anhängen", self)
        self.overwrite_genres_button.setToolTip(
            "Ersetzt vorhandene Genre-Werte auf der Auswahl durch die "
            "gewählte Genre"
        )
        self.append_genre_button.setToolTip(
            "Hängt die gewählte Genre an vorhandene Genre-Werte an "
            "(ohne Dubletten)"
        )
        self.renumber_button = QPushButton("Tracks neu nummerieren", self)
        self.renumber_button.setToolTip(
            "Nummeriert die Tracks des gewählten Albums pro Disc neu: "
            "nur Tracks mit vorhandener Datei, lückenlos ab 1; "
            "totaltracks = Anzahl der Tracks mit Datei je Disc"
        )
        self.mix_button = QPushButton("Tracks gemixt nummerieren", self)
        self.mix_button.setToolTip(
            "Nummeriert die Tracks des gewählten Albums pro Disc "
            "zufällig neu — derselbe Interpret folgt nie unmittelbar "
            "auf sich selbst (soweit vermeidbar); nur Tracks mit "
            "vorhandener Datei, totaltracks = Anzahl der Tracks mit "
            "Datei je Disc"
        )
        self.run_script_button.setEnabled(False)
        self.run_action_button.setEnabled(False)
        self.overwrite_genres_button.setEnabled(False)
        self.append_genre_button.setEnabled(False)
        self.renumber_button.setEnabled(False)
        self.mix_button.setEnabled(False)

        # --- Script-Liste ---
        self.script_list = CompactListWidget(self)
        self.script_list.setItemDelegate(
            ListItemSpacingDelegate(self.script_list)
        )
        self.scripts_box = QGroupBox("Tagging-Scripte", self)
        scripts_layout = QVBoxLayout(self.scripts_box)
        scripts_layout.addWidget(self.script_list)
        # Beide Ausführungs-Schaltflächen direkt unter der Script-Liste
        # (rechtsbündig, „Alle aktiven Scripte ausführen“ rechts daneben)
        scripts_footer = QHBoxLayout()
        scripts_footer.addStretch(1)
        scripts_footer.addWidget(self.run_script_button)
        scripts_footer.addWidget(self.run_all_button)
        scripts_layout.addLayout(scripts_footer)

        # --- Action-Liste ---
        self.action_list = CompactListWidget(self)
        self.action_list.setItemDelegate(
            ListItemSpacingDelegate(self.action_list)
        )
        self.actions_box = QGroupBox("Plugin-Aktionen", self)
        actions_layout = QVBoxLayout(self.actions_box)
        actions_layout.addWidget(self.action_list)
        # „Aktion ausführen“ direkt unter der Action-Liste
        actions_footer = QHBoxLayout()
        actions_footer.addStretch(1)
        actions_footer.addWidget(self.run_action_button)
        actions_layout.addLayout(actions_footer)

        self._lists_splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self._lists_splitter.addWidget(self.scripts_box)
        self._lists_splitter.addWidget(self.actions_box)
        self._lists_splitter.setStretchFactor(0, 1)
        self._lists_splitter.setStretchFactor(1, 1)

        # Untere Schaltflächenzeile: nur noch Fenster-übergreifendes
        button_layout = QHBoxLayout()
        button_layout.addWidget(self.refresh_button)
        button_layout.addWidget(self.clear_log_button)
        button_layout.addStretch(1)

        self._status = QLabel("Öffne das Fenster oder klicke auf „Aktualisieren“.", self)
        self._status.setWordWrap(True)

        # --- Genre-Auswahl ---
        # Dropdown zwischen den Listen und dem Protokoll: Inhalt ist die
        # Genre-Liste aus den Optionen (eine Zeile pro Genre). Gewählt
        # wird erst mit einer der beiden Schaltflächen angewendet —
        # überschreiben oder anhängen. Ohne Auswahl zeigt das Feld nur
        # den Platzhalter.
        self.genre_combo = QComboBox(self)
        self.genre_combo.setPlaceholderText("Genre wählen …")
        self.genre_combo.setToolTip(
            "Genre wählen und unten überschreiben oder anhängen"
        )
        self.genre_box = QGroupBox("Genre hinzufügen", self)
        genre_layout = QVBoxLayout(self.genre_box)
        genre_layout.addWidget(self.genre_combo)
        # Beide Schaltflächen direkt unter dem Dropdown (rechtsbündig)
        genre_footer = QHBoxLayout()
        genre_footer.addStretch(1)
        genre_footer.addWidget(self.overwrite_genres_button)
        genre_footer.addWidget(self.append_genre_button)
        genre_layout.addLayout(genre_footer)
        # Höhe fixieren (Combo plus Fußzeile plus Titel): Der Bereich soll
        # beim Vergrößern des Fensters nicht wachsen.
        self.genre_box.setMaximumHeight(self.genre_box.sizeHint().height())

        # --- Nummerierung ---
        # Eigener Bereich neben der Genre-Auswahl (analog zu Script-
        # und Action-Liste als eigener Kasten) mit den beiden
        # Nummerierungs-Schaltflächen.
        self.numbering_box = QGroupBox("Nummerierung", self)
        numbering_layout = QVBoxLayout(self.numbering_box)
        numbering_footer = QHBoxLayout()
        numbering_footer.addStretch(1)
        numbering_footer.addWidget(self.renumber_button)
        numbering_footer.addWidget(self.mix_button)
        numbering_layout.addLayout(numbering_footer)
        self.numbering_box.setMaximumHeight(
            self.numbering_box.sizeHint().height()
        )

        # Genre-Auswahl und Nummerierung nebeneinander
        self.genre_numbering_splitter = QSplitter(
            Qt.Orientation.Horizontal, self
        )
        self.genre_numbering_splitter.addWidget(self.genre_box)
        self.genre_numbering_splitter.addWidget(self.numbering_box)
        self.genre_numbering_splitter.setStretchFactor(0, 1)
        self.genre_numbering_splitter.setStretchFactor(1, 1)

        # --- Protokollfenster ---
        self.log_view = QTextEdit(self)
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(60)
        self.log_view.setPlaceholderText(
            "Start, Erfolg und Fehlschlag ausgeführter Scripte und Aktionen …"
        )
        self.log_box = QGroupBox("Protokoll", self)
        log_layout = QVBoxLayout(self.log_box)
        log_layout.addWidget(self.log_view)

        # Vertikaler Splitter zwischen Listen, Genre-Auswahl/Nummerierung
        # und Protokoll: Die Höhe des Protokollfensters lässt sich mit der
        # Maus frei verstellen, ohne dass einer der Bereiche ganz
        # verschwindet. Überschüssiger Platz beim Vergrößern des
        # Fensters geht ausschließlich ans Protokoll (Stretch 1);
        # Listenbereich und Genre/Nummerierung (Stretch 0) werden über
        # ihre Höchsthöhen ohnehin kompakt gehalten.
        main_splitter = QSplitter(Qt.Orientation.Vertical, self)
        main_splitter.addWidget(self._lists_splitter)
        main_splitter.addWidget(self.genre_numbering_splitter)
        main_splitter.addWidget(self.log_box)
        main_splitter.setStretchFactor(0, 0)
        main_splitter.setStretchFactor(1, 0)
        main_splitter.setStretchFactor(2, 1)
        main_splitter.setCollapsible(0, False)
        main_splitter.setCollapsible(1, False)
        main_splitter.setCollapsible(2, False)
        main_splitter.setSizes([520, 100, 140])

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
        self.overwrite_genres_button.clicked.connect(self._overwrite_genres)
        self.append_genre_button.clicked.connect(self._append_genre)
        self.renumber_button.clicked.connect(self._renumber_tracks)
        self.mix_button.clicked.connect(self._renumber_tracks_mixed)
        self.genre_combo.currentIndexChanged.connect(
            lambda *_: self._update_genre_buttons()
        )
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

        # --- Live-Aktualisierung bei Optionsänderungen ---
        # Die Plugin-Konfiguration ist ein QObject und sendet setting_changed,
        # sobald ein Wert geschrieben wird — auch aus dem Optionsdialog.
        try:
            self.api.plugin_config.setting_changed.connect(
                self._on_plugin_setting_changed
            )
        except Exception:
            # Signal nicht verfügbar: Einstellungen greifen dann über den
            # regulären Aktualisierungs-Pfad (refresh() wendet sie an).
            pass

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
        """Anzeige-Einstellungen aus den Plugin-Optionen anwenden.

        Steuert die Sichtbarkeit der Bereichs-Boxen (Scripte, Aktionen,
        Protokoll) und den Zeilenabstand. Läuft bei jeder Aktualisierung
        (Öffnen, Toolbar-Klick, „Aktualisieren“) sowie live beim Ändern
        der Optionen über das setting_changed-Signal der
        Plugin-Konfiguration.
        """
        spacing = _config_value(self.api.plugin_config, "list_row_spacing", 6)
        self.script_list.setItemDelegate(
            ListItemSpacingDelegate(self.script_list, spacing)
        )
        self.action_list.setItemDelegate(
            ListItemSpacingDelegate(self.action_list, spacing)
        )
        self.scripts_box.setVisible(
            _config_value(self.api.plugin_config, "show_scripts_list", True)
        )
        self.actions_box.setVisible(
            _config_value(self.api.plugin_config, "show_actions_list", True)
        )
        self.log_box.setVisible(
            _config_value(self.api.plugin_config, "show_log", True)
        )
        self.genre_box.setVisible(
            _config_value(self.api.plugin_config, "show_genre", True)
        )
        self.numbering_box.setVisible(
            _config_value(self.api.plugin_config, "show_numbering", True)
        )

    def _on_plugin_setting_changed(self, name, old_value, new_value):
        """Live-Reaktion auf Optionsänderungen (z. B. im Optionsdialog)."""
        if name in (
            "show_scripts_list",
            "show_actions_list",
            "show_log",
            "show_genre",
            "show_numbering",
            "genre_list",
            "list_row_spacing",
            "show_disabled_scripts",
        ):
            self.refresh()

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

    def _adjust_list_heights(self):
        """Beide Listen maximal so hoch wie ihr Inhalt — und der gesamte
        Listenbereich (Boxen inkl. Titel und Fußzeilen) ebenfalls.

        Die gemeinsame Höhe orientiert sich an der größeren der beiden
        Listen: Der letzte Eintrag des größeren Fensters begrenzt beide
        Boxen — unterhalb der Einträge bleibt kein leerer Raum, die
        Elemente verteilen sich also nicht beim Vergrößern des Fensters.
        Der Listenbereich bekommt dafür eine Höchsthöhe (Größen-Schätzung
        der größeren Box, getragen von CompactListWidget.sizeHint()),
        sodass ihm der vertikale Splitter keinen Leerraum zuweisen kann;
        überschüssiger Platz fällt dem Protokoll zu. Läuft nach jedem
        Listen-Neuaufbau, also auch nach Options-Änderungen, da
        sizeHintForRow() den Zeilenabstand des Delegates berücksichtigt.
        """
        heights = []
        for list_widget in (self.script_list, self.action_list):
            count = list_widget.count()
            if count == 0:
                heights.append(list_widget.sizeHintForRow(0))
            else:
                heights.append(
                    sum(list_widget.sizeHintForRow(i) for i in range(count))
                )
        content_height = max(heights)
        for list_widget in (self.script_list, self.action_list):
            list_widget.setMaximumHeight(
                content_height + 2 * list_widget.frameWidth()
            )
        # Benötigte Höhe des Listenbereichs: die größere der beiden
        # Boxen (inkl. Titel, Ränder, Fußzeile) begrenzt den Splitter.
        self._lists_splitter.setMaximumHeight(
            max(
                self.scripts_box.sizeHint().height(),
                self.actions_box.sizeHint().height(),
            )
        )

    def refresh(self):
        """Vollständige Aktualisierung: Einstellungen, Listen, Statuszeile."""
        self._apply_display_settings()
        objs = self._selected_objects()
        self._last_selection_signature = self._selection_signature(objs)
        self._needed_points = set()
        for obj in objs:
            self._needed_points.update(_points_for_object(obj))
        num_scripts = self._populate_scripts()
        num_actions = self._populate_actions(objs)
        self._populate_genre_combo()
        # Nummerierung nur bei Album-Auswahl anbieten
        album_selected = any(isinstance(obj, Album) for obj in objs)
        self.renumber_button.setEnabled(album_selected)
        self.mix_button.setEnabled(album_selected)
        self._adjust_list_heights()
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

    def _apply_to_metadata(self, objs, apply_func):
        """apply_func(parser, metadata) auf alle Metadaten der Auswahl
        anwenden.

        Folgt dem Muster aus Album._finalize_loading_album: pro Aufruf
        ein frischer ScriptParser, Auswertung gegen die Track- bzw.
        Album-Metadaten, danach UI-Update über obj.update(). Gibt
        (geänderte Metadaten, fehlgeschlagene Anwendungen) zurück.
        """
        parser = ScriptParser()
        changed = 0
        failed = 0
        for obj in objs:
            count = 0
            if isinstance(obj, Album):
                for track in obj.tracks:
                    if apply_func(parser, track.metadata):
                        count += 1
                        self._sync_track_files(track)
                    else:
                        failed += 1
                if apply_func(parser, obj.metadata):
                    count += 1
                else:
                    failed += 1
            elif isinstance(obj, Track):
                if apply_func(parser, obj.metadata):
                    count += 1
                    self._sync_track_files(obj)
                else:
                    failed += 1
            elif isinstance(obj, File):
                if apply_func(parser, obj.metadata):
                    count += 1
                else:
                    failed += 1
            elif isinstance(obj, Cluster):
                for file in obj.files:
                    if apply_func(parser, file.metadata):
                        count += 1
                    else:
                        failed += 1
            else:
                # Fallback für sonstige Objekte mit Metadaten (z. B. NATs)
                metadata = getattr(obj, "metadata", None)
                if metadata is not None:
                    if apply_func(parser, metadata):
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

    def _sync_track_files(self, track):
        """Manuelle Track-Änderungen in die gematchten Dateien übertragen.

        Picard verwaltet die „neuen“ Metadaten einer Datei separat von
        den Track-Metadaten: Manuelle Änderungen an track.metadata
        erscheinen zwar in der Albensicht, erreichen die Datei aber nur
        über Track.update_file_metadata() — derselbe Weg, den Picard
        selbst beim Matchen einer Datei geht (dort laufen die Scripte
        erneut und der manuelle Diff track.metadata vs.
        scripted_metadata wird angewendet; gegen Picard 3.0.2
        verifiziert). Ohne diesen Schritt zeigt das Datei-Detail die
        Änderung nicht und Speichern schreibt sie nicht.
        """
        for file in list(getattr(track, "files", None) or []):
            try:
                track.update_file_metadata(file)
            except Exception:
                self.api.logger.exception(
                    "Synchronisieren der Datei-Metadaten fehlgeschlagen "
                    "für Track %r, Datei %r",
                    track,
                    file,
                )

    def _apply_script(self, script, objs):
        """Script auf die ausgewählten Objekte anwenden."""
        return self._apply_to_metadata(
            objs,
            lambda parser, metadata: self._eval_script(parser, script, metadata),
        )

    # ------------------------------------------------------------------
    # Ausführen: Genre

    def _populate_genre_combo(self):
        """Dropdown aus der Option „genre_list“ füllen: eine Zeile pro
        Genre, leere Zeilen werden übersprungen. Ohne Auswahl zeigt das
        Feld nur den Platzhalter; eine bereits gewählte Genre bleibt
        über Aktualisierungen hinweg erhalten (damit mehrere Auswahl-
        Wechsel im Hauptfenster mit derselben Genre bearbeitet werden
        können).
        """
        previous = self.genre_combo.currentText().strip()
        text = _config_value(self.api.plugin_config, "genre_list", "")
        if not isinstance(text, str):
            text = ""
        genres = [line.strip() for line in text.splitlines() if line.strip()]
        self.genre_combo.clear()
        self.genre_combo.addItems(genres)
        if previous:
            index = self.genre_combo.findText(previous)
            if index >= 0:
                self.genre_combo.setCurrentIndex(index)
                return
        self.genre_combo.setCurrentIndex(-1)

    def _update_genre_buttons(self):
        """Beide Genre-Schaltflächen nur bei gewählter Genre freigeben."""
        selected = bool(self.genre_combo.currentText().strip())
        self.overwrite_genres_button.setEnabled(selected)
        self.append_genre_button.setEnabled(selected)

    def _set_genre(self, metadata, genre, append):
        """Genre-Tag überschreiben (append=False: vorhandene Genre-Werte
        werden ersetzt) bzw. gewählte Genre anhängen (append=True, ohne
        Dubletten). True, wenn die Metadaten geändert wurden."""
        try:
            if append:
                if genre in metadata.getall("genre"):
                    return False
                metadata.add_unique("genre", genre)
            else:
                if metadata.getall("genre") == [genre]:
                    return False
                metadata["genre"] = genre
            metadata.strip_whitespace()
            return True
        except Exception:
            self.api.logger.exception(
                "Fehler beim Setzen des Genres „%s“", genre
            )
            return False

    def _apply_genre(self, genre, append):
        """Gewählte Genre per Schaltfläche auf die Auswahl anwenden."""
        genre = (genre or "").strip()
        if not genre:
            return
        objs = self._selected_objects()
        if not objs:
            self._log_result(
                False,
                "Keine Auswahl im Hauptfenster — bitte zuerst Objekte markieren.",
            )
            return
        self._log_message(
            "Genre „%s“ %s …"
            % (genre, "anhängen" if append else "überschreiben")
        )
        try:
            changed, failed = self._apply_to_metadata(
                objs,
                lambda parser, metadata: self._set_genre(
                    metadata, genre, append
                ),
            )
        except Exception:
            self.api.logger.exception(
                "Unerwarteter Fehler beim Setzen des Genres „%s“", genre
            )
            self._log_result(
                False,
                "Genre „%s“ — unerwarteter Fehler, Details im Picard-Log."
                % genre,
            )
            return
        if failed:
            self._log_result(
                False,
                "Genre „%s“ mit Fehlern %s: %d Metadaten geändert, %d Fehler — Details im Picard-Log."
                % (
                    genre,
                    "angehängt" if append else "überschrieben",
                    changed,
                    failed,
                ),
            )
        else:
            self._log_result(
                True,
                "Genre „%s“ %s: %d Metadaten aktualisiert."
                % (genre, "angehängt" if append else "überschrieben", changed),
            )

    def _overwrite_genres(self, _checked=False):
        """„Alle Genre überschreiben“: Die gewählte Genre ersetzt alle
        vorhandenen Genre-Werte der Auswahl."""
        self._apply_genre(self.genre_combo.currentText(), append=False)

    def _append_genre(self, _checked=False):
        """„Dieses Genre anhängen“: Die gewählte Genre wird an vorhandene
        Genre-Werte angehängt (ohne Dubletten)."""
        self._apply_genre(self.genre_combo.currentText(), append=True)

    # ------------------------------------------------------------------
    # Ausführen: Nummerierung

    def _renumber_tracks(self, _checked=False):
        """„Tracks neu nummerieren“: Pro Disc lückenlos, in der Track-
        Reihenfolge des Albums (Details siehe _renumber_selected_albums)."""
        self._renumber_selected_albums("neu", None)

    def _renumber_tracks_mixed(self, _checked=False):
        """„Tracks gemixt nummerieren“: Pro Disc zufällige Reihenfolge,
        ohne denselben Interpreten zweimal hintereinander (Details
        siehe _renumber_selected_albums und _shuffled_no_repeat)."""
        self._renumber_selected_albums(
            "gemischt neu", self._shuffled_no_repeat
        )

    def _track_artist(self, track):
        """Interpret eines Tracks aus den Track-Metadaten (leerer String
        als Fallback)."""
        try:
            return (track.metadata.get("artist") or "").strip()
        except Exception:
            return ""

    def _shuffled_no_repeat(self, tracks):
        """Zufällige Reihenfolge mit Interpreten-Abstand.

        Pro Schritt wird zufällig aus den noch übrigen Tracks gewählt,
        deren Interpret sich vom zuletzt gewählten unterscheidet. Ist
        das nicht möglich (z. B. alle Tracks vom selben Interpret),
        wird aus allen übrigen gewählt — die Nummerierung läuft so
        immer durch und hält die Regel, wo sie haltbar ist.
        """
        remaining = list(tracks)
        result = []
        last_artist = None
        while remaining:
            different = [
                track
                for track in remaining
                if self._track_artist(track) != last_artist
            ]
            pool = different or remaining
            pick = random.choice(pool)
            remaining.remove(pick)
            result.append(pick)
            last_artist = self._track_artist(pick)
        return result

    def _renumber_selected_albums(self, label, order_func):
        """Gemeinsamer Kern beider Nummerierungs-Schaltflächen: Nur für
        Album-Auswahl.

        Pro Disc (Gruppierung nach discnumber der Track-Metadaten,
        Voreinstellung „1“) werden die Tracks mit gematchter Datei
        nummeriert (1, 2, 3, …) — order_func bestimmt die Reihenfolge
        (None = Track-Reihenfolge des Albums, _shuffled_no_repeat =
        zufällig mit Interpreten-Abstand); Tracks ohne Datei bleiben
        komplett unberührt. totaltracks erhält die Anzahl der Tracks
        mit Datei der jeweiligen Disc. Die Änderungen laufen über
        track.metadata und werden über Track.update_file_metadata()
        (siehe _sync_track_files) in die gematchten Dateien übertragen
        — sichtbar im Datei-Detail (Spalte „Neu“) und mit „Speichern“
        in die Dateien geschrieben.
        """
        objs = self._selected_objects()
        albums = [obj for obj in objs if isinstance(obj, Album)]
        if not albums:
            self._log_result(
                False,
                "Nummerierung braucht eine Album-Auswahl im "
                "Hauptfenster — bitte zuerst ein Album markieren.",
            )
            return
        self._log_message(
            "Nummeriere %d Album(x) %s (nur Tracks mit vorhandener "
            "Datei) …" % (len(albums), label)
        )
        changed = 0
        skipped = 0
        try:
            for album in albums:
                # Tracks in Album-Reihenfolge nach Disc gruppieren.
                # discnumber als Gruppenschlüssel (Rohwert der
                # Metadaten, z. B. „1“ oder „2/3“); ohne Discnumber
                # zählen alle Tracks zu Disc „1“.
                disc_groups = {}
                disc_order = []
                for track in album.tracks:
                    disc = str(
                        track.metadata.get("discnumber", "1") or "1"
                    )
                    if disc not in disc_groups:
                        disc_groups[disc] = []
                        disc_order.append(disc)
                    disc_groups[disc].append(track)
                for disc in disc_order:
                    available = [
                        track
                        for track in disc_groups[disc]
                        if getattr(track, "files", None)
                    ]
                    ordered = (
                        order_func(available) if order_func else available
                    )
                    total = len(ordered)
                    for position, track in enumerate(ordered, start=1):
                        track.metadata["tracknumber"] = str(position)
                        track.metadata["totaltracks"] = str(total)
                        self._sync_track_files(track)
                    skipped += len(disc_groups[disc]) - total
                    changed += total
                update = getattr(album, "update", None)
                if callable(update):
                    try:
                        update()
                    except Exception:
                        self.api.logger.exception(
                            "UI-Update für %r fehlgeschlagen", album
                        )
        except Exception:
            self.api.logger.exception(
                "Unerwarteter Fehler bei der Nummerierung"
            )
            self._log_result(
                False,
                "Nummerierung — unerwarteter Fehler, Details im "
                "Picard-Log.",
            )
            return
        if changed:
            self._log_result(
                True,
                "Nummerierung: %d Track(s) mit Datei %s nummeriert, "
                "%d Track(s) ohne Datei übersprungen."
                % (changed, label, skipped),
            )
        else:
            self._log_result(
                False,
                "Nummerierung: keine Tracks mit vorhandener Datei "
                "gefunden.",
            )

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
        self.refresh()
        if self._use_poll_timer and not self._poll_timer.isActive():
            self._poll_timer.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        if self._poll_timer.isActive():
            self._poll_timer.stop()