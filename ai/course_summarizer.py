"""LLM-assisted semantic course summary generation."""

from __future__ import annotations

from core.document_parser import ExtractedDocument
from models.course_project import CourseTopic


class CourseSummaryGenerator:
    """Generate a reusable Markdown course summary with an LLM fallback path."""

    SYSTEM_PROMPT = (
        "You are a course-note synthesis assistant. Create a detailed Markdown "
        "study summary from the supplied courseware text. Use Chinese as the main "
        "language when possible, but preserve important English technical terms. "
        "Stay inside the provided materials and do not invent unsupported facts."
    )

    def __init__(self, llm_client):
        self.llm_client = llm_client
        self.summary_source = "local"
        self.summary_warning = ""

    def generate(
        self,
        title: str,
        docs: list[ExtractedDocument],
        topics: list[CourseTopic],
        local_summary: str,
    ) -> str:
        """Return an LLM summary, falling back to the local summary on failure."""
        self.summary_source = "local"
        self.summary_warning = ""
        messages = self.build_messages(title, docs, topics, local_summary)
        text = self.llm_client.generate(messages, temperature=0.3, max_tokens=12000)
        if not text or not text.strip():
            self.summary_warning = (
                getattr(self.llm_client, "last_error", "")
                or "LLM returned an empty summary."
            )
            return local_summary
        self.summary_source = "llm"
        return text.strip()

    @classmethod
    def build_messages(
        cls,
        title: str,
        docs: list[ExtractedDocument],
        topics: list[CourseTopic],
        local_summary: str,
    ) -> list[dict]:
        topic_lines = "\n".join(
            f"- {topic.title}: {', '.join(topic.keywords[:8]) or 'no extracted keywords'}"
            for topic in topics
        )
        material_lines = []
        for doc in docs:
            excerpt = doc.text[:5000].strip()
            if not excerpt:
                continue
            material_lines.append(
                f"## Source: {doc.title} ({doc.extension})\n"
                f"Warnings: {'; '.join(doc.warnings) if doc.warnings else 'none'}\n\n"
                f"{excerpt}"
            )

        user_prompt = f"""Create a complete reusable course summary for:

Course title: {title}

Inferred topics:
{topic_lines or '- General course review'}

Requirements:
- Output Markdown only.
- Prefer Chinese explanation, with key terms as 中文术语(English Term) where useful.
- Organize by knowledge point, not by file dump.
- Include for each major topic: 核心概念, 推演流程, 实际例子, 易错点, 可考方向, 答题要点.
- Keep concrete formulas, examples, state models, scheduling comparisons, and diagrams if the source material supports them.
- Preserve source semantics. Do not add unrelated textbook content.
- If a source page has OCR/extraction warnings, mention the coverage limitation briefly.

Local fallback summary for reference:
{local_summary[:6000]}

Extracted courseware text:
{chr(10).join(material_lines)[:30000]}
"""
        return [
            {"role": "system", "content": cls.SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
