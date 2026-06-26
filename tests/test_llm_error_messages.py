import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from ai.batch_generator import GenerationWorker
from ai.llm_client import LLMClient
from ui.dialogs.ai_generation_dialog import AIGenerationDialog


_APP = QApplication.instance() or QApplication([])


class LLMErrorMessageTests(unittest.TestCase):
    def test_local_agent_records_actionable_error_when_no_cli_is_available(self):
        client = LLMClient(api_key="", base_url="local-agent://auto", model="auto")

        with patch("ai.llm_client.shutil.which", return_value=None):
            result = client.generate([{"role": "user", "content": "Generate JSON."}])

        self.assertIsNone(result)
        self.assertIn("No supported local agent CLI found", client.last_error)

    def test_generation_worker_emits_client_error_detail(self):
        class FailingClient:
            model = "test-model"
            last_error = "OpenAI-compatible API error 401: invalid API key"

            def generate_with_json(self, *_args, **_kwargs):
                return None

        worker = GenerationWorker(
            FailingClient(),
            course_content="Cache content",
            topics=["cache"],
            count=3,
            difficulty="medium",
        )
        errors = []
        worker.error.connect(errors.append)

        worker.run()

        self.assertEqual(["OpenAI-compatible API error 401: invalid API key"], errors)

    def test_generation_dialog_keeps_error_status_after_worker_finished(self):
        dialog = AIGenerationDialog(
            "Cache content",
            {
                "ai_provider": "local_agent",
                "ai_base_url": "local-agent://auto",
                "ai_model": "codex",
            },
            available_topics=["cache"],
        )

        with patch("ui.dialogs.ai_generation_dialog.QMessageBox.critical"):
            dialog._on_error("OpenAI-compatible API error 401: invalid API key")
        dialog._on_finished()

        self.assertIn("invalid API key", dialog.status_label.text())
        self.assertNotIn("No questions were generated", dialog.status_label.text())

    def test_client_blocks_unsafe_remote_endpoint_before_network_request(self):
        client = LLMClient(
            api_key="sk-test",
            base_url="http://llm.example.com/v1",
            model="model",
        )

        with patch("ai.llm_client.requests.post") as post:
            result = client.generate([{"role": "user", "content": "Return JSON."}])

        self.assertIsNone(result)
        self.assertFalse(post.called)
        self.assertIn("HTTPS", client.last_error)


if __name__ == "__main__":
    unittest.main()
