# -*- coding: utf-8 -*-
#
# Display Coverinformation — Plugin für MusicBrainz Picard 3
#
# Zeigt Informationen zum aktuell angezeigten Coverbild
# (Bildmaße in Höhe x Breite, Dateigröße, Dateityp)
# direkt unterhalb des Coverbildes in der Cover-Spalte
# des Hauptfensters an.
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
    """Bestimmt eine lesbare Dateityp-Bezeichnung aus Erweiterung und MIME-Typ."""
    extension = (getattr(image, 'extension', None) or '').lstrip('.').upper()
    mimetype = getattr(image, 'mimetype', None) or ''
    if not extension and mimetype:
        extension = mimetype.split('/')[-1].upper()
    if extension and mimetype:
        return '%s (%s)' % (extension, mimetype)
    return extension or mimetype or '-'


class CoverInfoWidget(QtWidgets.QWidget):
    """Zeigt die Bildinformationen in drei untereinanderliegenden Labels."""

    def __init__(self, api, parent=None):
        super().__init__(parent)
        self._api = api
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(2, 0, 2, 0)
        layout.setSpacing(0)
        self.dimensions_label = QtWidgets.QLabel('', self)
        self.filesize_label = QtWidgets.QLabel('', self)
        self.filetype_label = QtWidgets.QLabel('', self)
        self.count_label = QtWidgets.QLabel('', self)
        for label in (self.dimensions_label, self.filesize_label,
                      self.filetype_label, self.count_label):
            label.setAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter)
            label.setWordWrap(True)
            layout.addWidget(label)
        self.setVisible(False)

    def update_info(self, images):
        """Aktualisiert die Labels anhand der angezeigten CoverArtImage-Objekte."""
        if not images:
            self.setVisible(False)
            return

        api = self._api
        image = images[0]

        # Bildmaße (Höhe x Breite in Pixel)
        width = getattr(image, 'width', None)
        height = getattr(image, 'height', None)
        if width and height:
            dimensions = api.tr('dimensions_value', '{height} x {width} Pixel',
                                height=height, width=width)
        else:
            dimensions = api.tr('value_unknown', 'unbekannt')
        self.dimensions_label.setText(
            api.tr('dimensions_line', 'Bildmaße: {dimensions}', dimensions=dimensions))

        # Dateigröße
        datalength = getattr(image, 'datalength', None)
        if datalength:
            filesize = _human_size(datalength)
        else:
            filesize = api.tr('value_unknown', 'unbekannt')
        self.filesize_label.setText(
            api.tr('filesize_line', 'Dateigröße: {filesize}', filesize=filesize))

        # Dateityp
        self.filetype_label.setText(
            api.tr('filetype_line', 'Dateityp: {filetype}', filetype=_file_type(image)))

        # Hinweis bei mehreren angezeigten Coverbildern (Cover-Stapel)
        if len(images) > 1:
            self.count_label.setText(
                api.tr('image_count', '{index} von {count} Bildern',
                       index=1, count=len(images)))
        else:
            self.count_label.setText('')

        self.setVisible(True)


def _refresh_info(box):
    """Liest die aktuell angezeigten Bilder aus dem Cover-Thumbnail und aktualisiert das Widget."""
    widget = _state.get('widget')
    if widget is None:
        return
    images = getattr(box.cover_art, 'data', None) or []
    try:
        widget.update_info(images)
    except Exception:
        widget.setVisible(False)


def enable(api: PluginApi):
    """Plugin aktivieren: Info-Widget unterhalb des Coverbildes einfügen."""
    box = getattr(api.tagger.window, 'cover_art_box', None)
    if box is None:
        api.logger.error('%s: Cover-Spalte nicht gefunden, Plugin wird nicht aktiviert.',
                         PLUGIN_NAME)
        return

    from picard.ui.coverartbox import CoverArtBox

    widget = CoverInfoWidget(api, parent=box)
    # Direkt unter das Coverbild einfügen
    index = box.layout.indexOf(box.cover_art) + 1
    box.layout.insertWidget(index, widget)

    # update_display() ist der zentrale Aktualisierungspunkt der Cover-Spalte
    # (Auswahlwechsel, neue Coverbilder, gespeicherte Bilder). Dort einklinken:
    original_update_display = CoverArtBox.update_display

    def update_display_with_info(self, force=False):
        original_update_display(self, force)
        _refresh_info(self)

    CoverArtBox.update_display = update_display_with_info

    _state['box'] = box
    _state['widget'] = widget
    _state['original_update_display'] = original_update_display
    _state['patched_update_display'] = update_display_with_info

    # Erste Aktualisierung für die aktuelle Auswahl
    _refresh_info(box)
    api.logger.info('%s: Bildinformationen werden unterhalb des Coverbildes angezeigt.',
                    PLUGIN_NAME)


def disable():
    """Plugin deaktivieren: Widget entfernen und Patch zurücknehmen."""
    from picard.ui.coverartbox import CoverArtBox

    patched = _state.get('patched_update_display')
    original = _state.get('original_update_display')
    if patched and original and CoverArtBox.update_display is patched:
        CoverArtBox.update_display = original

    box = _state.get('box')
    widget = _state.get('widget')
    if box is not None and widget is not None:
        box.layout.removeWidget(widget)
        widget.deleteLater()

    _state.clear()