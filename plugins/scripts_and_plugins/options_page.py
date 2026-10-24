"""Einstellungsseite für das Plugin „Scripts & Plugins“.

Die Seite erscheint in den Picard-Optionen unter „Plugins“ und bietet
die Konfiguration für das Script-und-Plugins-Fenster an.
"""

from typing import ClassVar

from PyQt6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QPlainTextEdit,
    QSpinBox,
    QVBoxLayout,
)

from picard.plugin3.api import OptionsPage, PageOptionConfigs, t_

from .helpers import _config_value


class ScriptsPluginsOptionsPage(OptionsPage):
    """Optionen → Plugins → Scripts & Plugins."""

    NAME = "scripts_and_plugins"
    TITLE = t_("options.page_title", "Scripts & Plugins")
    PARENT = "plugins"

    # Widget-Zuordnung für die Profil-Hervorhebung: pro Option die
    # Widget-Attribute, die sie im Optionsdialog darstellen.
    OPTIONS: ClassVar[PageOptionConfigs] = {
        "show_disabled_scripts": {"widgets": ["show_disabled_scripts_check"]},
        "show_scripts_list": {"widgets": ["show_scripts_list_check"]},
        "show_actions_list": {"widgets": ["show_actions_list_check"]},
        "show_log": {"widgets": ["show_log_check"]},
        "show_genre": {"widgets": ["show_genre_check"]},
        "show_cover_info": {"widgets": ["show_cover_info_check"]},
        "genre_list": {"widgets": ["genre_list_edit"]},
        "list_row_spacing": {"widgets": ["list_row_spacing_spin"]},
    }

    def __init__(self, parent=None):
        super().__init__(parent)

        self.show_disabled_scripts_check = QCheckBox(
            "Deaktivierte Scripte in der Liste anzeigen", self
        )
        self.show_scripts_list_check = QCheckBox(
            "Tagging-Scripte anzeigen", self
        )
        self.show_actions_list_check = QCheckBox(
            "Plugin-Aktionen anzeigen", self
        )
        self.show_log_check = QCheckBox(
            "Protokoll anzeigen", self
        )
        self.show_genre_check = QCheckBox(
            "Genre-Auswahl und Nummerierung anzeigen", self
        )
        self.show_cover_info_check = QCheckBox(
            "Cover-Informationen anzeigen", self
        )
        self.show_cover_info_check.setToolTip(
            "Maße, Dateigröße und Dateityp der Cover-Bilder im "
            "Cover-Panel des Hauptfensters anzeigen"
        )
        self.genre_list_edit = QPlainTextEdit(self)
        self.genre_list_edit.setPlaceholderText(
            "Eine Genre pro Zeile …"
        )
        self.genre_list_edit.setMinimumHeight(120)
        self.list_row_spacing_spin = QSpinBox(self)
        self.list_row_spacing_spin.setRange(0, 30)
        self.list_row_spacing_spin.setSuffix(" Pixel")

        form = QFormLayout()
        form.addRow(self.show_disabled_scripts_check)
        form.addRow(self.show_scripts_list_check)
        form.addRow(self.show_actions_list_check)
        form.addRow(self.show_log_check)
        form.addRow(self.show_genre_check)
        form.addRow(self.show_cover_info_check)
        form.addRow("Genre-Liste (eine Genre pro Zeile):", self.genre_list_edit)
        form.addRow("Zusätzlicher Zeilenabstand:", self.list_row_spacing_spin)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addStretch(1)

    def load(self):
        """Einstellungen aus der Plugin-Konfiguration in die Widgets laden."""
        self.show_disabled_scripts_check.setChecked(
            _config_value(self.api.plugin_config, "show_disabled_scripts", True)
        )
        self.show_scripts_list_check.setChecked(
            _config_value(self.api.plugin_config, "show_scripts_list", True)
        )
        self.show_actions_list_check.setChecked(
            _config_value(self.api.plugin_config, "show_actions_list", True)
        )
        self.show_log_check.setChecked(
            _config_value(self.api.plugin_config, "show_log", True)
        )
        self.show_genre_check.setChecked(
            _config_value(self.api.plugin_config, "show_genre", True)
        )
        self.show_cover_info_check.setChecked(
            _config_value(self.api.plugin_config, "show_cover_info", True)
        )
        genre_text = _config_value(self.api.plugin_config, "genre_list", "")
        if not isinstance(genre_text, str):
            genre_text = ""
        self.genre_list_edit.setPlainText(genre_text)
        self.list_row_spacing_spin.setValue(
            _config_value(self.api.plugin_config, "list_row_spacing", 6)
        )

    def save(self):
        """Widget-Werte in die Plugin-Konfiguration schreiben."""
        self.api.plugin_config["show_disabled_scripts"] = (
            self.show_disabled_scripts_check.isChecked()
        )
        self.api.plugin_config["show_scripts_list"] = (
            self.show_scripts_list_check.isChecked()
        )
        self.api.plugin_config["show_actions_list"] = (
            self.show_actions_list_check.isChecked()
        )
        self.api.plugin_config["show_log"] = (
            self.show_log_check.isChecked()
        )
        self.api.plugin_config["show_genre"] = (
            self.show_genre_check.isChecked()
        )
        self.api.plugin_config["show_cover_info"] = (
            self.show_cover_info_check.isChecked()
        )
        self.api.plugin_config["genre_list"] = self.genre_list_edit.toPlainText()
        self.api.plugin_config["list_row_spacing"] = (
            self.list_row_spacing_spin.value()
        )