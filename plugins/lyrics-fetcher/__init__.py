# Lyrics Fetcher is a plugin that fetches lyrics from a public API.
# Copyright (C) 2024 Deniz Engin <dev@dilbil.im>
#
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with this program. If not, see <https://www.gnu.org/licenses/>.

"""Fetches lyrics for each track from the public lrclib.net API.

Port of the former Picard v2 plugin "Picard Sözler" to the Picard
plugin API v3 (renamed to "lyrics-fetcher"). All plugin metadata lives
in MANIFEST.toml; the v2 PLUGIN_* constants are no longer used.
"""

from functools import lru_cache, partial
import re

from PyQt6 import QtWidgets

from picard.plugin3.api import OptionsPage


# Plugin-Optionen mit Defaults (werden in enable() registriert).
PLUGIN_OPTIONS = {
    # 'skip' = blockierte Lyrics gar nicht laden, 'load' = trotzdem laden
    'blocked_lyrics_action': 'skip',
    'block_cjk': True,
    'block_hangul': True,
    'block_sea': True,
    'block_indic': True,
    'clear_blocked_lyrics': True,
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


def _get_option(config, name, default):
    """Read a plugin option, returning default if unset or not registered.

    Picard's ConfigSection has no get() method and __getitem__ returns
    None for unregistered options, so wrap the access here.
    """
    value = config[name]
    return default if value is None else value


def has_blocked_script(api, text):
    """Return True if the text contains a character of a blocked script."""
    config = api.plugin_config
    if _get_option(config, 'blocked_lyrics_action', 'skip') != 'skip':
        # 'load': blockierte Lyrics sind ausdrücklich erwünscht
        return False
    blocked = tuple(name for name in SCRIPT_RANGES if _get_option(config, name, True))
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

        # album.loaded-Guard: Lief der Task ins Timeout und ist das Album
        # bereits finalisiert (Scripts sind gelaufen), würden die Lyrics
        # hier unbemerkt nachträglich in die Metadaten geschrieben, ohne
        # dass die Tagging-Scripts sie jemals sehen. Dann lieber leer lassen.
        if lyrics is not None and not album.loaded:
            metadata["lyrics"] = lyrics
    except AttributeError:
        logger.exception("api malformed response: %r", data)
    finally:
        api.complete_album_task(album, task_id)
        # Picard 3.0.x kann abgelaufene Plugin-Tasks nicht selbst aus der
        # Pending-Liste entfernen: check_timed_out_tasks() crasht beim
        # abort() VOR dem pop() mit AttributeError ('PendingRequest' has
        # no 'abort'). Der Task bliebe für immer in _pending_tasks und
        # blockierte die Album-Finalisierung dauerhaft. Deshalb räumen wir
        # eigene, abgelaufene Tasks hier selbst auf – erkennbar am
        # Präfix "lyrics-fetcher_lyrics_" (Plugin-Name + task_id aus
        # process_track). Spät eintreffende Antworten sind danach harmlos;
        # complete_album_task loggt dann nur eine Warnung "unknown task".
        try:
            pending = getattr(album, '_pending_tasks', None)
            if pending:
                for pending_id, task_info in list(pending.items()):
                    if (pending_id.startswith('lyrics-fetcher_lyrics_')
                            and task_info.is_timed_out()):
                        pending.pop(pending_id, None)
        except Exception:
            logger.exception("timed-out task cleanup failed for %r", album)
        # Workaround für PICARD-3513 (Picard 3.0.x): complete_album_task
        # stößt die Album-Finalisierung bei blockierenden Tasks nicht
        # erneut an – das Album würde nie fertig geladen werden. Deshalb
        # wie im bewährten v2-Muster zusätzlich _finalize_loading
        # aufrufen; die internen Guards (self.loaded, has_critical_tasks)
        # machen wiederholte oder verfrühte Aufrufe harmlos.
        if album.id in api.tagger.albums:
            # try/except: _finalize_loading berührt Picard-Interna, die in
            # 3.0.x teils fehlerhaft sind (z. B. check_timed_out_tasks) –
            # ein Fehler dort darf Picard niemals mitreißen.
            try:
                album._finalize_loading(None)
            except Exception:
                logger.exception("finalize workaround failed for %r", album)


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

    # blocking=True hält die Album-Finalisierung (und damit die Ausführung
    # der Tagging-Scripts) an, bis die Lyrics geladen sind – die Scripts
    # sehen die Lyrics also garantiert. Hinweis: Picard setzt für
    # blockierende Plugin-Tasks ohnehin einen Standard-Timeout (30 s);
    # abgelaufene Tasks räumt der Handler in process_response selbst auf,
    # weil Picards check_timed_out_tasks() in 3.0.x dabei crasht.
    api.add_album_task(
        album,
        task_id,
        "Fetching lyrics",
        request_factory=create_request,
        blocking=True,
    )


def clear_blocked_lyrics(api, file):
    """Pre-save hook: delete blocked lyrics left over in the file's tags."""
    if not _get_option(api.plugin_config, 'clear_blocked_lyrics', True):
        return
    values = file.metadata.getall('lyrics')
    if any(has_blocked_script(api, value) for value in values):
        # Markiert das Tag als gelöscht – Picard entfernt es beim Speichern.
        del file.metadata['lyrics']
        api.logger.debug("removing existing blocked lyrics from %r", file.filename)


class LyricsFetcherOptionsPage(OptionsPage):
    """Options page: Options → Plugins → Lyrics Fetcher."""

    NAME = "lyrics-fetcher"
    TITLE = "Lyrics Fetcher"
    PARENT = "plugins"

    def __init__(self):
        super().__init__()
        layout = QtWidgets.QVBoxLayout(self)

        filter_group = QtWidgets.QGroupBox("Lyrics filter")
        filter_layout = QtWidgets.QVBoxLayout(filter_group)
        self.action_label = QtWidgets.QLabel(
            "When fetched lyrics are written in a blocked script:")
        self.action_combo = QtWidgets.QComboBox()
        self.action_combo.addItem("Skip them — do not load such lyrics at all", 'skip')
        self.action_combo.addItem("Load them anyway", 'load')
        self.action_combo.currentIndexChanged.connect(self._update_enabled)
        self.block_cjk = QtWidgets.QCheckBox("Chinese / Japanese (CJK characters) — 汉字 / カナ")
        self.block_hangul = QtWidgets.QCheckBox("Korean (Hangul) — 한글")
        self.block_sea = QtWidgets.QCheckBox("Thai, Lao, Khmer, Tibetan, Burmese, Mongolian")
        self.block_indic = QtWidgets.QCheckBox("Indian scripts (Devanagari, Tamil, Sinhala, …)")
        filter_layout.addWidget(self.action_label)
        filter_layout.addWidget(self.action_combo)
        for checkbox in (self.block_cjk, self.block_hangul,
                         self.block_sea, self.block_indic):
            filter_layout.addWidget(checkbox)
        layout.addWidget(filter_group)

        self.clear_existing = QtWidgets.QCheckBox(
            "Delete blocked lyrics left over in files when saving")
        layout.addWidget(self.clear_existing)

        layout.addStretch()

    def _update_enabled(self):
        enabled = self.action_combo.currentData() == 'skip'
        for checkbox in (self.block_cjk, self.block_hangul,
                         self.block_sea, self.block_indic):
            checkbox.setEnabled(enabled)

    def load(self):
        config = self.api.plugin_config
        action = _get_option(config, 'blocked_lyrics_action', 'skip')
        index = self.action_combo.findData(action)
        self.action_combo.setCurrentIndex(index if index >= 0 else 0)
        self.block_cjk.setChecked(_get_option(config, 'block_cjk', True))
        self.block_hangul.setChecked(_get_option(config, 'block_hangul', True))
        self.block_sea.setChecked(_get_option(config, 'block_sea', True))
        self.block_indic.setChecked(_get_option(config, 'block_indic', True))
        self.clear_existing.setChecked(_get_option(config, 'clear_blocked_lyrics', True))
        self._update_enabled()

    def save(self):
        config = self.api.plugin_config
        config['blocked_lyrics_action'] = self.action_combo.currentData()
        config['block_cjk'] = self.block_cjk.isChecked()
        config['block_hangul'] = self.block_hangul.isChecked()
        config['block_sea'] = self.block_sea.isChecked()
        config['block_indic'] = self.block_indic.isChecked()
        config['clear_blocked_lyrics'] = self.clear_existing.isChecked()


def enable(api):
    """Called when the plugin is enabled: register options and hooks."""
    # Loggt die tatsächlich laufende Version (Gut-zu-wissen bei Update-Problemen)
    api.logger.info("lyrics-fetcher %s enabled", api.get_plugin_version())

    for option, default in PLUGIN_OPTIONS.items():
        api.plugin_config.register_option(option, default)

    api.register_track_metadata_processor(process_track)
    api.register_file_pre_save_processor(clear_blocked_lyrics)
    api.register_options_page(LyricsFetcherOptionsPage)


def disable():
    """Called when the plugin is disabled (nothing to clean up)."""