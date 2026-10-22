# Picard Sözler is a plugin that fetches lyrics from a public API.
# Copyright (C) 2024 Deniz Engin <dev@dilbil.im>
#
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with this program. If not, see <https://www.gnu.org/licenses/>.

"""Fetches lyrics for each track from the public lrclib.net API.

Port of the former Picard v2 plugin "Picard Sözler" to the Picard
plugin API v3. All plugin metadata lives in MANIFEST.toml; the v2
PLUGIN_* constants are no longer used.
"""

from functools import lru_cache, partial
import re

from PyQt6 import QtWidgets

from picard.plugin3.api import OptionsPage


# Plugin-Optionen mit Defaults (werden in enable() registriert).
PLUGIN_OPTIONS = {
    'skip_asian_lyrics': True,
    'block_cjk': True,
    'block_hangul': True,
    'block_sea': True,
    'block_indic': True,
    'clear_blocked_lyrics': False,
}

# Unicode-Bereiche der Schriftgruppen, die in den Optionen blockierbar sind.
SCRIPT_RANGES = {
    'block_cjk': (
        (0x2E80, 0x2EFF),     # CJK-Radikale (Supplement)
        (0x3000, 0x30FF),     # CJK-Symbole, Hiragana & Katakana
        (0x3400, 0x4DBF),     # CJK-Erweiterung A
        (0x4E00, 0x9FFF),     # CJK-Ideogramme (Hauptblock, Chinesisch)
        (0xF900, 0xFAFF),     # CJK-Kompatibilitätsideogramme
        (0xFF00, 0xFF60),     # Fullwidth-Formen (Latein, Zahlen, Satzzeichen)
        (0x20000, 0x2F8FF),   # CJK-Erweiterungen B–F
    ),
    'block_hangul': (
        (0x3130, 0x318F),     # Hangul Compatibility Jamo
        (0xA960, 0xA97F),     # Hangul Jamo Extended-A
        (0xAC00, 0xD7AF),     # Hangul (Koreanisch)
    ),
    'block_sea': (
        (0x0E00, 0x109F),     # Thai, Lao, Tibetisch, Myanmar
        (0x1780, 0x17FF),     # Khmer
        (0x1800, 0x18AF),     # Mongolisch
    ),
    'block_indic': (
        (0x0900, 0x0DFF),     # indische Schriften (Devanagari, Tamil, Sinhala u. a.)
    ),
}


@lru_cache(maxsize=8)
def _build_re(blocked_groups):
    """Build a regex matching any character of the blocked script groups."""
    ranges = [r for name in blocked_groups for r in SCRIPT_RANGES[name]]
    pattern = '[' + ''.join(f'{chr(start)}-{chr(end)}' for start, end in ranges) + ']'
    return re.compile(pattern)


def has_blocked_script(api, text):
    """Return True if the text contains a character of a blocked script."""
    config = api.plugin_config
    if not config.get('skip_asian_lyrics', True):
        return False
    blocked = tuple(name for name in SCRIPT_RANGES if config.get(name, True))
    if not blocked:
        return False
    return bool(_build_re(blocked).search(text))


def process_response(api, album, metadata, task_id, data, reply, error):
    """Process the lrclib.net API response and complete the album task."""
    logger = api.logger
    try:
        if error:
            logger.error("lrclib request failed: %r", error)
            return

        logger.debug("starting to process")
        logger.debug("got response: %r", data)

        instrumental = data.get("instrumental")
        if instrumental:
            logger.debug("instrumental track; skipping")
            lyrics = None
        else:
            # Fallbacks to plain, ie, unsynced lyrics. Candidates containing
            # blocked scripts (see plugin options) are skipped and the next
            # candidate is tried instead.
            lyrics = None
            for candidate in (data.get("syncedLyrics"), data.get("plainLyrics")):
                if not candidate:
                    continue
                if has_blocked_script(api, candidate):
                    logger.debug("skipping lyrics candidate: contains blocked script characters")
                    continue
                lyrics = candidate
                break

        if lyrics is not None:
            metadata["lyrics"] = lyrics
    except AttributeError:
        logger.error("api malformed response: %r", data)
    finally:
        api.complete_album_task(album, task_id)


def process_track(api, track, metadata, track_node, release_node=None):
    """Queue a lyrics lookup on lrclib.net for the given track."""
    album = track.album

    (mins, secs) = map(int, metadata["~length"].split(":"))
    query = {
        "artist_name": metadata["albumartist"] or metadata["artist"],
        "album_name": metadata["album"],
        "track_name": metadata["title"],
        "duration": mins * 60 + secs,  # accepts seconds only
    }
    api.logger.debug("trying to query with: %r", query)

    task_id = f"lyrics_{track.id}"

    def create_request():
        # request_factory keeps request creation and task registration atomic
        # and prevents race conditions with album removal.
        return api.web_service.get_url(
            url="https://lrclib.net/api/get",
            handler=partial(process_response, api, album, metadata, task_id),
            parse_response_type="json",
            queryargs=query,
        )

    api.add_album_task(
        album,
        task_id,
        "Fetching lyrics",
        request_factory=create_request,
    )


def clear_blocked_lyrics(api, file):
    """Pre-save hook: delete blocked lyrics left over in the file's tags."""
    if not api.plugin_config.get('clear_blocked_lyrics', False):
        return
    values = file.metadata.getall('lyrics')
    if any(has_blocked_script(api, value) for value in values):
        # Markiert das Tag als gelöscht – Picard entfernt es beim Speichern.
        del file.metadata['lyrics']
        api.logger.debug("removing existing blocked lyrics from %r", file.filename)


class SozlerOptionsPage(OptionsPage):
    """Options page: Options → Plugins → Picard Sözler."""

    NAME = "picard_sözler_v3"
    TITLE = "Picard Sözler"
    PARENT = "plugins"

    def __init__(self):
        super().__init__()
        layout = QtWidgets.QVBoxLayout(self)

        filter_group = QtWidgets.QGroupBox("Lyrics filter")
        filter_layout = QtWidgets.QVBoxLayout(filter_group)
        self.skip_asian = QtWidgets.QCheckBox("Skip lyrics written in Asian scripts")
        self.block_cjk = QtWidgets.QCheckBox("Chinese / Japanese (CJK characters) — 汉字 / カナ")
        self.block_hangul = QtWidgets.QCheckBox("Korean (Hangul) — 한글")
        self.block_sea = QtWidgets.QCheckBox("Thai, Lao, Khmer, Tibetan, Burmese, Mongolian")
        self.block_indic = QtWidgets.QCheckBox("Indian scripts (Devanagari, Tamil, Sinhala, …)")
        for checkbox in (self.skip_asian, self.block_cjk, self.block_hangul,
                         self.block_sea, self.block_indic):
            filter_layout.addWidget(checkbox)
        self.skip_asian.toggled.connect(self._update_enabled)
        layout.addWidget(filter_group)

        self.clear_existing = QtWidgets.QCheckBox(
            "Delete blocked lyrics left over in files when saving")
        layout.addWidget(self.clear_existing)

        layout.addStretch()

    def _update_enabled(self):
        enabled = self.skip_asian.isChecked()
        for checkbox in (self.block_cjk, self.block_hangul,
                         self.block_sea, self.block_indic):
            checkbox.setEnabled(enabled)

    def load(self):
        config = self.api.plugin_config
        self.skip_asian.setChecked(config['skip_asian_lyrics'])
        self.block_cjk.setChecked(config['block_cjk'])
        self.block_hangul.setChecked(config['block_hangul'])
        self.block_sea.setChecked(config['block_sea'])
        self.block_indic.setChecked(config['block_indic'])
        self.clear_existing.setChecked(config['clear_blocked_lyrics'])
        self._update_enabled()

    def save(self):
        config = self.api.plugin_config
        config['skip_asian_lyrics'] = self.skip_asian.isChecked()
        config['block_cjk'] = self.block_cjk.isChecked()
        config['block_hangul'] = self.block_hangul.isChecked()
        config['block_sea'] = self.block_sea.isChecked()
        config['block_indic'] = self.block_indic.isChecked()
        config['clear_blocked_lyrics'] = self.clear_existing.isChecked()


def enable(api):
    """Called when the plugin is enabled: register options and hooks."""
    # Loggt die tatsächlich laufende Version (Gut-zu-wissen bei Update-Problemen)
    api.logger.info("picard_sözler_v3 %s enabled", api.get_plugin_version())

    for option, default in PLUGIN_OPTIONS.items():
        api.plugin_config.register_option(option, default)

    api.register_track_metadata_processor(process_track)
    api.register_file_pre_save_processor(clear_blocked_lyrics)
    api.register_options_page(SozlerOptionsPage)


def disable():
    """Called when the plugin is disabled (nothing to clean up)."""