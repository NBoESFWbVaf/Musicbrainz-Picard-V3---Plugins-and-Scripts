# -*- coding: utf-8 -*-
#
# Display Coverinformation — Plugin for MusicBrainz Picard 3
#
# Displays information about the cover art images (dimensions as
# height x width, file size, file type) directly below the preview
# images in the cover art panel of the main window — firmly embedded
# in the interface, not as a separate window.
#
# The information is displayed:
# - for the new cover art image (e.g. to be loaded from the internet)
# - for the original cover art image embedded in the file
# - for multiple images additionally in a table listing all images
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

# Central plugin state, so disable() can clean everything up again.
_state = {}


def _human_size(size):
    """Format a byte count in human-readable form (decimal, English number format)."""
    size = float(size)
    for unit in ('B', 'kB', 'MB', 'GB'):
        if size < 1000.0 or unit == 'GB':
            if unit == 'B':
                return '%d B' % int(size)
            return '%.1f %s' % (size, unit)
        size /= 1000.0
    # never reached ('GB' covers everything)


def _file_type(image):
    """Determine the file extension (e.g. 'JPG') as the file type."""
    extension = (getattr(image, 'extension', None) or '').lstrip('.').upper()
    mimetype = getattr(image, 'mimetype', None) or ''
    if not extension and mimetype:
        extension = mimetype.split('/')[-1].upper()
    return extension or mimetype or '-'


def _dimensions_text(api, image):
    """Image dimensions as 'height x width Pixels'."""
    width = getattr(image, 'width', None)
    height = getattr(image, 'height', None)
    if width and height:
        return api.tr('dimensions_value', '{height} x {width} Pixels',
                      height=height, width=width)
    return api.tr('value_unknown', 'unknown')


def _dimensions_short(api, image):
    """Image dimensions compact as 'height x width' (for table cells)."""
    width = getattr(image, 'width', None)
    height = getattr(image, 'height', None)
    if width and height:
        return api.tr('dimensions_short', '{height} x {width}',
                      height=height, width=width)
    return api.tr('value_unknown', 'unknown')


def _filesize_text(api, image):
    """File size, formatted in human-readable form."""
    datalength = getattr(image, 'datalength', None)
    if datalength:
        return _human_size(datalength)
    return api.tr('value_unknown', 'unknown')


class CoverInfoWidget(QtWidgets.QWidget):
    """Cover art image information for a preview image, embedded directly below it.

    Shows the three info lines (dimensions, file size, file type) of the
    first image and, if there are multiple images, additionally a table
    with the values of all images.
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
            api.tr('col_dimensions', 'Dimensions'),
            api.tr('col_filesize', 'Size'),
            api.tr('col_filetype', 'Type'),
        ])
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.NoSelection)
        self.table.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.table.setWordWrap(False)
        layout.addWidget(self.table)

        self.setVisible(False)

    def update_info(self, images, visible=True):
        """Update the display based on the CoverArtImage objects of a thumbnail."""
        if not visible or not images:
            self.setVisible(False)
            return

        api = self._api
        image = images[0]

        self.dimensions_label.setText(
            api.tr('dimensions_line', 'Dimensions: {dimensions}',
                   dimensions=_dimensions_text(api, image)))
        self.filesize_label.setText(
            api.tr('filesize_line', 'Size: {filesize}',
                   filesize=_filesize_text(api, image)))
        self.filetype_label.setText(
            api.tr('filetype_line', 'Type: {filetype}', filetype=_file_type(image)))

        # With multiple images, list all values in a table
        if len(images) > 1:
            self._fill_table(api, images)
            self.table.setVisible(True)
        else:
            self.table.setRowCount(0)
            self.table.setVisible(False)

        self.setVisible(True)

    def _fill_table(self, api, images):
        """Fill the table with the values of all images."""
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
    """Update both info widgets based on the current cover art thumbnails."""
    widgets = _state.get('widgets')
    if not widgets:
        return
    try:
        new_images = getattr(box.cover_art, 'data', None) or []
        orig_images = getattr(box.orig_cover_art, 'data', None) or []
        # Only show the original information if the cover art panel is
        # also showing the original preview image.
        orig_visible = box.orig_cover_art.isVisible() and bool(orig_images)
        widgets['new'].update_info(new_images, visible=bool(new_images))
        widgets['orig'].update_info(orig_images, visible=orig_visible)
    except Exception:
        for widget in widgets.values():
            try:
                widget.setVisible(False)
            except RuntimeError:
                # Widget was already deleted (e.g. after re-enabling)
                pass


def _insert_after(box_layout, anchor, widget):
    """Insert a widget directly below an anchor widget into the layout.

    If the anchor is not contained in the layout (e.g. a differing Picard
    version), the widget is inserted before the trailing spacer at the end.
    """
    index = box_layout.indexOf(anchor)
    if index < 0:
        index = box_layout.count() - 1
    box_layout.insertWidget(index + 1, widget)


def enable(api: PluginApi):
    """Enable the plugin: insert the info widgets below the preview images."""
    # If any remains of a previous enable() call are still present (e.g.
    # after re-enabling without a restart), clean them up first.
    if _state:
        disable()

    box = getattr(api.tagger.window, 'cover_art_box', None)
    if box is None:
        api.logger.error('%s: Cover art panel not found, plugin will not be enabled.',
                         PLUGIN_NAME)
        return

    from picard.ui.coverartbox import CoverArtBox

    widgets = {
        # New cover art image (e.g. loaded from the internet), without heading
        'new': CoverInfoWidget(api, parent=box),
        # Original cover art image from the file (local), with a short label
        'orig': CoverInfoWidget(
            api, caption=api.tr('caption_orig', 'Original:'), parent=box),
    }

    # Insert directly below the respective preview images into the cover
    # art panel (not a separate window). The built-in info labels serve as
    # anchors if present; otherwise the preview images themselves.
    new_anchor = getattr(box, 'cover_art_info_label', None) or box.cover_art
    orig_anchor = getattr(box, 'orig_cover_art_info_label', None) or box.orig_cover_art
    _insert_after(box.layout, new_anchor, widgets['new'])
    _insert_after(box.layout, orig_anchor, widgets['orig'])

    # update_display() is the central refresh point of the cover art panel
    # (selection changes, new cover art, saved images). Hook in there:
    original_update_display = CoverArtBox.update_display

    def update_display_with_info(self, force=False):
        original_update_display(self, force)
        _refresh_info(self)

    CoverArtBox.update_display = update_display_with_info

    _state['box'] = box
    _state['widgets'] = widgets
    _state['original_update_display'] = original_update_display
    _state['patched_update_display'] = update_display_with_info

    # First update for the current selection
    _refresh_info(box)
    api.logger.info('%s: Cover art image information is displayed below the preview images.',
                    PLUGIN_NAME)


def disable():
    """Disable the plugin: remove the widgets and revert the patch."""
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