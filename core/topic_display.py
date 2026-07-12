"""Resolve stable topic identities into user-facing names."""

import re

from utils.constants import topic_alias_values, topic_label, topic_value


def topic_display_name(
    topic,
    course_project=None,
    language: str = "zh",
    fallback_title: str = "",
) -> str:
    """Return a readable title without exposing a storage-oriented topic ID."""
    stable_id = topic_value(topic)
    for project_topic in getattr(course_project, "topics", None) or []:
        if stable_id in topic_alias_values(project_topic):
            title = str(getattr(project_topic, "title", "") or "").strip()
            if title:
                return title

    fallback = str(fallback_title or "").strip()
    if fallback and topic_value(fallback) != stable_id:
        return fallback

    structured_label = str(topic_label(topic, language) or "").strip()
    if structured_label and topic_value(structured_label) != stable_id:
        return structured_label

    readable = re.sub(r"[_-]+", " ", stable_id)
    readable = re.sub(r"\s+", " ", readable).strip()
    if not readable:
        return "General"
    if readable == readable.lower() and re.search(r"[a-z]", readable):
        return readable.title()
    return readable
