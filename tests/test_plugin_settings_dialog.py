import unittest

from plugin_settings_dialog import preview_font, resolve_setting_value


class Value:
    def __init__(self, value): self.value = value
    def get(self): return self.value


class TextValue:
    def __init__(self, value): self.value = value
    def get(self, *_args): return self.value


class PluginSettingsDialogHelpersTests(unittest.TestCase):
    def test_choice_and_color_values_resolve_to_plugin_keys(self):
        options = {'azure': 'Azure provider', 'local': 'Local provider'}
        self.assertEqual(resolve_setting_value(Value('Azure provider'), options, 'choice'), 'azure')
        self.assertEqual(resolve_setting_value(Value('#1e1e2e - Dark'), {'#1e1e2e': 'Dark'}, 'color'), '#1e1e2e')

    def test_multiline_and_font_helpers_preserve_expected_values(self):
        self.assertEqual(resolve_setting_value(TextValue('line\n'), None, 'multiline_str'), 'line')
        self.assertEqual(preview_font('Segoe UI', 14, bold=True), ('Segoe UI', 14, 'bold'))
        self.assertEqual(preview_font('Segoe UI', 14), ('Segoe UI', 14))


if __name__ == '__main__':
    unittest.main()
