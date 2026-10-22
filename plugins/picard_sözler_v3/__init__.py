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

from functools import partial
import re


# Filter: Lyrics, die Schriftzeichen asiatischer Schriften enthalten
# (Chinesisch, Japanisch, Koreanisch, Thai, Khmer, indische Schriften usw.),
# werden verworfen, da lrclib.net hier oft falsche Treffer liefert.
# Auf False setzen, um den Filter zu deaktivieren.
SKIP_ASIAN_LYRICS = True

# Deckt alle größeren asiatischen Schriftsysteme ab
_ASIAN_RE = re.compile(
    '[\u0900-\u109f'          # indische Schriften (Devanagari, Tamil u. a.), Thai, Lao, Tibetisch, Myanmar
    '\u1780-\u17ff'          # Khmer
    '\u1800-\u18af'          # Mongolisch
    '\u2e80-\u2eff'          # CJK-Radikale (Supplement)
    '\u3000-\u30ff'          # CJK-Symbole, Hiragana & Katakana
    '\u3130-\u318f'          # Hangul Compatibility Jamo
    '\u3400-\u4dbf'          # CJK-Erweiterung A
    '\u4e00-\u9fff'          # CJK-Ideogramme (Hauptblock, Chinesisch)
    '\ua960-\ua97f'          # Hangul Jamo Extended-A
    '\uac00-\ud7af'          # Hangul (Koreanisch)
    '\uf900-\ufaff'          # CJK-Kompatibilitätsideogramme
    '\uff00-\uff60'          # Fullwidth-Formen (Latein, Zahlen, Satzzeichen)
    '\U00020000-\U0002f8ff'  # CJK-Erweiterungen B–F
    ']'
)


def has_asian_script(text):
    """Return True if the text contains characters from Asian scripts."""
    return bool(_ASIAN_RE.search(text))


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
            # Fallbacks to plain, ie, unsynced lyrics. With SKIP_ASIAN_LYRICS
            # enabled, candidates containing Asian script characters are
            # skipped and the next candidate is tried instead.
            lyrics = None
            for candidate in (data.get("syncedLyrics"), data.get("plainLyrics")):
                if not candidate:
                    continue
                if SKIP_ASIAN_LYRICS and has_asian_script(candidate):
                    logger.debug("skipping lyrics candidate: contains Asian script characters")
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


def enable(api):
    """Called when the plugin is enabled: register all hooks here."""
    # Loggt die tatsächlich laufende Version (Gut-zu-wissen bei Update-Problemen)
    api.logger.info("picard_sözler_v3 %s enabled", api.get_plugin_version())
    api.register_track_metadata_processor(process_track)


def disable():
    """Called when the plugin is disabled (nothing to clean up)."""