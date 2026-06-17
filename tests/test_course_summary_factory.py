import unittest

from ai.course_summary_factory import create_course_summary_generator, provider_requires_api_key
from ai.course_summarizer import CourseSummaryGenerator


class CourseSummaryFactoryTests(unittest.TestCase):
    def test_local_agent_summary_generator_does_not_need_api_key(self):
        generator = create_course_summary_generator(
            {
                "ai_provider": "local_agent",
                "ai_base_url": "local-agent://auto",
                "ai_model": "codex",
            },
            api_key="",
        )

        self.assertIsInstance(generator, CourseSummaryGenerator)
        self.assertEqual("local-agent://auto", generator.llm_client.base_url)
        self.assertEqual("codex", generator.llm_client.model)

    def test_remote_provider_without_key_returns_none(self):
        generator = create_course_summary_generator(
            {
                "ai_provider": "anthropic",
                "ai_base_url": "https://api.anthropic.com/v1",
                "ai_model": "claude-sonnet-4-6",
            },
            api_key="",
        )

        self.assertIsNone(generator)

    def test_remote_provider_with_key_creates_generator(self):
        generator = create_course_summary_generator(
            {
                "ai_provider": "openai",
                "ai_base_url": "https://api.openai.com/v1",
                "ai_model": "gpt-4.1-mini",
            },
            api_key="sk-test",
        )

        self.assertIsInstance(generator, CourseSummaryGenerator)
        self.assertEqual("https://api.openai.com/v1", generator.llm_client.base_url)

    def test_provider_requires_api_key_rule(self):
        self.assertFalse(provider_requires_api_key({"ai_provider": "local_agent"}))
        self.assertTrue(provider_requires_api_key({"ai_provider": "custom"}))


if __name__ == "__main__":
    unittest.main()
