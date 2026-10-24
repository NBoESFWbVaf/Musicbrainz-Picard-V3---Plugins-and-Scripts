# Changelog

Alle nennenswerten Änderungen am Plugin „Scripts & Plugins“ werden in dieser
Datei protokolliert. Das Format orientiert sich an
[Keep a Changelog](https://keepachangelog.com/de/1.1.0/), die Versionierung
folgt Semantic Versioning. Ältere Einträge sind ohne Datum; ab 0.5.0 wird
jede Version datiert.

## [Unveröffentlicht]

## [0.6.2] – 2026-10-24
### Fixed
- Schriftgröße änderte sich nicht: Auf Systemen, die die Schrift in Pixeln
  statt Punkten definieren (z. B. Wayland mit Skalierung), liefert
  `pointSize()` -1 und der Punkte-Offset wurde übersprungen. Die
  Offset-Berechnung nutzt jetzt `QFontInfo` und rechnet Pixel-Schriften
  über die Bildschirm-DPI um (72 Punkte = 1 Zoll).
- Einstellungen greifen jetzt sofort und ohne Neustart:
  `_apply_display_settings()` läuft bei jeder Aktualisierung (Öffnen,
  Toolbar-Klick, „Aktualisieren“), und das Fenster verbindet sich
  zusätzlich mit dem `setting_changed`-Signal der Plugin-Konfiguration —
  Änderungen im Optionsdialog aktualisieren ein offenes Fenster live.

## [0.6.1] – 2026-10-24
### Fixed
- Absturz beim ersten Öffnen des Fensters behoben: Die V3-API-Doku
  zeigt `api.plugin_config.get(...)` — doch `ProfileConfigSection`
  besitzt in Picard 3.0.2 keine `get()`-Methode, nur `__getitem__`
  (liefert `None` für unregistrierte Optionen). Das Auslesen der
  Optionen läuft jetzt über den neuen Helfer `_config_value()` in
  `helpers.py`, der das abfängt; verwendet in `window.py` und in der
  Einstellungsseite (`options_page.py`), die denselben Fehler hätte.

## [0.6.0] – 2026-10-24
### Added
- Einstellungsseite in den Picard-Optionen unter „Plugins“
  (neue Datei `options_page.py`): Anzeige deaktivierter Scripte an/aus,
  zusätzliche Schriftgröße (0–5 Punkte) und zusätzlicher Zeilenabstand
  (0–30 Pixel). Alle drei Optionen werden über `api.plugin_config`
  registriert und nehmen an Picards Profilsystem teil (pro Profil
  überschreibbar). Geänderte Werte greifen beim nächsten Öffnen des
  Fensters bzw. beim nächsten Listen-Neuaufbau — ohne Picard-Neustart.

## [0.5.1] – 2026-10-24
### Changed
- Code-Struktur: Der Fenster-Code ist in `window.py` ausgelagert, allgemeine
  Hilfsfunktionen und Konstanten in `helpers.py`. Die `__init__.py` enthält
  nur noch den Einstiegspunkt (`enable`/`disable`) und die Toolbar-Integration;
  eingebunden wird per relativer Imports. Keine funktionalen Änderungen.

## [0.5.0] – 2026-10-24
### Added
- Button „Alle aktiven Scripte ausführen“ rechtsbündig über der Script-Liste:
  führt alle aktivierten Tagging-Scripte in Positions-Reihenfolge nacheinander
  auf der Auswahl aus (deaktivierte werden übersprungen).
- Das Protokoll zeichnet Start und Abschluss jedes Scriptes plus eine
  Sammelzeile mit den Gesamtzahlen auf.

## [0.4.0]
### Changed
- Protokoll überarbeitet: Der Start einer Ausführung erscheint in Standardfarbe
  ohne Symbol; erst der Abschluss wird farbig bewertet („✓“ grün bei Erfolg,
  „✗“ rot bei Fehlschlag).
- Das Protokollfenster ist über einen vertikalen Splitter frei in der Höhe
  verstellbar (ersetzt die feste Höchsthöhe von 140 px).

## [0.3.1]
### Fixed
- Absturz beim Klick auf „Aktion ausführen“ (bzw. „Script ausführen“) behoben:
  Das `clicked`-Signal der Schaltflächen übergibt ein `bool` (checked-Argument)
  statt des Listeneintrags, der nur beim Doppelklick mitgeliefert wird. Die
  Slot-Parameter werden daher explizit auf `QListWidgetItem` geprüft.

## [0.3.0]
### Added
- Protokollfenster unterhalb der Listen: zeichnet jede Ausführung mit
  Zeitstempel auf und meldet Erfolg (grün, „✓“) bzw. Fehlschlag (rot, „✗“),
  inklusive Fehlerzählung bei Script-Auswertungen und „Leeren“-Schaltfläche.

## [0.2.1]
### Fixed
- Absturz beim Öffnen des Fensters behoben: Das Attribut
  `_selection_signature` kollidierte mit der gleichnamigen Methode und
  überschattete sie (`TypeError`). Das Attribut heißt nun
  `_last_selection_signature`.

## [0.2.0]
### Added
- Automatische Aktualisierung des Fensters bei Auswahländerungen im
  Hauptfenster (Signal-Hook mit Umfrage-Timer-Fallback).
- Doppelklick in beiden Listen führt Script bzw. Aktion sofort aus.

### Changed
- Größerer Zeilenabstand (+6 px pro Zeile) und um einen Punkt größere Schrift.

## [0.1.0]
### Added
- Fenster mit Liste der Tagging-Scripte und der Plugin-Aktionen; Ausführen
  der Auswahl auf die im Hauptfenster markierten Objekte; Aktualisieren-
  Funktion; Statuszeile.

## [0.0.3]
### Changed
- Fenster als reguläres Qt-Fenster deklariert, damit Maximieren (Schaltfläche
  und Doppelklick auf die Titelleiste) funktioniert.

## [0.0.2]
### Added
- Erste lauffähige Fassung: Toolbar-Schaltfläche öffnet ein Dialogfenster.

## [0.0.1]
### Added
- Initiale Fassung.