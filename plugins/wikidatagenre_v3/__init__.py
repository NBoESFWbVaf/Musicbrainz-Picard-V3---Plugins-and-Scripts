# -*- coding: utf-8 -*-
"""Wikidata Genre V3 — MusicBrainz Picard Plugin API v3.

Port of the Wikidata genre plugin to Picard 3.0's new plugin system.

Corrected version:
- OptionsPage: api is set as a CLASS attribute by api.register_options_page();
  __init__ must NOT shadow it with None.
- Web request handlers receive (document, reply, error) — three arguments.
- get_url() with parse_response_type=None, so raw XML bytes are passed
  through to the handlers without JSON parse errors.
- Dead code removed (_request_wikidata/_handle_wikidata, config fallbacks).
- Album tasks are CRITICAL tasks (blocking=True): the album is only
  finalized once the genres have arrived — the user's tagging scripts
  only run in _finalize_loading_album() and therefore see the complete
  metadata including genres. Since api.complete_album_task() does NOT
  re-trigger finalization (album.complete_task() only removes the task),
  the plugin calls album._finalize_loading(None) after each completed
  task — the same pattern classic V2 plugins used. Without this
  follow-up, the album would be stuck at "Loading album information"
  forever.
- Before finalizing, timed-out album tasks are removed safely: Picard's
  check_timed_out_tasks() calls request.abort(), which a PendingRequest
  does not have (AttributeError). webservice.abort_task() is used
  instead, as in Picard's cancel_tasks().
- The CRITICAL task is registered directly via album.add_task(timeout=None):
  api.add_album_task(blocking=True) enforces a 30-second timeout, which
  is not enough for albums with many unique works (Picard rate-limits
  Wikidata to ~1 request/second, i.e. from ~28 works onward the chain
  would break). Like the classic V2 plugin, there is no artificial
  timeout; network timeouts still apply.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from urllib.parse import urlparse

from PyQt6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QLineEdit,
)

from picard.album_requests import TaskType
from picard.plugin3.api import OptionsPage


PLUGIN_VERSION = "3.4.2"
WIKIDATA_BASE = "https://www.wikidata.org/wiki/Special:EntityData/"
MB_BASE = "https://musicbrainz.org/ws/2/"
RDF_NS = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
RDFS_NS = "http://www.w3.org/2000/01/rdf-schema#"
XML_NS = "http://www.w3.org/XML/1998/namespace"
WIKIDATA_ENTITY = "http://www.wikidata.org/entity/"
P136 = "{http://www.wikidata.org/prop/direct/}P136"

DEFAULTS = {
    "use_release_group_genres": True,
    "use_artist_genres": True,
    "use_artist_only_if_no_release": True,
    "ignore_genres_from_these_artists": "",
    "use_work_genres": True,
    "ignore_these_genres": r"seen live, favorites, /\d+ of \d+ stars/",
    "genre_delimiter": "; ",
}

# Requests are shared per album + MusicBrainz entity. Values contain the
# metadata objects waiting for the result.
_PENDING = {}

# Cross-album genre cache, keyed by "<entity_type>|<entity_id>".
_CACHE = {}

# Full task IDs ("<plugin_id>_<task_id>") of album tasks that were cleaned
# up due to a timeout, paired with id(album). Prevents their later
# complete_album_task() from triggering the "Attempted to complete
# unknown task" warning.
_ABANDONED = set()


def _setting(api, key):
    """Read a plugin option. All keys are registered in enable()."""
    return api.plugin_config[key]


def _parse_ignored(setting):
    patterns = []
    for raw in str(setting or "").split(","):
        raw = raw.strip()
        if not raw:
            continue
        if len(raw) >= 2 and raw.startswith("/") and raw.endswith("/"):
            try:
                patterns.append(re.compile(raw[1:-1], re.IGNORECASE))
            except re.error:
                # Invalid patterns are ignored rather than breaking tagging.
                continue
        else:
            patterns.append(raw.casefold())
    return patterns


def _is_ignored(patterns, value):
    value = str(value or "").strip()
    for pattern in patterns:
        if hasattr(pattern, "search"):
            if pattern.search(value):
                return True
        elif value.casefold() == pattern:
            return True
    return False


def _xml_bytes(data):
    if isinstance(data, bytes):
        return data
    if isinstance(data, str):
        return data.encode("utf-8")
    if hasattr(data, "read"):
        return data.read()
    return bytes(data)


def _entity_id(url):
    path = urlparse(url).path.rstrip("/")
    candidate = path.split("/")[-1]
    if re.fullmatch(r"Q\d+", candidate):
        return candidate
    return None


def _split_genres(metadata, delimiter):
    result = []
    for value in metadata.getall("genre"):
        if delimiter and delimiter in str(value):
            result.extend(part.strip() for part in str(value).split(delimiter) if part.strip())
        elif str(value).strip():
            result.append(str(value).strip())
    return result


def _write_genres(metadata, genres, delimiter):
    merged = sorted(set(_split_genres(metadata, delimiter)).union(genres), key=str.casefold)
    if delimiter:
        metadata["genre"] = delimiter.join(merged)
    else:
        metadata["genre"] = merged


def _parse_mb_relations(data, entity_type):
    """Return Wikidata entity URLs found in a MusicBrainz XML response."""
    root = ET.fromstring(_xml_bytes(data))
    urls = []
    for relation in root.iter():
        if relation.tag.rsplit("}", 1)[-1] != "relation":
            continue
        if relation.attrib.get("type", "").casefold() != "wikidata":
            continue
        for child in relation:
            if child.tag.rsplit("}", 1)[-1] == "target" and child.text:
                url = child.text.strip()
                if _entity_id(url):
                    urls.append(url)
    return list(dict.fromkeys(urls))


def _parse_wikidata_genres(data, item_id, ignored_patterns):
    """Read P136 genre claims and their English labels from Wikidata RDF/XML."""
    root = ET.fromstring(_xml_bytes(data))
    genre_ids = set()
    labels = {}
    for element in root.iter():
        about = element.attrib.get(f"{{{RDF_NS}}}about", "")
        if about == WIKIDATA_ENTITY + item_id:
            for child in element:
                if child.tag == P136:
                    resource = child.attrib.get(f"{{{RDF_NS}}}resource", "")
                    genre_id = resource.rsplit("/", 1)[-1]
                    if re.fullmatch(r"Q\d+", genre_id):
                        genre_ids.add(genre_id)
        if about.startswith(WIKIDATA_ENTITY):
            qid = about.rsplit("/", 1)[-1]
            if re.fullmatch(r"Q\d+", qid):
                for child in element:
                    if child.tag == f"{{{RDFS_NS}}}label" and child.attrib.get(f"{{{XML_NS}}}lang") == "en":
                        labels[qid] = (child.text or "").strip()

    genres = []
    for qid in sorted(genre_ids):
        label = labels.get(qid)
        if label:
            # Keep the original plugin's English title-case behavior.
            label = label.title()
            if not _is_ignored(ignored_patterns, label):
                genres.append(label)
    return genres


def _cleanup_timed_out_tasks(api, album):
    """Safely clean up timed-out album tasks.

    Picard's check_timed_out_tasks() calls task_info.request.abort(),
    but a PendingRequest does not have that method (only the "aborted"
    flag) — this raises an AttributeError and aborts finalization, so
    the album would be stuck for good. The correct method is
    webservice.abort_task(), which Picard itself uses in cancel_tasks().
    We therefore perform the cleanup here, before _finalize_loading()
    is called.
    """
    pending = getattr(album, "_pending_tasks", None)
    if not pending:
        return
    try:
        items = list(pending.items())
    except Exception:
        return
    for full_id, info in items:
        try:
            if not info.is_timed_out():
                continue
        except Exception:
            continue
        try:
            elapsed = info.elapsed_time()
        except Exception:
            elapsed = -1.0
        api.logger.warning(
            "Wikidata Genre V3: album task %s timed out after %.1fs: %s",
            full_id, elapsed, getattr(info, "description", ""),
        )
        request = getattr(info, "request", None)
        if request is not None:
            try:
                album.tagger.webservice.abort_task(request)
            except Exception:
                pass
        try:
            pending.pop(full_id, None)
        except Exception:
            pass
        _ABANDONED.add((id(album), full_id))


def _finish_task(api, album, task_id):
    """Complete an album task and re-trigger finalization.

    api.complete_album_task() only calls album.complete_task() and does
    NOT re-trigger the album's finalization. Since our tasks are
    CRITICAL (they hold back _finalize_loading_album() until the genres
    are there — the user's tagging scripts only run at that point), we
    make up for it here, exactly like the classic V2 plugins did
    (album._requests -= 1; album._finalize_loading(None)).
    _finalize_loading() itself is idempotent: it returns early if
    critical tasks are still open or the album has already been loaded.
    """
    full_id = f"{getattr(api, 'plugin_id', '')}_{task_id}"
    if (id(album), full_id) in _ABANDONED:
        # The task was already removed from the album's task management
        # due to a timeout — do not complete it again.
        _ABANDONED.discard((id(album), full_id))
        return
    try:
        api.complete_album_task(album, task_id)
    except Exception:
        api.logger.exception("Wikidata Genre: could not complete task %s", task_id)
    else:
        # INFO log for diagnostics: confirms without debug mode that
        # the task was completed.
        api.logger.info("Wikidata Genre V3: lookup task %s finished", task_id)
    if album is None or getattr(album, "loaded", True):
        return
    tagger = getattr(album, "tagger", None)
    if tagger is None or getattr(album, "id", None) not in getattr(tagger, "albums", {}):
        # The album was removed in the meantime; do not finalize.
        return
    # Remove timed-out tasks safely first — otherwise
    # _finalize_loading() would crash in Picard's
    # check_timed_out_tasks() with an AttributeError
    # (PendingRequest has no abort()).
    _cleanup_timed_out_tasks(api, album)
    try:
        album._finalize_loading(None)
    except Exception:
        api.logger.exception("Wikidata Genre: failed to finalize album")


def _refresh_track(track):
    """Refresh the track display so newly written genres become
    visible immediately."""
    if track is None:
        return
    try:
        track.update()
    except Exception:
        pass


def _apply_genres(api, item_key, cache_key, pending, all_genres):
    """Write the collected genres to all waiting metadata objects."""
    if not all_genres:
        return
    _CACHE[cache_key] = all_genres
    delimiter = _setting(api, "genre_delimiter")
    for metadata, source_type, track in pending["metadata"]:
        if source_type == "release-group":
            metadata["~release_group_genre_sourced"] = True
        elif source_type == "artist":
            if (
                _setting(api, "use_artist_only_if_no_release")
                and metadata.get("~release_group_genre_sourced", False)
            ):
                continue
            if _is_ignored(
                _parse_ignored(_setting(api, "ignore_genres_from_these_artists")),
                metadata.get("artist", ""),
            ):
                continue
        _write_genres(metadata, all_genres, delimiter)
        _refresh_track(track)


def _handle_musicbrainz(api, album, task_id, item_key, cache_key, entity_type, data, error):
    """Handle the MusicBrainz url-rels response and chain Wikidata requests.

    Web request handlers receive (document, reply, error); reply is not
    needed here but must be part of the signature.
    """
    pending = _PENDING.get(item_key)
    if not pending:
        _finish_task(api, album, task_id)
        return
    try:
        if error:
            api.logger.warning("Wikidata Genre: MusicBrainz request failed for %s: %s", item_key, error)
            return
        try:
            urls = _parse_mb_relations(data, entity_type)
        except Exception:
            api.logger.exception("Wikidata Genre: failed to parse MusicBrainz response")
            return
        if not urls:
            api.logger.info(
                "Wikidata Genre V3: %s has no Wikidata relation in MusicBrainz",
                cache_key,
            )
            return

        pending["genres"] = set()

        def fetch_one(index):
            if index >= len(urls):
                try:
                    all_genres = sorted(pending["genres"], key=str.casefold)
                    if all_genres:
                        # Result log: which genres actually came from
                        # Wikidata, and for how many waiting tracks?
                        api.logger.info(
                            "Wikidata Genre V3: %s received from Wikidata "
                            "(%d tracks waiting): %s",
                            cache_key, len(pending["metadata"]), ", ".join(all_genres),
                        )
                    else:
                        api.logger.info(
                            "Wikidata Genre V3: %s — no usable genres from Wikidata",
                            cache_key,
                        )
                    _apply_genres(api, item_key, cache_key, pending, all_genres)
                except Exception:
                    api.logger.exception("Wikidata Genre: failed writing genres for %s", cache_key)
                finally:
                    _PENDING.pop(item_key, None)
                    _finish_task(api, album, task_id)
                return

            wikidata_id = _entity_id(urls[index])
            if not wikidata_id:
                fetch_one(index + 1)
                return

            def on_wikidata(data2, reply, error2):
                try:
                    if not error2:
                        try:
                            pending["genres"].update(
                                _parse_wikidata_genres(
                                    data2, wikidata_id,
                                    _parse_ignored(_setting(api, "ignore_these_genres")),
                                )
                            )
                        except Exception:
                            api.logger.exception("Wikidata Genre: failed to parse %s", wikidata_id)
                    else:
                        api.logger.warning("Wikidata Genre: request failed for %s: %s", wikidata_id, error2)
                finally:
                    fetch_one(index + 1)

            try:
                api.web_service.get_url(
                    url=f"{WIKIDATA_BASE}{wikidata_id}.rdf",
                    parse_response_type=None,
                    handler=on_wikidata,
                )
            except Exception:
                api.logger.exception("Wikidata Genre: could not request %s", wikidata_id)
                fetch_one(index + 1)

        # Flag: chained Wikidata requests own the task completion now.
        pending["chained"] = True
        fetch_one(0)
    finally:
        # If no relations were found or an early error occurred, complete
        # the task here. Once chained requests started, their callbacks
        # own completion.
        if not pending.get("chained") and _PENDING.get(item_key) is pending:
            _PENDING.pop(item_key, None)
            _finish_task(api, album, task_id)


def _add_album_task(api, album, task_id, description, create_request):
    """Register a CRITICAL task without an artificial timeout.

    This makes the album finalize only once the genres are available —
    the user's tagging scripts, which are supposed to clean up the
    genres, only run in _finalize_loading_album().

    api.add_album_task(blocking=True) enforces a 30-second timeout.
    But Picard rate-limits Wikidata requests to roughly one per second,
    so albums with many unique works would exceed 30 s; the last tasks
    would be cleaned up and their genres would arrive without being
    scripted. The task is therefore registered directly with
    timeout=None — like the classic V2 plugin, which also had no
    timeouts. Network timeouts still apply, and _finish_task() completes
    the task in any case. If direct registration fails, the public API
    call is used as a fallback (with its enforced 30 s timeout).
    """
    plugin_id = getattr(api, "plugin_id", "")
    try:
        album.add_task(
            task_id=f"{plugin_id}_{task_id}",
            task_type=TaskType.CRITICAL,
            description=f"[{plugin_id}] {description}",
            timeout=None,
            plugin_id=plugin_id or None,
            request_factory=create_request,
        )
    except Exception:
        api.add_album_task(
            album,
            task_id,
            description,
            request_factory=create_request,
            blocking=True,
        )


def _queue_lookup(api, album, track, metadata, item_id, entity_type):
    if not item_id:
        return
    cache_key = f"{entity_type}|{item_id}"
    delimiter = _setting(api, "genre_delimiter")
    if cache_key in _CACHE:
        api.logger.debug(
            "Wikidata Genre V3: %s %s served from cache: %s",
            entity_type, item_id, ", ".join(_CACHE[cache_key]),
        )
        _write_genres(metadata, _CACHE[cache_key], delimiter)
        _refresh_track(track)
        return

    album_key = str(getattr(album, "id", id(album)))
    item_key = f"{album_key}|{cache_key}"
    task_id = f"wikidatagenre_{entity_type}_{item_id}"
    if item_key in _PENDING:
        # Multiple tracks share the same entity: only ONE lookup per
        # album + entity; all waiting metadata objects receive the result.
        api.logger.debug(
            "Wikidata Genre V3: %s %s already pending, sharing result",
            entity_type, item_id,
        )
        _PENDING[item_key]["metadata"].append((metadata, entity_type, track))
        return

    _PENDING[item_key] = {"metadata": [(metadata, entity_type, track)]}

    path = f"{MB_BASE}{entity_type}/{item_id}?inc=url-rels"

    def create_request():
        return api.web_service.get_url(
            url=path,
            parse_response_type=None,
            handler=lambda data, reply, error: _handle_musicbrainz(
                api, album, task_id, item_key, cache_key, entity_type, data, error
            ),
        )

    try:
        # IMPORTANT: CRITICAL task, so the album is only finalized once
        # the genres are available (see _add_album_task and _finish_task).
        _add_album_task(
            api, album, task_id,
            f"Looking up Wikidata genres ({entity_type})",
            create_request,
        )
    except Exception:
        _PENDING.pop(item_key, None)
        api.logger.exception("Wikidata Genre: failed to queue %s", item_id)
        # The task may already have been registered before
        # request_factory() failed. Complete it in any case, otherwise
        # it would block the album's finalization forever.
        try:
            api.complete_album_task(album, task_id)
        except Exception:
            pass
    else:
        # INFO log for diagnostics: confirms without debug mode that the
        # new plugin version is running and the lookup was registered.
        api.logger.info(
            "Wikidata Genre V3: genre lookup queued for %s %s", entity_type, item_id
        )


def process_track(api, track, metadata, track_node, release_node=None):
    use_release = _setting(api, "use_release_group_genres")
    use_artist = _setting(api, "use_artist_genres")
    use_work = _setting(api, "use_work_genres")

    if use_release:
        for mbid in metadata.getall("musicbrainz_releasegroupid"):
            _queue_lookup(api, track.album, track, metadata, mbid, "release-group")
    if use_artist:
        for mbid in metadata.getall("musicbrainz_albumartistid"):
            _queue_lookup(api, track.album, track, metadata, mbid, "artist")
        for mbid in metadata.getall("musicbrainz_artistid"):
            _queue_lookup(api, track.album, track, metadata, mbid, "artist")
    if use_work:
        for mbid in metadata.getall("musicbrainz_workid"):
            _queue_lookup(api, track.album, track, metadata, mbid, "work")


class WikidataGenreOptionsPage(OptionsPage):
    NAME = "wikidatagenre_v3"
    TITLE = "Wikidata Genre V3"
    PARENT = "plugins"

    def __init__(self, parent=None):
        # IMPORTANT: no api parameter, do not overwrite self.api.
        # api.register_options_page() sets the API as a CLASS attribute
        # on this class; the options dialog instantiates the page with
        # no arguments. A "self.api = api" would shadow the class
        # attribute with None and crash load()/save().
        super().__init__(parent)
        self.use_release_group = QCheckBox("Use genres from the release group")
        self.use_artist = QCheckBox("Use genres from the artists")
        self.artist_only_if_no_release = QCheckBox(
            "Only use artist genres if no release group genres were found"
        )
        self.use_work = QCheckBox("Use genres from the works")
        self.ignore_artists = QLineEdit()
        self.ignore_genres = QLineEdit()
        self.delimiter = QLineEdit()
        layout = QFormLayout()
        layout.addRow(self.use_release_group)
        layout.addRow(self.use_artist)
        layout.addRow(self.artist_only_if_no_release)
        layout.addRow(self.use_work)
        layout.addRow("Ignore artists (comma-separated):", self.ignore_artists)
        layout.addRow("Ignore genres (comma-separated; /regex/ allowed):", self.ignore_genres)
        layout.addRow("Genre delimiter:", self.delimiter)
        self.setLayout(layout)

    def load(self):
        config = self.api.plugin_config
        self.use_release_group.setChecked(bool(config["use_release_group_genres"]))
        self.use_artist.setChecked(bool(config["use_artist_genres"]))
        self.artist_only_if_no_release.setChecked(bool(config["use_artist_only_if_no_release"]))
        self.use_work.setChecked(bool(config["use_work_genres"]))
        self.ignore_artists.setText(str(config["ignore_genres_from_these_artists"] or ""))
        self.ignore_genres.setText(str(config["ignore_these_genres"] or ""))
        self.delimiter.setText(str(config["genre_delimiter"] or ""))

    def save(self):
        config = self.api.plugin_config
        config["use_release_group_genres"] = self.use_release_group.isChecked()
        config["use_artist_genres"] = self.use_artist.isChecked()
        config["use_artist_only_if_no_release"] = self.artist_only_if_no_release.isChecked()
        config["use_work_genres"] = self.use_work.isChecked()
        config["ignore_genres_from_these_artists"] = self.ignore_artists.text()
        config["ignore_these_genres"] = self.ignore_genres.text()
        config["genre_delimiter"] = self.delimiter.text()


def enable(api):
    """Picard 3 plugin entry point. Registers all options before any
    plugin_config access happens."""
    for key, default in DEFAULTS.items():
        api.plugin_config.register_option(key, default)
    api.register_track_metadata_processor(process_track)
    api.register_options_page(WikidataGenreOptionsPage)
    # Log the active sources at startup — otherwise a disabled source
    # is hard to identify as the cause of missing genres.
    api.logger.info(
        "Wikidata Genre V3 %s enabled (sources: release-group=%s, artist=%s, work=%s)",
        PLUGIN_VERSION,
        _setting(api, "use_release_group_genres"),
        _setting(api, "use_artist_genres"),
        _setting(api, "use_work_genres"),
    )


def disable():
    """Clear in-memory caches when the plugin is disabled."""
    _PENDING.clear()
    _CACHE.clear()
    _ABANDONED.clear()