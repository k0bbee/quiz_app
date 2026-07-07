import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from ai.batch_generator import GenerationWorker
from ai.llm_client import LLMClient
from core.app_errors import AppError
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

    def test_generation_dialog_formats_structured_error_for_users(self):
        dialog = AIGenerationDialog(
            "Cache content",
            {
                "ai_provider": "local_agent",
                "ai_base_url": "local-agent://auto",
                "ai_model": "codex",
            },
            available_topics=["cache"],
        )
        error = AppError(
            code="GEN-QUOTA-001",
            severity="error",
            title_zh="生成未完成",
            title_en="Generation incomplete",
            message_zh="还有题目没有满足当前分布设置。",
            message_en="Some requested quotas are still unmet.",
            action_zh="请重试或放宽权重。",
            action_en="Try again or relax the weights.",
            technical_detail="Missing topic cache: 6",
        )

        with patch("ui.dialogs.ai_generation_dialog.QMessageBox.critical") as critical:
            dialog._on_error(error)

        self.assertIn("GEN-QUOTA-001", dialog.status_label.text())
        self.assertIn("生成未完成", dialog.status_label.text())
        self.assertIn("生成未完成", critical.call_args.args[1])
        self.assertIn("错误码: GEN-QUOTA-001", critical.call_args.args[2])
        self.assertIn("建议操作: 请重试或放宽权重。", critical.call_args.args[2])
        self.assertIn("技术详情: Missing topic cache: 6", critical.call_args.args[2])

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

    def test_openai_compatible_client_retries_without_response_format_when_provider_rejects_it(self):
        class FakeResponse:
            def __init__(self, status_code, payload=None, text=""):
                self.status_code = status_code
                self._payload = payload or {}
                self.text = text

            def json(self):
                return self._payload

        client = LLMClient(
            api_key="sk-test",
            base_url="https://api.example.com/v1",
            model="model",
        )
        first = FakeResponse(
            400,
            text="response_format json_object is not supported by this model",
        )
        second = FakeResponse(
            200,
            payload={"choices": [{"message": {"content": '{"questions":[]}'}}]},
        )

        with patch("ai.llm_client.requests.post", side_effect=[first, second]) as post:
            result = client.generate([{"role": "user", "content": "Return JSON."}])

        self.assertEqual('{"questions":[]}', result)
        self.assertEqual(2, post.call_count)
        self.assertIn("response_format", post.call_args_list[0].kwargs["json"])
        self.assertNotIn("response_format", post.call_args_list[1].kwargs["json"])

    def test_json_extraction_ignores_trailing_braced_explanation_after_object(self):
        client = LLMClient(
            api_key="sk-test",
            base_url="https://api.example.com/v1",
            model="model",
        )
        text = (
            'Here is the JSON:\n{"questions": [{"stem": "I/O interrupt"}]}\n'
            'Note: avoid placeholders such as {not json} in the final answer.'
        )

        with patch.object(client, "generate", return_value=text):
            result = client.generate_with_json([{"role": "user", "content": "Return JSON."}], max_retries=1)

        self.assertEqual({"questions": [{"stem": "I/O interrupt"}]}, result)

    def test_generate_with_json_rejects_top_level_non_object(self):
        client = LLMClient(
            api_key="sk-test",
            base_url="https://api.example.com/v1",
            model="model",
        )

        with patch.object(client, "generate", return_value='["not", "an", "object"]'):
            result = client.generate_with_json([{"role": "user", "content": "Return JSON."}], max_retries=1)

        self.assertIsNone(result)
        self.assertIn("JSON object", client.last_error)

    def test_anthropic_client_accepts_text_payload_without_explicit_text_block_type(self):
        class FakeResponse:
            status_code = 200
            text = ""

            def json(self):
                return {"content": [{"text": '{"questions": []}'}]}

        client = LLMClient(
            api_key="sk-test",
            base_url="https://api.anthropic.com/v1",
            model="claude-test",
        )

        with patch("ai.llm_client.requests.post", return_value=FakeResponse()):
            result = client.generate([{"role": "user", "content": "Return JSON."}])

        self.assertEqual('{"questions": []}', result)
        self.assertEqual("", client.last_error)

    def test_anthropic_client_serializes_structured_json_content(self):
        class FakeResponse:
            status_code = 200
            text = ""

            def json(self):
                return {
                    "content": [
                        {
                            "type": "input_json",
                            "input": {"question_count": 10},
                        }
                    ]
                }

        client = LLMClient(
            api_key="sk-test",
            base_url="https://api.anthropic.com/v1",
            model="claude-test",
        )

        with patch("ai.llm_client.requests.post", return_value=FakeResponse()):
            result = client.generate([{"role": "user", "content": "Return JSON."}])

        self.assertEqual('{"question_count": 10}', result)
        self.assertEqual("", client.last_error)


if __name__ == "__main__":
    unittest.main()
