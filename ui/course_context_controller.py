"""Coordinate active-course context across application workspaces."""

from __future__ import annotations


class CourseContextController:
    """Keep course identity, scope and dependent screen refreshes consistent."""

    def __init__(self, host) -> None:
        self._host = host

    def current_course_id(self) -> str:
        course = self._host.course_manager.current()
        return course.course_id if course else ""

    def course_changed(self) -> None:
        host = self._host
        self.sync_home()
        self.sync_topic_screen()
        self.sync_question_bank()
        self.sync_progress()
        self.refresh_results_retry_availability()
        host._refresh_first_run()
        host._on_language_changed()

    def question_bank_changed(self) -> None:
        host = self._host
        host.question_bank.clear_cache()
        host.home_screen.refresh()
        host.topic_screen.refresh()
        self.refresh_results_retry_availability()
        host._refresh_first_run()

    def refresh_results_retry_availability(self) -> None:
        host = self._host
        record = getattr(host.results_screen, "current_record", None)
        if record is None:
            return
        answer_ids = [answer.question_id for answer in record.answers]
        available = host.question_bank.get_many(
            answer_ids,
            course_id=self.current_course_id(),
        )
        question_set = (
            host.set_manager.get(record.set_id) if record.set_id else None
        )
        set_questions = (
            host.question_bank.get_many(question_set.questions)
            if question_set is not None
            else []
        )
        host.results_screen.set_retry_availability(
            [question.question_id for question in available],
            can_retry_all=bool(question_set is not None and set_questions),
        )

    def generation_context(self) -> tuple[str, list, object]:
        host = self._host
        gm = host.lang_manager.get_text
        course = host.course_manager.current()
        if course:
            scoped_topics = getattr(course, "exam_topics", None)
            topics = list(
                scoped_topics()
                if callable(scoped_topics)
                else getattr(course, "topics", []) or []
            )
            if (
                not topics
                and getattr(course, "exam_scope_mode", "all") != "selected"
            ):
                topics = [gm("综合", "General")]
            return course.summary_markdown, topics, course
        return "", [], None

    def sync_topic_screen(self) -> None:
        host = self._host
        course = host.course_manager.current()
        host.topic_screen.set_current_course(
            course.course_id if course else "",
            course.title if course else "",
        )

    def sync_question_bank(self) -> None:
        host = self._host
        if host._question_bank_screen is None:
            return
        host._question_bank_screen.set_current_course(self.current_course_id())

    def sync_home(self) -> None:
        host = self._host
        course = host.course_manager.current()
        exam_topic_ids = None
        exam_scope_weights = {}
        if course and getattr(course, "exam_scope_mode", "all") == "selected":
            scoped_topics = getattr(course, "exam_topics", None)
            topics = (
                scoped_topics()
                if callable(scoped_topics)
                else getattr(course, "topics", [])
            )
            exam_topic_ids = {topic.topic_id for topic in topics}
        if course:
            allowed_topics = {
                topic.topic_id
                for topic in (
                    course.exam_topics()
                    if callable(getattr(course, "exam_topics", None))
                    else getattr(course, "topics", [])
                )
            }
            profile = getattr(course, "generation_profile", {}) or {}
            raw_weights = (
                profile.get("topic_weights", {})
                if isinstance(profile, dict)
                else {}
            )
            if isinstance(raw_weights, dict):
                exam_scope_weights = {
                    str(topic_id): weight
                    for topic_id, weight in raw_weights.items()
                    if str(topic_id) in allowed_topics
                }
        host.home_screen.set_current_course(
            course.course_id if course else "",
            course.title if course else "",
            exam_topic_ids,
            exam_scope_weights=exam_scope_weights,
        )
        host._update_home_resume_draft()

    def sync_progress(self) -> None:
        self._host.progress_screen.set_current_course(
            self.current_course_id()
        )
