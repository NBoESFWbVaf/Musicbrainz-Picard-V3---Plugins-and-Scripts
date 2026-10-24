# Changelog

Alle nennenswerten Änderungen am Plugin „Scripts & Plugins“ werden in dieser
Datei protokolliert. Das Format orientiert sich an
[Keep a Changelog](https://keepachangelog.com/de/1.1.0/), die Versionierung
folgt Semantic Versioning. Ältere Einträge sind ohne Datum; ab 0.5.0 wird
jede Version datiert.

## [Unveröffentlicht]

## [0.10.1] – 2026-10-24
### Fixed
- Genre- und Script-Änderungen an Tracks (Album- oder Track-Auswahl)
  erschienen zwar in der Albensicht, aber weder im Datei-Detail noch
  wurden sie beim Speichern in die Dateien geschrieben: Picard hält
  die „neuen“ Metadaten jeder Datei separat, und manuelle Änderungen an
  den Track-Metadaten erreichen sie nur über
  `Track.update_file_metadata()` — derselbe Aufruf, den Picard selbst
  beim Matchen einer Datei verwendet. Das Plugin ruft diese
  Synchronisierung jetzt nach jeder geänderten Track-Metadaten für
  alle gematchten Dateien auf. Damit erscheinen Genre und
  Script-Ergebnisse auch im Datei-Detail (Spalte „Neu“) und werden
  mit „Speichern“ in die Dateien geschrieben.

## [0.10.0] – 2026-10-24
### Added
- Zwei Schaltflächen im Genre-Bereich: **„Alle Genre überschreiben“**
  ersetzt vorhandene Genre-Werte der Auswahl durch die im Dropdown
  gewählte Genre, **„Dieses Genre anhängen“** hängt die gewählte Genre
  an vorhandene Genre-Werte an (ohne Dubletten). Beide sind nur bei
  gewählter Genre freigeschaltet.
- Die gewählte Genre bleibt über Aktualisierungen hinweg im Dropdown
  erhalten — so lassen sich mehrere Auswahl-Wechsel im Hauptfenster
  nacheinander mit derselben Genre bearbeiten.

### Changed
- Das Dropdown wendet die Genre nicht mehr automatisch bei der Auswahl
  an; die Anwendung erfolgt jetzt ausschließlich über die beiden
  Schaltflächen (gleiches Muster wie Listen-Auswahl plus Schaltfläche).

## [0.9.0] – 2026-10-24
### Added
- Neuer Bereich „Genre hinzufügen“ zwischen den Listen und dem
  Protokoll: Dropdown mit den Genres aus der neuen Option „Genre-Liste“
  (Textfeld in den Optionen, eine Genre pro Zeile, vorbelegt mit 20
  Hauptstilrichtungen). Wird eine Genre gewählt, wird sie als `genre`-Tag
  auf die im Hauptfenster markierten Objekte gesetzt (überschreibt ein
  vorhandenes Genre-Tag; Speichern wie immer erst mit „Speichern“ in
  Picard). Das Dropdown ist erst einmal leer (Platzhalter „Genre
  wählen …“).
- Neue Anzeige-Option „Genre-Auswahl anzeigen“ — der Genre-Bereich ist
  wie alle anderen Bereiche ein- und ausblendbar.
- Interne Umstellung: Die gemeinsame Metadaten-Schleife für Scripte und
  Genre liegt jetzt in `_apply_to_metadata()` in `window.py`.

## [0.8.2] – 2026-10-24
### Fixed
- Import-Fehler beim Laden des Plugins: `QWIDGETSIZE_MAX` wird von
  PyQt6 nicht aus `QtCore` exportiert (anders als PyQt5). Die Konstante
  ist jetzt als lokaler Wert `_WIDGET_SIZE_MAX` in `window.py`
  definiert (identisch zu Qt: 2**24 − 1 = 16777215).

## [0.8.1] – 2026-10-24
### Fixed
- Beim Vergrößern des Fensters verteilten sich die Elemente innerhalb
  der Listen-Boxen gleichmäßig im neuen Raum (unschöne Optik): Der
  vertikale Splitter gab überschüssigen Höhe an den Listenbereich
  weiter (falscher Stretch-Faktor) statt ans Protokoll. Der
  Listenbereich behält jetzt seine benötigte Höhe — die Einträge,
  Schaltflächen und das Protokoll wandern beim Vergrößern nicht mehr
  auseinander; zusätzlicher Platz geht ausschließlich ans Protokoll.
- Dafür liefert die Liste jetzt eine inhaltsbasierte
  Größen-Schätzung statt des festen Qt-Standardwerts (neue Unterklasse
  `CompactListWidget` mit `sizeHint()` über alle Zeilen), und der
  Listenbereich erhält eine Höchsthöhe aus der Größen-Schätzung der
  größeren Box, sodass ihm der Splitter nie Leerraum zuweisen kann.

## [0.8.0] – 2026-10-24
### Changed
- Die Listen „Tagging-Scripte“ und „Plugin-Aktionen“ sind maximal so
  hoch wie ihr Inhalt: Die gemeinsame Höhe orientiert sich an der
  größeren der beiden Listen — unterhalb des letzten Eintrags bleibt
  kein leerer Raum, der überschüssige Platz fällt dem Protokoll zu.
  Die Begrenzung wird nach jedem Listen-Neuaufbau neu berechnet und
  berücksichtigt auch den eingestellten Zeilenabstand.
- Der Button „Alle aktiven Scripte ausführen“ liegt jetzt unterhalb
  der Script-Liste, rechts neben der Ausführen-Schaltfläche (statt
  in einer Kopfzeile über der Liste).
- „Script ausführen“ heißt jetzt „Gewähltes Script ausführen“.

## [0.7.0] – 2026-10-24
### Added
- Drei neue Anzeige-Optionen (Optionen → Plugins → Scripts & Plugins):
  „Tagging-Scripte anzeigen“, „Plugin-Aktionen anzeigen“ und
  „Protokoll anzeigen“ — jeder Fensterbereich (Script-Liste,
  Aktions-Liste, Protokoll) lässt sich einzeln ein- und ausblenden.
  Alle Optionen sind profilfähig und greifen live in einem offenen
  Fenster.

### Changed
- Die Schaltflächen „Script ausführen“ und „Aktion ausführen“ liegen
  jetzt direkt unter der jeweiligen Liste (rechtsbündig im
  Gruppenfeld-Fuß), nicht mehr in der unteren Button-Leiste. Dort
  verbleiben nur „Aktualisieren“ und „Leeren“.

### Removed
- Option „Zusätzliche Schriftgröße“ (0–5 Punkte) vollständig entfernt:
  Sie funktionierte auf Systemen mit pixel-basierten Schriften
  (z. B. Wayland mit Skalierung) nicht zuverlässig.

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