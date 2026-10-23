# -*- coding: utf-8 -*-
#
# Display Coverinformation — Plugin für MusicBrainz Picard 3
#
# Zeigt Informationen zu den Coverbildern (Bildmaße in Höhe x Breite,
# Dateigröße, Dateityp) direkt unterhalb der Vorschaubilder in der
# Cover-Spalte des Hauptfensters an — fest in die Oberfläche eingebettet,
# nicht als eigenes Fenster.
#
# Angezeigt werden die Informationen:
# - für das neue Coverbild (z. B. das aus dem Internet zu ladende)
# - für das in der Datei bereits vorhandene Original-Coverbild
# - bei mehreren Bildern zusätzlich tabellarisch für alle Bilder
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
# See <https://www.gnu.org/licenses/gpl-2.0.html>.

from PyQt6 import (
    QtCore,
    QtWidgets,
)

from picard.plugin3.api import PluginApi

PLUGIN_NAME = 'Display Coverinformation'

# Zentraler Zustand des Plugins, damit disable() alles wieder aufräumen kann.
_state = {}


def _human_size(size):
    """Formatiert eine Byte-Anzahl lesbar (dezimal, deutsches Zahlenformat)."""
    size = float(size)
    for unit in ('B', 'kB', 'MB', 'GB'):
        if size < 1000.0 or unit == 'GB':
            if unit == 'B':
                return '%d B' % int(size)
            return ('%.1f %s' % (size, unit)).replace('.', ',')
        size /= 1000.0
    # wird nie erreicht ('GB' deckt alles ab)


def _file_type(image):
    """Bestimmt die Dateiendung (z. B. 'JPG') als Dateityp-Angabe."""
    extension = (getattr(image, 'extension', None) or '').lstrip('.').upper()
    mimetype = getattr(image, 'mimetype', None) or ''
    if not extension and mimetype:
        extension = mimetype.split('/')[-1].upper()
    return extension or mimetype or '-'


def _dimensions_text(api, image):
    """Bildmaße als 'Höhe x Breite Pixel'."""
    width = getattr(image, 'width', None)
    height = getattr(image, 'height', None)
    if width and height:
        return api.tr('dimensions_value', '{height} x {width} Pixel',
                      height=height, width=width)
    return api.tr('value_unknown', 'unbekannt')


def _dimensions_short(api, image):
    """Bildmaße kompakt als 'Höhe x Breite' (für Tabellenzellen)."""
    width = getattr(image, 'width', None)
    height = getattr(image, 'height', None)
    if width and height:
        return api.tr('dimensions_short', '{height} x {width}',
                      height=height, width=width)
    return api.tr('value_unknown', 'unbekannt')


def _filesize_text(api, image):
    """Dateigröße, lesbar formatiert."""
    datalength = getattr(image, 'datalength', None)
    if datalength:
        return _human_size(datalength)
    return api.tr('value_unknown', 'unbekannt')


class CoverInfoWidget(QtWidgets.QWidget):
    """Bildinformationen zu einem Vorschaubild, direkt darunter eingebettet.

    Zeigt die drei Info-Zeilen (Bildmaße, Dateigröße, Dateityp) des ersten
    Bildes und bei mehreren Bildern zusätzlich eine Tabelle mit den Werten
    aller Bilder.
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
            api.tr('col_dimensions', 'Maße'),
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
        """Aktualisiert die Anzeige anhand der CoverArtImage-Objekte eines Thumbnails."""
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

        # Bei mehreren Bildern alle Werte tabellarisch auflisten
        if len(images) > 1:
            self._fill_table(api, images)
            self.table.setVisible(True)
        else:
            self.table.setRowCount(0)
            self.table.setVisible(False)

        self.setVisible(True)

    def _fill_table(self, api, images):
        """Füllt die Tabelle mit den Werten aller Bilder."""
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
    """Aktualisiert beide Info-Widgets anhand der aktuellen Cover-Thumbnails."""
    widgets = _state.get('widgets')
    if not widgets:
        return
    try:
        new_images = getattr(box.cover_art, 'data', None) or []
        orig_images = getattr(box.orig_cover_art, 'data', None) or []
        # Die Original-Anzeige nur einblenden, wenn die Cover-Spalte auch
        # das Original-Vorschaubild anzeigt.
        orig_visible = box.orig_cover_art.isVisible() and bool(orig_images)
        widgets['new'].update_info(new_images, visible=bool(new_images))
        widgets['orig'].update_info(orig_images, visible=orig_visible)
    except Exception:
        for widget in widgets.values():
            widget.setVisible(False)


def enable(api: PluginApi):
    """Plugin aktivieren: Info-Widgets unterhalb der Vorschaubilder einfügen."""
    box = getattr(api.tagger.window, 'cover_art_box', None)
    if box is None:
        api.logger.error('%s: Cover-Spalte nicht gefunden, Plugin wird nicht aktiviert.',
                         PLUGIN_NAME)
        return

    from picard.ui.coverartbox import CoverArtBox

    widgets = {
        # Neues Coverbild (z. B. aus dem Internet geladen), ohne Überschrift
        'new': CoverInfoWidget(api, parent=box),
        # Original-Coverbild aus der Datei (lokal), mit kurzer Kennzeichnung
        'orig': CoverInfoWidget(
            api, caption=api.tr('caption_orig', 'Original:'), parent=box),
    }

    # Direkt unterhalb der jeweiligen Vorschaubilder in die Cover-Spalte
    # einfügen (kein eigenes Fenster).
    box.layout.insertWidget(box.layout.indexOf(box.cover_art_info_label) + 1, widgets['new'])
    box.layout.insertWidget(box.layout.indexOf(box.orig_cover_art_info_label) + 1, widgets['orig'])

    # update_display() ist der zentrale Aktualisierungspunkt der Cover-Spalte
    # (Auswahlwechsel, neue Coverbilder, gespeicherte Bilder). Dort einklinken:
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
    api.logger.info('%s: Bildinformationen werden unterhalb der Vorschaubilder angezeigt.',
                    PLUGIN_NAME)


def disable():
    """Plugin deaktivieren: Widgets entfernen und Patch zurücknehmen."""
    from picard.ui.coverartbox import CoverArtBox

    patched = _state.get('patched_update_display')
    original = _state.get('original_update_display')
    if patched and original and CoverArtBox.update_display is patched:
        CoverArtBox.update_display = original

    box = _state.get('box')
    widgets = _state.get('widgets') or {}
    if box is not None:
        for widget in widgets.values():
            box.layout.removeWidget(widget)
            widget.deleteLater()

    _state.clear()