import unittest

from core.app_errors import AppError, format_app_error


class AppErrorTests(unittest.TestCase):
    def test_app_error_formats_localized_user_message_with_code_action_and_detail(self):
        error = AppError(
            code="GEN-QUOTA-001",
            severity="error",
            title_zh="生成未完成",
            title_en="Generation incomplete",
            message_zh="还有 6 道题没有满足当前分布设置。",
            message_en="6 questions still do not satisfy the requested distribution.",
            action_zh="请重试，或减少题目数量，或放宽权重。",
            action_en="Try again, reduce the count, or relax the weights.",
            technical_detail="Missing topic cache: 6",
        )

        zh = format_app_error(error, "zh")
        en = format_app_error(error, "en")

        self.assertIn("生成未完成", zh)
        self.assertIn("请重试", zh)
        self.assertIn("错误码: GEN-QUOTA-001", zh)
        self.assertIn("技术详情: Missing topic cache: 6", zh)

        self.assertIn("Generation incomplete", en)
        self.assertIn("Try again", en)
        self.assertIn("Error code: GEN-QUOTA-001", en)
        self.assertIn("Details: Missing topic cache: 6", en)


if __name__ == "__main__":
    unittest.main()
