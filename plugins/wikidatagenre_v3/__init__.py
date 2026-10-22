# -*- coding: utf-8 -*-
"""Wikidata Genre V3 — MusicBrainz Picard Plugin API v3.

Portierung des Wikidata-Genre-Plugins auf das neue Plugin-System von Picard 3.0.

Korrigierte Fassung:
- OptionsPage: api wird als Klassenattribut von api.register_options_page()
  gesetzt; __init__ darf es NICHT mit None überschreiben.
- Web-Request-Handler empfangen (document, reply, error) — drei Argumente.
- get_url() mit parse_response_type=None, damit rohe XML-Bytes ohne
  JSON-Parse-Fehler an die Handler durchgereicht werden.
- Toter Code entfernt (_request_wikidata/_handle_wikidata, Config-Fallbacks).
- Album-Tasks sind CRITICAL-Tasks (blocking=True): Das Album wird erst
  finalisiert, wenn die Genres eingetroffen sind — die Tagging-Scripte des
  Benutzers laufen erst in _finalize_loading_album() und sehen damit die
  vollständigen Metadaten inklusive Genres. Da api.complete_album_task()
  das Finalisieren NICHT erneut anstößt (album.complete_task() entfernt
  den Task nur), ruft das Plugin nach jedem abgeschlossenen Task
  album._finalize_loading(None) auf — dasselbe Muster, das klassische
  V2-Plugins nutzten. Ohne diesen Nachtrag bliebe das Album dauerhaft bei
  "Albuminformationen werden geladen" hängen.
- Vor dem Finalisieren werden abgelaufene Album-Tasks sicher entfernt:
  Picards check_timed_out_tasks() ruft request.abort() auf, was ein
  PendingRequest nicht besitzt (AttributeError). Stattdessen wird
  webservice.abort_task() verwendet, wie in Picards cancel_tasks().
- Der CRITICAL-Task wird direkt über album.add_task(timeout=None)
  registriert: api.add_album_task(blocking=True) erzwingt ein
  30-Sekunden-Timeout, das bei Alben mit vielen einzigartigen Werken
  nicht reicht (Picard drosselt Wikidata auf ~1 Anfrage/Sekunde, d. h.
  ab ~28 Werken würde die Kette abreißen). Wie beim klassischen V2-Plugin
  gibt es kein künstliches Timeout; Netzwerk-Timeouts greifen weiterhin.
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


PLUGIN_VERSION = "3.4.0"
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

# Volle Task-IDs ("<plugin_id>_<task_id>") der durch Timeout abgeräumten
# Album-Tasks, jeweils mit id(album) gepaart. Verhindert, dass deren
# späteres complete_album_task() die Warnung "Attempted to complete
# unknown task" auslöst.
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
    """Räumt abgelaufene Album-Tasks sicher ab.

    Picards check_timed_out_tasks() ruft task_info.request.abort() auf,
    ein PendingRequest besitzt diese Methode aber nicht (nur das Flag
    "aborted") — das löst ein AttributeError aus und bricht das
    Finalisieren ab, sodass das Album endgültig hängen bliebe. Die
    korrekte Methode ist webservice.abort_task(), wie sie Picard selbst
    in cancel_tasks() verwendet. Wir führen die Aufräumarbeit deshalb
    hier aus, bevor _finalize_loading() aufgerufen wird.
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
    """Album-Task abschließen und das Finalisieren erneut anstoßen.

    api.complete_album_task() ruft nur album.complete_task() auf und stößt
    das Finalisieren des Albums NICHT erneut an. Da unsere Tasks CRITICAL
    sind (sie halten _finalize_loading_album() auf, bis die Genres da sind
    — erst dort laufen die Tagging-Scripte des Benutzers), holen wir das
    hier nach, exakt wie die klassischen V2-Plugins
    (album._requests -= 1; album._finalize_loading(None)).
    _finalize_loading() selbst ist idempotent: Es kehrt früh zurück, wenn
    noch kritische Tasks offen sind oder das Album bereits geladen wurde.
    """
    full_id = f"{getattr(api, 'plugin_id', '')}_{task_id}"
    if (id(album), full_id) in _ABANDONED:
        # Task wurde wegen Timeout bereits aus der Album-Verwaltung
        # entfernt — nicht erneut abschließen.
        _ABANDONED.discard((id(album), full_id))
        return
    try:
        api.complete_album_task(album, task_id)
    except Exception:
        api.logger.exception("Wikidata Genre: could not complete task %s", task_id)
    else:
        # INFO-Log als Diagnose: bestätigt ohne Debug-Modus, dass der
        # Task abgeschlossen wurde.
        api.logger.info("Wikidata Genre V3: lookup task %s finished", task_id)
    if album is None or getattr(album, "loaded", True):
        return
    tagger = getattr(album, "tagger", None)
    if tagger is None or getattr(album, "id", None) not in getattr(tagger, "albums", {}):
        # Album wurde inzwischen entfernt; nicht finalisieren.
        return
    # Abgelaufene Tasks zuerst sicher entfernen — sonst bräche
    # _finalize_loading() in Picards check_timed_out_tasks() mit
    # AttributeError ab (PendingRequest hat kein abort()).
    _cleanup_timed_out_tasks(api, album)
    try:
        album._finalize_loading(None)
    except Exception:
        api.logger.exception("Wikidata Genre: failed to finalize album")


def _refresh_track(track):
    """Aktualisiert die Track-Anzeige, damit neu geschriebene Genres
    sofort sichtbar werden."""
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

    Web-Request-Handler empfangen (document, reply, error); reply wird
    hier nicht benötigt, muss aber in der Signatur stehen.
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
            return

        pending["genres"] = set()

        def fetch_one(index):
            if index >= len(urls):
                try:
                    all_genres = sorted(pending["genres"], key=str.casefold)
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
    """Registriert einen CRITICAL-Task ohne künstliches Timeout.

    Das Album wird dadurch erst finalisiert, wenn die Genres vorliegen —
    erst in _finalize_loading_album() laufen die Tagging-Scripte des
    Benutzers, die Bereinigungen auf den Genres ausführen sollen.

    api.add_album_task(blocking=True) erzwingt ein 30-Sekunden-Timeout.
    Picard drosselt Wikidata-Anfragen aber auf etwa eine pro Sekunde,
    weshalb Alben mit vielen einzigartigen Werken die 30 s überschreiten
    würden; die letzten Tasks würden abgeräumt und deren Genres gingen
    unscriptet ein. Der Task wird daher direkt mit timeout=None
    registriert — wie das klassische V2-Plugin, das ebenfalls keine
    Timeouts kannte. Netzwerk-Timeouts greifen weiterhin, und
    _finish_task() schließt den Task in jedem Fall ab. Scheitert die
    direkte Registrierung, greift der öffentliche API-Aufruf als Fallback
    (mit dann erzwungenem 30-s-Timeout).
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
            "Wikidata Genre V3: %s %s served from cache", entity_type, item_id
        )
        _write_genres(metadata, _CACHE[cache_key], delimiter)
        _refresh_track(track)
        return

    album_key = str(getattr(album, "id", id(album)))
    item_key = f"{album_key}|{cache_key}"
    task_id = f"wikidatagenre_{entity_type}_{item_id}"
    if item_key in _PENDING:
        # Mehrere Tracks teilen sich dieselbe Entity: nur EIN Lookup pro
        # Album + Entity; alle wartenden Metadaten erhalten das Ergebnis.
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
        # WICHTIG: CRITICAL-Task, damit das Album erst finalisiert wird,
        # wenn die Genres vorliegen (siehe _add_album_task und _finish_task).
        _add_album_task(
            api, album, task_id,
            f"Looking up Wikidata genres ({entity_type})",
            create_request,
        )
    except Exception:
        _PENDING.pop(item_key, None)
        api.logger.exception("Wikidata Genre: failed to queue %s", item_id)
        # Der Task kann bereits registriert worden sein, bevor
        # request_factory() fehlgeschlagen ist. In jedem Fall abschließen,
        # sonst blockierte er das Finalisieren des Albums für immer.
        try:
            api.complete_album_task(album, task_id)
        except Exception:
            pass
    else:
        # INFO-Log als Diagnose: bestätigt ohne Debug-Modus, dass die neue
        # Plugin-Version läuft und der Lookup registriert wurde.
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
        # WICHTIG: kein api-Parameter, self.api nicht überschreiben.
        # api.register_options_page() setzt die API als Klassenattribut
        # auf dieser Klasse; der Optionsdialog instanziiert die Seite
        # ohne Argumente. Ein "self.api = api" würde das Klassenattribut
        # mit None überschatten und load()/save() zum Absturz bringen.
        super().__init__(parent)
        self.use_release_group = QCheckBox("Genres der Release Group verwenden")
        self.use_artist = QCheckBox("Genres der Künstler verwenden")
        self.artist_only_if_no_release = QCheckBox(
            "Künstlergenres nur verwenden, wenn keine Release-Group-Genres gefunden wurden"
        )
        self.use_work = QCheckBox("Genres der Werke verwenden")
        self.ignore_artists = QLineEdit()
        self.ignore_genres = QLineEdit()
        self.delimiter = QLineEdit()
        layout = QFormLayout()
        layout.addRow(self.use_release_group)
        layout.addRow(self.use_artist)
        layout.addRow(self.artist_only_if_no_release)
        layout.addRow(self.use_work)
        layout.addRow("Künstler ignorieren (kommagetrennt):", self.ignore_artists)
        layout.addRow("Genres ignorieren (kommagetrennt; /Regex/ möglich):", self.ignore_genres)
        layout.addRow("Genre-Trennzeichen:", self.delimiter)
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
    api.logger.info("Wikidata Genre V3 %s enabled", PLUGIN_VERSION)


def disable():
    """Clear in-memory caches when the plugin is disabled."""
    _PENDING.clear()
    _CACHE.clear()
    _ABANDONED.clear()
