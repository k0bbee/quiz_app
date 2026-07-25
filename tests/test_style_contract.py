import re
import unittest
from pathlib import Path


class StyleContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qss = Path("style.qss").read_text(encoding="utf-8").lower()

    def test_base_theme_tokens_and_default_button_role(self):
        for token in (
            "#181818",
            "#1f1f1f",
            "#252526",
            "#313131",
            "#0078d4",
            "#007fd4",
            "#cccccc",
        ):
            self.assertIn(token, self.qss)
        self.assertRegex(
            self.qss,
            r"qdialog[^\{]*\{[^}]*background-color:\s*#1f1f1f",
        )
        self.assertIn("qpushbutton#primarybutton", self.qss)
        self.assertIn(
            'qpushbutton#secondarybutton[marked="true"]',
            self.qss,
        )
        self.assertIn("qlabel#settingsconnectionstatus", self.qss)

        default_rule = re.search(
            r"qpushbutton\s*\{(?P<body>[^}]*)\}",
            self.qss,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(default_rule)
        self.assertIn("#313131", default_rule.group("body"))
        self.assertNotIn("#0078d4", default_rule.group("body"))

    def test_buttons_define_soft_shape_and_complete_interaction_states(self):
        default_rule = re.search(
            r"qpushbutton\s*\{(?P<body>[^}]*)\}",
            self.qss,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(default_rule)
        self.assertRegex(
            default_rule.group("body"),
            r"border-radius:\s*(1[0-9]|[2-9][0-9])px",
        )
        self.assertIn("outline: none", default_rule.group("body"))

        for selector in (
            "qpushbutton:hover",
            "qpushbutton:pressed",
            "qpushbutton:focus",
            "qpushbutton#primarybutton:hover",
            "qpushbutton#primarybutton:pressed",
            "qpushbutton#primarybutton:focus",
            "qpushbutton#secondarybutton:hover",
            "qpushbutton#secondarybutton:pressed",
            "qpushbutton#secondarybutton:focus",
            "qpushbutton#dangerbutton:hover",
            "qpushbutton#dangerbutton:pressed",
            "qpushbutton#dangerbutton:focus",
        ):
            self.assertIn(selector, self.qss)

    def test_menus_define_shape_and_complete_interaction_states(self):
        menu_bar_item = re.search(
            r"qmenubar::item\s*\{(?P<body>[^}]*)\}",
            self.qss,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(menu_bar_item)
        self.assertIn("border-radius", menu_bar_item.group("body"))
        self.assertIn("border:", menu_bar_item.group("body"))

        menu_item = re.search(
            r"qmenu::item\s*\{(?P<body>[^}]*)\}",
            self.qss,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(menu_item)
        self.assertIn("border:", menu_item.group("body"))
        self.assertIn("border-radius", menu_item.group("body"))

        for selector in (
            "qmenubar::item:selected",
            "qmenubar::item:pressed",
            "qmenubar::item:open",
            "qmenu::item:selected",
            "qmenu::item:pressed",
            "qtoolbar qpushbutton:hover",
            "qtoolbar qpushbutton:pressed",
            "qtoolbar qpushbutton:focus",
        ):
            self.assertIn(selector, self.qss)

    def test_contextual_controls_define_visible_state_feedback(self):
        for selector in (
            'qpushbutton[homeaction="primary"]:hover',
            'qpushbutton[homeaction="primary"]:pressed',
            'qpushbutton[homeaction="primary"]:focus',
            'qpushbutton[homeaction="secondary"]:hover',
            'qpushbutton[homeaction="secondary"]:pressed',
            'qpushbutton[homeaction="secondary"]:focus',
        ):
            self.assertIn(selector, self.qss)

        for role in ("primary", "secondary"):
            with self.subTest(home_action=role):
                pressed = re.search(
                    rf'qpushbutton\[homeaction="{role}"\]:pressed\s*'
                    r"\{(?P<body>[^}]*)\}",
                    self.qss,
                    flags=re.DOTALL,
                )
                self.assertIsNotNone(pressed)
                self.assertIn("padding-top", pressed.group("body"))
                self.assertIn("padding-bottom", pressed.group("body"))
                self.assertIn("border-color", pressed.group("body"))

        toggle_rule = re.search(
            r"qcheckbox#quizuncertaincheck,\s*qcheckbox#quizreviewcheck\s*"
            r"\{(?P<body>[^}]*)\}",
            self.qss,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(toggle_rule)
        self.assertRegex(
            toggle_rule.group("body"),
            r"border-radius:\s*([6-9]|[1-9][0-9])px",
        )
        for property_name in ("background-color:", "border:", "padding:"):
            self.assertIn(property_name, toggle_rule.group("body"))
        for selector in (
            "qcheckbox#quizuncertaincheck:hover",
            "qcheckbox#quizreviewcheck:hover",
            "qcheckbox#quizuncertaincheck:checked",
            "qcheckbox#quizreviewcheck:checked",
        ):
            self.assertIn(selector, self.qss)

        selectors = {
            "quiz_mode": (
                "qpushbutton#quizmodeoption",
                "qpushbutton#quizmodeoption:checked",
                "qpushbutton#quizmodeoption:hover",
                "qpushbutton#quizmodeoption:focus",
            ),
            "review_tabs": (
                "qtabwidget::pane",
                "qtabbar::tab:selected",
                "qtabbar::tab:hover",
                "qtabbar::tab:focus",
            ),
        }
        for control, required_selectors in selectors.items():
            with self.subTest(control=control):
                for selector in required_selectors:
                    self.assertIn(selector, self.qss)

    def test_quiz_cards_use_soft_baicizhan_style_borders(self):
        card_rule = re.search(
            r"qframe#quizpreviewpane,\s*qframe#quizpracticecard,\s*"
            r"qframe#questioncard,\s*qframe#reviewcard,\s*"
            r"qframe#feedbackframe\s*\{(?P<body>[^}]*)\}",
            self.qss,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(card_rule)
        self.assertRegex(
            card_rule.group("body"),
            r"border-radius:\s*(1[6-9]|[2-9][0-9])px",
        )
        self.assertIn("#4a4a4a", card_rule.group("body"))
        self.assertIn("qframe#quizpreviewpane", self.qss)
        self.assertIn("qframe#feedbackframe", self.qss)


if __name__ == "__main__":
    unittest.main()
