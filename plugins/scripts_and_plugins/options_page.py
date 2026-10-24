"""Einstellungsseite für das Plugin „Scripts & Plugins“.

Die Seite erscheint in den Picard-Optionen unter „Plugins“ und bietet
die Konfiguration für das Script-und-Plugins-Fenster an.
"""

from typing import ClassVar

from PyQt6.QtWidgets import (
    QCheckBox,
    QFormLayout,
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
        "font_size_offset": {"widgets": ["font_size_offset_spin"]},
        "list_row_spacing": {"widgets": ["list_row_spacing_spin"]},
    }

    def __init__(self, parent=None):
        super().__init__(parent)

        self.show_disabled_scripts_check = QCheckBox(
            "Deaktivierte Scripte in der Liste anzeigen", self
        )
        self.font_size_offset_spin = QSpinBox(self)
        self.font_size_offset_spin.setRange(0, 5)
        self.font_size_offset_spin.setSuffix(" Punkt(e)")
        self.list_row_spacing_spin = QSpinBox(self)
        self.list_row_spacing_spin.setRange(0, 30)
        self.list_row_spacing_spin.setSuffix(" Pixel")

        form = QFormLayout()
        form.addRow(self.show_disabled_scripts_check)
        form.addRow("Zusätzliche Schriftgröße:", self.font_size_offset_spin)
        form.addRow("Zusätzlicher Zeilenabstand:", self.list_row_spacing_spin)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addStretch(1)

    def load(self):
        """Einstellungen aus der Plugin-Konfiguration in die Widgets laden."""
        self.show_disabled_scripts_check.setChecked(
            _config_value(self.api.plugin_config, "show_disabled_scripts", True)
        )
        self.font_size_offset_spin.setValue(
            _config_value(self.api.plugin_config, "font_size_offset", 1)
        )
        self.list_row_spacing_spin.setValue(
            _config_value(self.api.plugin_config, "list_row_spacing", 6)
        )

    def save(self):
        """Widget-Werte in die Plugin-Konfiguration schreiben."""
        self.api.plugin_config["show_disabled_scripts"] = (
            self.show_disabled_scripts_check.isChecked()
        )
        self.api.plugin_config["font_size_offset"] = (
            self.font_size_offset_spin.value()
        )
        self.api.plugin_config["list_row_spacing"] = (
            self.list_row_spacing_spin.value()
        )