# Load Without Analysis
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

"""Load album clusters directly into the album pane.

Adds a context menu action for clusters in the left-hand pane that
loads all files of the selected clusters into newly created local
albums in the right-hand album pane -- without querying MusicBrainz
and without AcoustID fingerprint analysis. The existing tags of the
files are kept.
"""

import uuid

from picard.plugin3.api import (
    Album,
    BaseAction,
    Cluster,
    PluginApi,
    Track,
)


class LocalAlbum(Album):
    """An album that only exists locally inside Picard.

    It is never loaded from the MusicBrainz web service. All of its
    data comes from the tags already present in the files.
    """

    def load(self, priority=False, refresh=False):
        # Overridden to guarantee that no MusicBrainz request is ever
        # triggered for this album (e.g. by a session restore).
        self.loaded = True
        self.update()

    @property
    def can_refresh(self):
        return False

    @property
    def can_browser_lookup(self):
        return False

    @property
    def can_autotag(self):
        return False

    @property
    def can_analyze(self):
        return False

    @property
    def can_submit(self):
        return False


class LoadWithoutAnalysis(BaseAction):
    TITLE = 'Load Without Analysis'

    def callback(self, objs):
        tagger = self.api.tagger
        loaded = 0
        for obj in objs:
            # Only regular album clusters can be loaded; special
            # clusters such as "Unclustered Files" are skipped.
            if not isinstance(obj, Cluster) or obj.special:
                continue
            if not len(obj.files):
                continue
            try:
                self._load_cluster(tagger, obj)
                loaded += 1
            except Exception:
                self.api.logger.exception(
                    'Load Without Analysis: failed to load %r', obj)
        if loaded:
            self.api.logger.info(
                'Load Without Analysis: loaded %d album(s)', loaded)

    def _load_cluster(self, tagger, cluster):
        # Create a new local album carrying the cluster's metadata
        # (album, albumartist, totaltracks and aggregated tags).
        album = LocalAlbum(str(uuid.uuid4()))
        album.loaded = True
        album.metadata.copy(cluster.metadata)

        # Make the album show up in the right-hand album pane.
        tagger.albums[album.id] = album
        tagger.album_added.emit(album)

        # Turn every file into a track of the new album. Moving the
        # file also removes it from the cluster in the left-hand pane.
        for file in list(cluster.files):
            track = Track(str(uuid.uuid4()), album=album)
            track.orig_metadata.copy(file.orig_metadata)
            track.metadata.copy(file.orig_metadata)
            album.tracks.append(track)
            file.move(track)

        # Refresh the album and expand it in the album pane.
        album.update()
        if album.ui_item:
            album.ui_item.setExpanded(True)


def enable(api: PluginApi):
    api.register_cluster_action(LoadWithoutAnalysis)


def disable():
    pass