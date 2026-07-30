import unittest
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.qt

from ui.first_run_controller import FirstRunController


class FirstRunControllerTests(unittest.TestCase):
    def test_practice_candidates_stay_with_the_current_course(self):
        current_set = SimpleNamespace(
            set_id="set-current",
            questions=["q-current"],
            metadata={"course_id": "course-current"},
        )
        other_set = SimpleNamespace(
            set_id="set-other",
            questions=["q-other"],
            metadata={"course_id": "course-other"},
        )
        questions = {
            "q-current": SimpleNamespace(question_id="q-current"),
            "q-other": SimpleNamespace(question_id="q-other"),
        }
        host = SimpleNamespace(
            _current_course_id=lambda: "course-current",
            set_manager=SimpleNamespace(
                load_all=lambda: [current_set, other_set]
            ),
            question_bank=SimpleNamespace(
                get_many=lambda question_ids, course_id: [
                    questions[question_id]
                    for question_id in question_ids
                    if course_id == "course-current"
                ]
            ),
        )

        candidates = FirstRunController(host).practice_candidates()

        self.assertEqual(
            [(current_set, ["q-current"])],
            candidates,
        )


if __name__ == "__main__":
    unittest.main()
