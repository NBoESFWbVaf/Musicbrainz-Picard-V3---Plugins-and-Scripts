"""Cover-Informationen im Cover-Panel des Hauptfensters anzeigen.

Zeigt Informationen zu den Cover-Bildern (Maße als HöhexBreite,
Dateigröße, Dateityp) direkt unter den Vorschaubildern im Cover-Panel
des Hauptfensters an — fest in die Oberfläche eingebettet, nicht als
eigenes Fenster.

Angezeigt werden die Informationen:
- für das neue Cover-Bild (z. B. aus dem Internet zu laden)
- für das im Datei-Container eingebettete Original-Cover
- bei mehreren Bildern zusätzlich als Tabelle mit allen Bildern

Übernommen aus dem eigenständigen Plugin „Display Coverinformation“
(lizenziert unter GPL-2-or-later, daher in dieses GPL-3.0-or-later-
Projekt übernehmbar) und an die Struktur dieses Plugins angepasst.
Die benutzten Picard-Internals (CoverArtBox-Anker, update_display,
to_main, api.tr) sind gegen Picard 3.0.2 verifiziert.
"""

import threading

from PyQt6 import (
    QtCore,
    QtWidgets,
)

from picard.util.thread import to_main

# Name für Log-Meldungen dieses Moduls.
_PLUGIN_NAME = "Picard Extender"

# Zentraler Modul-Zustand, damit disable_cover_info() wieder alles
# aufräumen kann.
_state = {}


def _human_size(size):
    """Byte-Anzahl menschenlesbar formatieren (dezimal)."""
    size = float(size)
    for unit in ('B', 'kB', 'MB', 'GB'):
        if size < 1000.0 or unit == 'GB':
            if unit == 'B':
                return '%d B' % int(size)
            return '%.1f %s' % (size, unit)
        size /= 1000.0
    # Wird nie erreicht ('GB' deckt alles ab)


def _file_type(image):
    """Dateiendung (z. B. 'JPG') als Dateityp ermitteln."""
    extension = (getattr(image, 'extension', None) or '').lstrip('.').upper()
    mimetype = getattr(image, 'mimetype', None) or ''
    if not extension and mimetype:
        extension = mimetype.split('/')[-1].upper()
    return extension or mimetype or '-'


def _dimensions_text(api, image):
    """Bildmaße als 'HöhexBreite px'."""
    width = getattr(image, 'width', None)
    height = getattr(image, 'height', None)
    if width and height:
        return api.tr('dimensions_value', '{height}x{width} px',
                      height=height, width=width)
    return api.tr('value_unknown', 'unbekannt')


def _dimensions_short(api, image):
    """Bildmaße kompakt als 'HöhexBreite' (für Tabellenzellen)."""
    width = getattr(image, 'width', None)
    height = getattr(image, 'height', None)
    if width and height:
        return api.tr('dimensions_short', '{height}x{width}',
                      height=height, width=width)
    return api.tr('value_unknown', 'unbekannt')


def _filesize_text(api, image):
    """Dateigröße, menschenlesbar formatiert."""
    datalength = getattr(image, 'datalength', None)
    if datalength:
        return _human_size(datalength)
    return api.tr('value_unknown', 'unbekannt')


class CoverInfoWidget(QtWidgets.QWidget):
    """Cover-Bildinformationen für ein Vorschaubild, direkt darunter
    eingebettet.

    Zeigt die drei Info-Zeilen (Maße, Dateigröße, Dateityp) des ersten
    Bildes und bei mehreren Bildern zusätzlich eine Tabelle mit den
    Werten aller Bilder.
    """

    def __init__(self, api, caption='', parent=None):
        super().__init__(parent)
        self._api = api
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(2, 0, 2, 0)
        layout.setSpacing(0)

        if caption:
            self.caption_label = QtWidgets.QLabel(caption, self)
            caption_font = self.caption_label.font()
            caption_font.setBold(True)
            self.caption_label.setFont(caption_font)
            layout.addWidget(self.caption_label)

        self.dimensions_label = QtWidgets.QLabel('', self)
        self.filesize_label = QtWidgets.QLabel('', self)
        self.filetype_label = QtWidgets.QLabel('', self)
        for label in (self.dimensions_label, self.filesize_label, self.filetype_label):
            label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
            label.setWordWrap(True)
            layout.addWidget(label)

        self.table = QtWidgets.QTableWidget(0, 3, self)
        self.table.setHorizontalHeaderLabels([
            api.tr('col_dimensions', 'HxW'),
            api.tr('col_filesize', 'Größe'),
            api.tr('col_filetype', 'Typ'),
        ])
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.NoSelection)
        self.table.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.table.setWordWrap(False)
        layout.addWidget(self.table)

        self.setVisible(False)

    def update_info(self, images, visible=True):
        """Anzeige anhand der CoverArtImage-Objekte eines Thumbnails
        aktualisieren."""
        if not visible or not images:
            self.setVisible(False)
            return

        api = self._api
        image = images[0]

        self.dimensions_label.setText(
            api.tr('dimensions_line', 'Maße: {dimensions}',
                   dimensions=_dimensions_text(api, image)))
        self.filesize_label.setText(
            api.tr('filesize_line', 'Größe: {filesize}',
                   filesize=_filesize_text(api, image)))
        self.filetype_label.setText(
            api.tr('filetype_line', 'Typ: {filetype}', filetype=_file_type(image)))

        # Bei mehreren Bildern alle Werte in einer Tabelle auflisten
        if len(images) > 1:
            self._fill_table(api, images)
            self.table.setVisible(True)
        else:
            self.table.setRowCount(0)
            self.table.setVisible(False)

        self.setVisible(True)

    def _fill_table(self, api, images):
        """Tabelle mit den Werten aller Bilder füllen."""
        self.table.setRowCount(len(images))
        for row, image in enumerate(images):
            values = (
                _dimensions_short(api, image),
                _filesize_text(api, image),
                _file_type(image),
            )
            for col, text in enumerate(values):
                item = QtWidgets.QTableWidgetItem(text)
                item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, col, item)
        self.table.resizeColumnsToContents()
        self.table.resizeRowsToContents()


def _refresh_info(box):
    """Beide Info-Widgets anhand der aktuellen Cover-Thumbnails
    aktualisieren."""
    widgets = _state.get('widgets')
    if not widgets:
        return
    try:
        new_images = getattr(box.cover_art, 'data', None) or []
        orig_images = getattr(box.orig_cover_art, 'data', None) or []
        # Die Original-Informationen nur zeigen, wenn das Cover-Panel
        # auch das Original-Vorschaubild anzeigt.
        orig_visible = box.orig_cover_art.isVisible() and bool(orig_images)
        widgets['new'].update_info(new_images, visible=bool(new_images))
        widgets['orig'].update_info(orig_images, visible=orig_visible)
    except Exception:
        for widget in widgets.values():
            try:
                widget.setVisible(False)
            except RuntimeError:
                # Widget war bereits gelöscht (z. B. nach Re-Aktivierung)
                pass


def _active_layout(widget):
    """Das wirklich aktive Layout eines Widgets zurückgeben.

    Robust gegen ein Python-Instanzattribut 'layout', das die QWidget-
    Methode layout() überschattet (CoverArtBox tut genau das) oder ein
    veraltetes, nicht aktiviertes Layout hält: Das aktive Layout wird
    immer über die ungebundene Qt-Methode erfragt, die ein
    Python-Attribut ignoriert.
    """
    layout = QtWidgets.QWidget.layout(widget)
    if layout is not None:
        return layout
    # Fallback für Randfälle: das Instanz-Attribut lesen
    attr = getattr(widget, 'layout', None)
    if attr is not None and not callable(attr):
        return attr
    return None


def _insert_after(box_layout, anchor, widget):
    """Ein Widget direkt unterhalb eines Anker-Widgets in das Layout
    einfügen.

    Ist der Anker nicht im Layout enthalten (z. B. abweichende Picard-
    Version), wird das Widget vor dem abschließenden Spacer am Ende
    eingefügt.
    """
    index = box_layout.indexOf(anchor)
    if index < 0:
        index = box_layout.count() - 1
    box_layout.insertWidget(index + 1, widget)


def enable_cover_info(api):
    """Aktivieren: Info-Widgets unter den Vorschaubildern einfügen.

    Picard installiert, aktualisiert und lädt Plugins asynchron in
    einem Hintergrund-Thread. Qt-Widgets dürfen aber nur im Haupt-
    (GUI-)Thread erzeugt und verwaltet werden, sonst erscheinen sie
    als eigene freischwebende Fenster. Wird enable() aus einem anderen
    Thread aufgerufen, wird der gesamte Aufbau in den Haupt-Thread
    verschoben.
    """
    if threading.current_thread() is not threading.main_thread():
        to_main(_enable_in_main, api)
    else:
        _enable_in_main(api)


def _enable_in_main(api):
    """Eigentlicher Aufbau, immer im Haupt-Thread."""
    # Sollten noch Reste eines früheren Aufrufs vorhanden sein (z. B.
    # nach Re-Aktivieren ohne Neustart), erst aufräumen.
    if _state:
        _disable_in_main()

    box = getattr(api.tagger.window, 'cover_art_box', None)
    if box is None:
        api.logger.error('%s: Cover-Panel nicht gefunden, Cover-Info wird nicht aktiviert.',
                         _PLUGIN_NAME)
        return

    from picard.ui.coverartbox import CoverArtBox

    widgets = {
        # Neues Cover-Bild (z. B. aus dem Internet zu laden), ohne Überschrift
        'new': CoverInfoWidget(api, parent=box),
        # Original-Cover aus der Datei (lokal), mit kurzer Beschriftung
        'orig': CoverInfoWidget(
            api, caption=api.tr('caption_orig', 'Original:'), parent=box),
    }

    # Direkt unter die jeweiligen Vorschaubilder in das Cover-Panel
    # einfügen (kein eigenes Fenster). Immer das wirklich aktive Layout
    # des Panels verwenden: Ein Widget in einem inaktiven Layout würde
    # als frei schwebendes Overlay gezeichnet und sähe aus wie ein
    # eigenes Fenster.
    layout = _active_layout(box)
    if layout is None:
        api.logger.error('%s: Cover-Panel hat kein Layout, Cover-Info wird nicht aktiviert.',
                         _PLUGIN_NAME)
        return

    # Die eingebauten Info-Labels dienen als Anker, falls vorhanden,
    # sonst die Vorschaubilder selbst.
    new_anchor = getattr(box, 'cover_art_info_label', None) or box.cover_art
    orig_anchor = getattr(box, 'orig_cover_art_info_label', None) or box.orig_cover_art
    _insert_after(layout, new_anchor, widgets['new'])
    _insert_after(layout, orig_anchor, widgets['orig'])

    # Plausibilitätsprüfung: Die Info-Widgets müssen eingebettete Kinder
    # des Cover-Panels sein, von dessen aktivem Layout verwaltet, und
    # niemals eigenständige Fenster. Andernfalls Warnung ins Picard-Log,
    # damit die Ursache diagnostizierbar ist.
    for name, widget in widgets.items():
        in_layout = layout.indexOf(widget) >= 0
        if widget.isWindow() or widget.parent() is not box or not in_layout:
            api.logger.warning(
                '%s: Das Info-Widget %s ist nicht in das Cover-Panel eingebettet '
                '(parent=%r, isWindow=%s, inActiveLayout=%s).',
                _PLUGIN_NAME, name, widget.parent(), widget.isWindow(), in_layout)

    # update_display() ist der zentrale Aktualisierungspunkt des Cover-
    # Panels (Auswahlwechsel, neue Cover, gespeicherte Bilder). Dort
    # einklinken:
    original_update_display = CoverArtBox.update_display

    def update_display_with_info(self, force=False):
        original_update_display(self, force)
        _refresh_info(self)

    CoverArtBox.update_display = update_display_with_info

    _state['box'] = box
    _state['widgets'] = widgets
    _state['original_update_display'] = original_update_display
    _state['patched_update_display'] = update_display_with_info

    # Erste Aktualisierung für die aktuelle Auswahl
    _refresh_info(box)
    api.logger.info('%s: Cover-Bildinformationen werden unter den Vorschaubildern angezeigt.',
                    _PLUGIN_NAME)


def disable_cover_info():
    """Deaktivieren: Widgets entfernen und Patch zurücknehmen.

    Wie enable_cover_info() kann auch dies aus einem Hintergrund-Thread
    aufgerufen werden (z. B. bei Update, Reload oder Deinstallation);
    das Aufräumen wird dann in den Haupt-Thread verschoben.
    """
    if threading.current_thread() is not threading.main_thread():
        to_main(_disable_in_main)
    else:
        _disable_in_main()


def _disable_in_main():
    """Eigentliches Aufräumen, immer im Haupt-Thread."""
    from picard.ui.coverartbox import CoverArtBox

    patched = _state.get('patched_update_display')
    original = _state.get('original_update_display')
    if patched and original and CoverArtBox.update_display is patched:
        CoverArtBox.update_display = original

    box = _state.get('box')
    widgets = _state.get('widgets') or {}
    if box is not None:
        layout = _active_layout(box)
        for widget in widgets.values():
            if layout is not None:
                layout.removeWidget(widget)
            widget.deleteLater()

    _state.clear()