from models.progress import AnswerRecord, ProgressRecord, SessionSummary
from models.question import Question
from utils.constants import Difficulty, QuestionType
from core.mastery import build_question_mastery, build_topic_mastery, prioritize_review_question_ids
from core.progress_tracker import ProgressManager


def _record(progress_id: str, started_at: str, answers: list[AnswerRecord]) -> ProgressRecord:
    return ProgressRecord(
        progress_id=progress_id,
        set_id="set-review",
        language="zh",
        started_at=started_at,
        completed_at=started_at,
        status="completed",
        answers=answers,
        summary=SessionSummary.compute(
            answers,
            total_questions=len(answers),
            total_time=sum(answer.time_spent_seconds for answer in answers),
        ),
    )


def _answer(question_id: str, is_correct: bool, index: int = 0) -> AnswerRecord:
    return AnswerRecord(
        question_id=question_id,
        index_in_session=index,
        user_answer="A" if is_correct else "B",
        is_correct=is_correct,
    )


def _question(question_id: str, topic: str) -> Question:
    return Question(
        question_id=question_id,
        type=QuestionType.MULTIPLE_CHOICE,
        difficulty=Difficulty.MEDIUM,
        bilingual={
            "zh": {"stem": question_id, "options": ["A. one", "B. two"], "explanation": "解释"},
            "en": {"stem": question_id, "options": ["A. one", "B. two"], "explanation": "Explanation"},
        },
        correct_answer="A",
        topic=topic,
    )


def test_prioritizes_repeated_and_recent_wrong_questions_before_recovered_old_mistakes():
    records = [
        _record(
            "old",
            "2026-06-01T00:00:00+00:00",
            [
                _answer("repeated-wrong", False, 0),
                _answer("recovered", False, 1),
                _answer("single-old-wrong", False, 2),
            ],
        ),
        _record(
            "middle",
            "2026-06-10T00:00:00+00:00",
            [
                _answer("recovered", True, 0),
                _answer("repeated-wrong", False, 1),
            ],
        ),
        _record(
            "recent",
            "2026-06-20T00:00:00+00:00",
            [
                _answer("recovered", True, 0),
                _answer("repeated-wrong", False, 1),
            ],
        ),
    ]

    prioritized = prioritize_review_question_ids(records)

    assert prioritized[0] == "repeated-wrong"
    assert prioritized.index("single-old-wrong") < prioritized.index("recovered")
    assert set(prioritized) == {"repeated-wrong", "single-old-wrong", "recovered"}


def test_mastery_state_tracks_streaks_accuracy_and_excludes_never_wrong_questions_from_review():
    records = [
        _record(
            "first",
            "2026-06-01T00:00:00+00:00",
            [
                _answer("cache", False, 0),
                _answer("process", True, 1),
            ],
        ),
        _record(
            "second",
            "2026-06-02T00:00:00+00:00",
            [
                _answer("cache", True, 0),
                _answer("process", True, 1),
            ],
        ),
    ]

    states = build_question_mastery(records)
    prioritized = prioritize_review_question_ids(records)

    assert states["cache"].attempts == 2
    assert states["cache"].correct == 1
    assert states["cache"].recent_correct_streak == 1
    assert states["cache"].recent_wrong_streak == 0
    assert 0 < states["cache"].mastery_score < states["process"].mastery_score
    assert prioritized == ["cache"]


def test_progress_manager_returns_prioritized_review_ids(tmp_path):
    progress_manager = ProgressManager(str(tmp_path / "progress"))
    for record in [
        _record(
            "old",
            "2026-06-01T00:00:00+00:00",
            [
                _answer("recovered", False, 0),
                _answer("repeated-wrong", False, 1),
            ],
        ),
        _record(
            "recent",
            "2026-06-20T00:00:00+00:00",
            [
                _answer("recovered", True, 0),
                _answer("repeated-wrong", False, 1),
            ],
        ),
    ]:
        progress_manager.save(record)

    prioritized = progress_manager.get_prioritized_review_question_ids()

    assert prioritized == ["repeated-wrong", "recovered"]


def test_build_topic_mastery_aggregates_question_states_by_topic():
    records = [
        _record(
            "first",
            "2026-06-01T00:00:00+00:00",
            [
                _answer("cache-a", False, 0),
                _answer("cache-b", True, 1),
                _answer("process-a", True, 2),
            ],
        ),
        _record(
            "second",
            "2026-06-02T00:00:00+00:00",
            [
                _answer("cache-a", False, 0),
                _answer("process-a", True, 1),
            ],
        ),
    ]
    questions = [
        _question("cache-a", "cache"),
        _question("cache-b", "cache"),
        _question("process-a", "process"),
    ]

    states = build_topic_mastery(records, questions)

    assert states["cache"].topic == "cache"
    assert states["cache"].question_count == 2
    assert states["cache"].attempts == 3
    assert states["cache"].correct == 1
    assert states["cache"].wrong_question_count == 1
    assert states["cache"].mastery_score < states["process"].mastery_score
    assert states["process"].mastery_score >= 0.8
