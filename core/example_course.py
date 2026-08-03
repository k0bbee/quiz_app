"""Install the small offline course used by the first-run experience."""

from __future__ import annotations

from datetime import datetime, timezone

from models.course_project import CourseProject, CourseTopic
from models.question import Question
from models.question_set import QuestionSet
from utils.constants import Difficulty, QuestionType


EXAMPLE_COURSE_ID = "example-study-skills"
EXAMPLE_SET_ID = "example-study-skills-set"
_STAMP = datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat()

_TOPICS = (
    ("active_recall", "主动回忆", ["回忆", "检索", "自测"]),
    ("spaced_review", "间隔复习", ["间隔", "复习", "遗忘"]),
    ("error_review", "错题复盘", ["错题", "反馈", "复盘"]),
)


def install_example_course(*, course_manager, question_bank, set_manager):
    """Create or reuse a complete ten-question course without network access."""
    existing = course_manager.get(EXAMPLE_COURSE_ID)
    existing_set = set_manager.get(EXAMPLE_SET_ID)
    if existing is not None and existing_set is not None:
        course_manager.set_current(EXAMPLE_COURSE_ID)
        return existing, existing_set

    project = _build_project()
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


def _build_project() -> CourseProject:
    topics = [
        CourseTopic(topic_id=topic_id, title=title, keywords=list(keywords))
        for topic_id, title, keywords in _TOPICS
    ]
    return CourseProject(
        course_id=EXAMPLE_COURSE_ID,
        title="示例课程：有效学习方法",
        source_folder="",
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
        documents=[],
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
            },
        ))
    return questions
