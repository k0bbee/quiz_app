"""Course-content extraction helpers for AI question generation."""

from __future__ import annotations

import re

from core.term_extraction import extract_course_terms
from utils.constants import topic_value


def extract_relevant_course_context(
    course_content: str,
    topics: list,
    topic_keywords: dict[str, list[str]] | None = None,
    max_chars: int = 22000,
) -> str:
    """Return topic-relevant Markdown sections for prompt context.

    The source document is a study note rather than a normalized database. This
    function scores Markdown heading sections by selected topic labels and core
    terms, then keeps the strongest chunks under a character budget.
    """
    if not course_content.strip() or not topics:
        return course_content[:max_chars]

    chunks = _split_markdown_sections(course_content)
    selected_terms = _topic_terms(topics, topic_keywords or {})
    selected_terms.extend(_global_key_terms(course_content, limit=18))
    scored = []
    for heading, body in chunks:
        text = f"{heading}\n{body}".strip()
        score = _score_text(text, selected_terms)
        if score > 0:
            scored.append((score, heading, text))

    scored.sort(key=lambda item: item[0], reverse=True)
    picked: list[str] = []
    used = 0
    for _, _, text in scored:
        if used >= max_chars:
            break
        remaining = max_chars - used
        excerpt = text[:remaining]
        picked.append(excerpt)
        used += len(excerpt)

    if not picked:
        return course_content[:max_chars]

    header = "以下是与所选主题最相关的课程内容摘录。只基于这些内容出题，不要引入课外细节。\n\n"
    return header + "\n\n---\n\n".join(picked)


def _split_markdown_sections(content: str) -> list[tuple[str, str]]:
    """Split Markdown into heading-led chunks."""
    sections: list[tuple[str, list[str]]] = []
    current_heading = "课程内容"
    current_lines: list[str] = []
    heading_re = re.compile(r"^#{1,3}\s+")

    for line in content.splitlines():
        if heading_re.match(line):
            if current_lines:
                sections.append((current_heading, current_lines))
            current_heading = line.strip()
            current_lines = []
        else:
            current_lines.append(line)
    if current_lines:
        sections.append((current_heading, current_lines))

    results = []
    for heading, lines in sections:
        body = "\n".join(lines).strip()
        if body:
            results.append((heading, body))
    return results


def _topic_terms(topics: list, topic_keywords: dict[str, list[str]]) -> list[str]:
    terms: list[str] = []
    keyword_lookup = {str(key).lower(): value for key, value in topic_keywords.items()}
    for topic in topics:
        title = topic_value(topic)
        terms.append(title)
        terms.extend(_split_terms(title))
        terms.extend(topic_keywords.get(title, []))
        terms.extend(keyword_lookup.get(title.lower(), []))
    return [term.lower() for term in terms if term]


def _global_key_terms(content: str, limit: int = 20) -> list[str]:
    """Extract general technical terms from the course content itself."""
    return list(extract_course_terms(content, limit=limit))


def _split_terms(text: str) -> list[str]:
    return re.findall(r"[A-Za-z][A-Za-z0-9_+-]{2,}|[\u4e00-\u9fff]{2,8}", text)


def _score_text(text: str, terms: list[str]) -> int:
    lowered = text.lower()
    score = 0
    for term in terms:
        count = lowered.count(term)
        if count:
            score += 3 if len(term) > 4 else 1
            score += min(count, 5)
    return score
