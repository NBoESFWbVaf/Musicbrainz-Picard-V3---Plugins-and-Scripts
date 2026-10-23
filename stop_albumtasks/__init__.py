# -*- coding: utf-8 -*-
#
# Stop albumtasks - plugin for MusicBrainz Picard 3 (plugin API v3)
#
# Adds a "Stop albumtasks" action to the album context menu that
# interrupts the processing of one or all selected albums and deletes
# all tasks associated with them.
#
# Copyright (C) 2026 Mirakuli Teebaum
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.


"""Adds a context menu action to albums that stops all processing tasks
associated with the selected album(s).

The action "Stop albumtasks" appears in the context menu when
right-clicking an album in the left pane. It cancels all pending tasks
of the selected album(s) (e.g. release, track, recording, cover art and
genre lookups, as well as tasks started by other plugins), aborts their
network operations, removes queued fingerprint analyses for the albums'
files and aborts pending file lookups.

Select a single album to stop only that album, or select multiple albums
(e.g. with Ctrl+A) to stop all of them at once.
"""

from picard.plugin3.api import (
    Album,
    BaseAction,
    PluginApi,
)


class StopAlbumTasksAction(BaseAction):
    """Context menu action that stops processing of the selected albums."""

    # Name of the action shown in the album context menu.
    TITLE = 'Stop albumtasks'

    def __init__(self, api=None, parent=None):
        super().__init__(parent)
        self.api = api

    def callback(self, objs):
        """Called by Picard with the currently selected objects."""
        albums = self._collect_albums(objs)
        if not albums:
            self._log('warning', 'Stop albumtasks: no album in selection, nothing to stop')
            return
        for album in albums:
            self._stop_album(album)
        self._log('info', 'Stop albumtasks: stopped processing of %d album(s)', len(albums))

    def _collect_albums(self, objs):
        """Return all distinct albums referenced by the selected objects."""
        albums = []
        seen = set()
        for obj in objs:
            album = obj if isinstance(obj, Album) else getattr(obj, 'album', None)
            if isinstance(album, Album) and id(album) not in seen:
                seen.add(id(album))
                albums.append(album)
        return albums

    def _stop_album(self, album):
        """Stop all tasks associated with the given album."""
        # Cancel all pending album tasks (web requests started by Picard
        # or other plugins, e.g. release, track, recording, cover art and
        # genre lookups) and abort their network operations.
        try:
            album.cancel_tasks()
        except Exception as e:
            self._log('warning', 'Stop albumtasks: error canceling tasks of %r: %r', album, e)

        # Stop tasks pending for the files of this album: remove the files
        # from the fingerprint analysis queue and abort pending lookups.
        try:
            for file in album.iterfiles():
                self._stop_file(file)
        except Exception as e:
            self._log('warning', 'Stop albumtasks: error stopping file tasks of %r: %r', album, e)

        # Make sure the album state gets reflected in the UI.
        try:
            album.update()
        except Exception:
            pass

    def _stop_file(self, file):
        """Stop tasks pending for a single file of an album."""
        # Remove the file from the fingerprint analysis queue, if queued.
        acoustid = getattr(self.tagger, '_acoustid', None)
        if acoustid is not None and hasattr(acoustid, 'stop_analyze'):
            try:
                acoustid.stop_analyze(file)
            except Exception:
                pass
        # Abort a pending lookup request of this file, if any.
        task = getattr(file, '_lookup_task', None)
        if task is not None and hasattr(task, 'abort'):
            try:
                task.abort()
            except Exception:
                pass

    def _log(self, level, msg, *args):
        try:
            getattr(self._logger(), level)(msg, *args)
        except Exception:
            pass

    def _logger(self):
        """Return the plugin logger, with fallbacks if api is missing."""
        api = getattr(self, 'api', None)
        if api is not None and hasattr(api, 'logger'):
            return api.logger
        try:
            return PluginApi.get_api().logger
        except Exception:
            from picard import log
            return log


def enable(api: PluginApi):
    """Entry point of the plugin, called by Picard when the plugin is enabled."""
    api.register_album_action(StopAlbumTasksAction)