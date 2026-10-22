# Wikidata Genre V3

Picard 3.x plugin port based on the legacy **Wikidata Genre** plugin by Daniel Sobey and Sambhav Kothari. It's vibecoded, use it careful.

## Files

- `MANIFEST.toml` — Picard Plugin API v3 manifest.
- `__init__.py` — plugin implementation and options page.
- `README.md` — installation and behavior notes.
- `.gitignore` — excludes Python cache files.

## Features

- Looks up Wikidata relationships for MusicBrainz release groups, artists, and works.
- Reads genre claims (`P136`) and English labels from Wikidata RDF/XML.
- Adds genres without intentionally removing existing genre values.
- Supports ignored genre names and `/regular expressions/`.
- Supports ignoring genres from selected artist names.
- Configurable source types and genre delimiter.

## Install / test locally

Picard 3 plugins use the v3 plugin layout and are distributed through Git repositories rather than the old single-file/ZIP plugin mechanism.

1. Extract this directory.
2. Initialize a Git repository in `wikidatagenre_v3` (`git init`).
3. In Picard 3, open **Options → Plugins** and use the local plugin/repository installation workflow supported by your Picard build. Point it at the repository directory.
4. Enable **Wikidata Genre V3** and restart Picard if requested.
5. Load a release and inspect Picard's log for `Wikidata Genre V3`.

For development, run a syntax check with `python -m py_compile __init__.py` in an environment with Python 3. The plugin must be tested inside the exact Picard 3 build because it uses Picard's Plugin API and asynchronous web-service interface.

## Options

Open **Options → Plugins → Wikidata Genre V3**:

- Release-group genres: enabled by default.
- Artist genres: enabled by default.
- Artist genres only if no release-group genre was found: enabled by default.
- Work genres: enabled by default.
- Ignore artist names: comma-separated exact names.
- Ignore genres: comma-separated exact names and `/regex/` patterns.
- Genre delimiter: defaults to `; `.

## Notes

- Wikidata lookups use the English labels and apply Python title casing, matching the behavior of the original plugin.
- Network requests are asynchronous. MusicBrainz and Wikidata must be reachable.
- This is a community port; it is not an official MusicBrainz release.
- Original license declaration: WTFPL v2.
