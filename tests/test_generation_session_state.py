import unittest

from core.generation_session_state import GenerationStage, GenerationSessionState


class GenerationSessionStateTests(unittest.TestCase):
    def test_stage_transitions_preserve_reviewable_partial_results(self):
        state = GenerationSessionState()

        self.assertEqual(GenerationStage.CONFIGURING, state.stage)
        state.start()
        self.assertEqual(GenerationStage.RUNNING, state.stage)
        state.keep_partial_results()
        self.assertEqual(GenerationStage.PARTIAL, state.stage)
        state.request_review()
        self.assertEqual(GenerationStage.REVIEW_PENDING, state.stage)

    def test_failure_and_cancellation_are_terminal_until_a_new_run_starts(self):
        state = GenerationSessionState()

        state.start()
        state.fail()
        self.assertEqual(GenerationStage.FAILED, state.stage)
        state.cancel()
        self.assertEqual(GenerationStage.FAILED, state.stage)
        state.start()
        self.assertEqual(GenerationStage.RUNNING, state.stage)
        state.cancel()
        self.assertEqual(GenerationStage.CANCELLED, state.stage)

    def test_failure_with_retained_questions_can_explicitly_reopen_review(self):
        state = GenerationSessionState()

        state.start()
        state.fail()
        state.recover_for_review()

        self.assertEqual(GenerationStage.REVIEW_PENDING, state.stage)


if __name__ == "__main__":
    unittest.main()
