"""Install the small offline course used by the first-run experience."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from models.course_project import CourseProject, CourseTopic
from models.question import Question
from models.question_set import QuestionSet
from utils.constants import Difficulty, QuestionType


EXAMPLE_COURSE_ID = "example-study-skills"
EXAMPLE_SET_ID = "example-study-skills-set"
EXAMPLE_MATERIAL_FILENAME = "example-study-skills-material.md"
_STAMP = datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat()

_TOPICS = (
    ("active_recall", "主动回忆", ["回忆", "检索", "自测"]),
    ("spaced_review", "间隔复习", ["间隔", "复习", "遗忘"]),
    ("error_review", "错题复盘", ["错题", "反馈", "复盘"]),
)

_SOURCE_EVIDENCE = {
    "active_recall": {
        "heading": "主动回忆",
        "excerpt": "主动回忆要求学习者在查看答案之前，先尝试从记忆中提取要点或答案。",
    },
    "spaced_review": {
        "heading": "间隔复习",
        "excerpt": "间隔复习把检索安排在逐渐拉开的时间间隔中，并根据回忆结果调整下一次复习。",
    },
    "error_review": {
        "heading": "错题复盘",
        "excerpt": "错题复盘先定位错误原因，再理解修正后的判断，并用新的练习验证掌握情况。",
    },
}

_EXAMPLE_MATERIAL = """# 有效学习方法示例材料

## 主动回忆

主动回忆要求学习者在查看答案之前，先尝试从记忆中提取要点或答案。自测的价值在于暴露哪些内容能够提取、哪些内容还不能提取；只反复阅读而不尝试回答，更接近被动阅读。

## 间隔复习

间隔复习把检索安排在逐渐拉开的时间间隔中，而不是在一次长时间学习里完成所有重复。随着回忆更稳定，复习间隔可以逐渐拉长；遗忘后的重新检索和核对，也能帮助调整下一次复习。

## 错题复盘

错题复盘先定位错误原因，例如概念不清、审题错误或粗心。随后理解修正后的判断，并通过新的检索或练习验证掌握情况。答对但不确定的题目同样值得标记，以便后续温和巩固。
"""


def install_example_course(*, course_manager, question_bank, set_manager):
    """Create or reuse a complete ten-question course without network access."""
    existing = course_manager.get(EXAMPLE_COURSE_ID)
    existing_set = set_manager.get(EXAMPLE_SET_ID)
    material_path = _ensure_example_material(course_manager)
    if (
        existing is not None
        and existing_set is not None
        and _has_source_assets(existing, existing_set, question_bank, material_path)
    ):
        course_manager.set_current(EXAMPLE_COURSE_ID)
        return existing, existing_set

    project = _build_project(material_path)
    questions = _build_questions()
    question_set = QuestionSet(
        set_id=EXAMPLE_SET_ID,
        title={"zh": "示例课程快速练习", "en": "Example Quick Practice"},
        description={
            "zh": "无需配置 AI 的十道示例题，用于熟悉练习和错题复习流程。",
            "en": "Ten offline questions for learning the practice and review flow.",
        },
        topics=[topic_id for topic_id, _title, _keywords in _TOPICS],
        difficulty=Difficulty.MEDIUM,
        estimated_minutes=10,
        questions=[question.question_id for question in questions],
        metadata={"created_at": _STAMP, "source": "builtin_example"},
    )

    saved_question_count = question_bank.save_many(questions)
    if saved_question_count != len(questions):
        raise RuntimeError("The built-in example questions could not be saved.")
    if not set_manager.save(question_set):
        for question in questions:
            question_bank.delete(question.question_id)
        raise RuntimeError("The built-in example question set could not be saved.")
    if not course_manager.save(project, make_current=True):
        set_manager.delete(EXAMPLE_SET_ID)
        for question in questions:
            question_bank.delete(question.question_id)
        raise RuntimeError("The built-in example course could not be saved.")
    return project, question_set


def _ensure_example_material(course_manager) -> Path:
    """Create the deterministic local material used by the offline sample."""
    material_path = Path(course_manager.directory) / EXAMPLE_MATERIAL_FILENAME
    if not material_path.is_file():
        material_path.parent.mkdir(parents=True, exist_ok=True)
        material_path.write_text(_EXAMPLE_MATERIAL, encoding="utf-8", newline="\n")
    return material_path


def _has_source_assets(project, question_set, question_bank, material_path: Path) -> bool:
    """Avoid rewriting an already current offline example installation."""
    if not material_path.is_file():
        return False
    source_paths = {
        str(document.get("path", "") or "").strip()
        for document in project.documents
        if isinstance(document, dict)
    }
    if str(material_path) not in source_paths:
        return False
    questions = question_bank.get_many(
        question_set.questions,
        course_id=EXAMPLE_COURSE_ID,
    )
    return len(questions) == len(question_set.questions) and all(
        any(
            ref.get("source_file") == EXAMPLE_MATERIAL_FILENAME
            for ref in (question.metadata or {}).get("source_refs", [])
            if isinstance(ref, dict)
        )
        for question in questions
    )


def _build_project(material_path: Path) -> CourseProject:
    topics = [
        CourseTopic(topic_id=topic_id, title=title, keywords=list(keywords))
        for topic_id, title, keywords in _TOPICS
    ]
    return CourseProject(
        course_id=EXAMPLE_COURSE_ID,
        title="示例课程：有效学习方法",
        source_folder=str(material_path.parent),
        summary_markdown=(
            "# 示例课程：有效学习方法\n\n"
            "## 学习目标\n"
            "- 认识主动回忆、间隔复习和错题复盘的基本做法。\n"
            "- 通过短练习熟悉答题、结果和错题复习流程。\n\n"
            "## 核心知识点\n"
            "- 主动回忆：先尝试从记忆中回答，再核对资料。\n"
            "- 间隔复习：在逐渐拉开的时间间隔中重复检索。\n"
            "- 错题复盘：定位错误原因，记录修正后的判断并再次练习。\n"
        ),
        summary_path="",
        topics=topics,
        documents=[{"path": str(material_path)}],
        created_at=_STAMP,
        updated_at=_STAMP,
        summary_source="builtin",
        generation_profile_source="builtin",
        generation_profile={
            "question_count": 10,
            "difficulty": "mixed",
            "template": "quick_review",
            "selected_topics": [topic_id for topic_id, _title, _keywords in _TOPICS],
        },
    )


def _build_questions() -> list[Question]:
    rows = (
        ("active_recall", "先合上资料，再尝试写出要点，这种做法最接近什么？", "Close the material and write the key points from memory. What is this?", ["主动回忆", "被动阅读", "装饰笔记", "跳过复习"], ["Active recall", "Passive reading", "Decorative notes", "Skipping review"], "A", "主动回忆要求先从记忆中提取答案。", "Active recall asks you to retrieve an answer before checking the material."),
        ("active_recall", "自测题的主要作用是什么？", "What is the main purpose of a self-test?", ["发现能否提取知识", "增加阅读页数", "替代所有理解", "隐藏错误"], ["Check retrieval", "Increase pages read", "Replace understanding", "Hide errors"], "A", "自测暴露了能够提取和不能提取的部分。", "A self-test reveals what can and cannot be retrieved."),
        ("active_recall", "只反复看同一页而不尝试回答问题，通常属于主动回忆。", "Repeatedly rereading a page without trying to answer is usually active recall.", ["正确", "错误"], ["True", "False"], "false", "没有主动提取答案时，更接近被动阅读。", "Without retrieval, the activity is closer to passive reading."),
        ("spaced_review", "间隔复习的时间间隔通常应该怎样变化？", "How should intervals usually change in spaced review?", ["逐渐拉长", "永远相同", "越来越短", "只在考试前"], ["Gradually lengthen", "Always stay equal", "Become shorter", "Only before exams"], "A", "掌握较稳后可以逐渐拉长复习间隔。", "As recall becomes stable, the review interval can gradually lengthen."),
        ("spaced_review", "遗忘后重新检索并核对答案，能为下一次复习提供什么？", "What can retrieving after forgetting provide for the next review?", ["更有针对性的间隔", "永久免复习", "更长的课件", "自动满分"], ["A better interval", "Permanent exemption", "Longer material", "Automatic full marks"], "A", "复习结果可以帮助调整下一次出现的时间。", "The result can guide when the topic should appear again."),
        ("spaced_review", "间隔复习意味着只在一次长时间学习中完成全部重复。", "Spaced review means completing all repetitions in one long study session.", ["正确", "错误"], ["True", "False"], "false", "间隔复习强调跨时间分散检索。", "Spaced review distributes retrieval across time."),
        ("error_review", "复盘错题时，第一步更适合做什么？", "What is a useful first step when reviewing an incorrect answer?", ["定位错误原因", "立刻删除题目", "只记住选项字母", "跳过解析"], ["Find the cause", "Delete the question", "Remember only the letter", "Skip the explanation"], "A", "先区分概念不清、审题错误或粗心等原因。", "First distinguish a concept gap, misreading, carelessness, or another cause."),
        ("error_review", "把正确答案抄一遍就等于完成了错题复盘。", "Copying the correct answer once is enough to complete error review.", ["正确", "错误"], ["True", "False"], "false", "还需要理解原因并再次检索或练习。", "You also need to understand the cause and retrieve or practice again."),
        ("error_review", "标记“不确定”但答对的题目有什么价值？", "Why is it useful to mark a question as unsure even when correct?", ["提示需要巩固的知识点", "改变正确答案", "跳过所有复习", "删除学习记录"], ["Signals a topic to reinforce", "Changes the answer", "Skips all review", "Deletes history"], "A", "不确定信号可以提醒系统安排温和的巩固。", "An unsure signal can prompt gentle reinforcement."),
        ("error_review", "错题复盘的目标是让同一道题永远不再出现。", "The goal of error review is to ensure the same question never appears again.", ["正确", "错误"], ["True", "False"], "false", "目标是掌握知识并验证迁移，不是简单隐藏题目。", "The goal is to master and transfer the knowledge, not merely hide the question."),
    )
    questions = []
    topic_titles = dict((topic_id, title) for topic_id, title, _keywords in _TOPICS)
    for index, row in enumerate(rows, start=1):
        topic_id, stem_zh, stem_en, options_zh, options_en, answer, explanation_zh, explanation_en = row
        questions.append(Question(
            question_id=f"example-study-skills-{index:02d}",
            type=(QuestionType.TRUE_FALSE if len(options_zh) == 2 else QuestionType.MULTIPLE_CHOICE),
            difficulty=Difficulty.MEDIUM,
            bilingual={
                "zh": {"stem": stem_zh, "options": options_zh, "explanation": explanation_zh},
                "en": {"stem": stem_en, "options": options_en, "explanation": explanation_en},
            },
            correct_answer=answer,
            topic=topic_id,
            metadata={
                "course_id": EXAMPLE_COURSE_ID,
                "topic_title": topic_titles[topic_id],
                "created_at": _STAMP,
                "source": "builtin_example",
                "source_refs": [
                    {
                        "chunk_id": f"example-{topic_id}",
                        "source_file": EXAMPLE_MATERIAL_FILENAME,
                        **_SOURCE_EVIDENCE[topic_id],
                    }
                ],
            },
        ))
    return questions
