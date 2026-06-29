from core.mastery_overrides import MasteryOverrideStore


def test_mastered_topics_persist_per_course(tmp_path):
    path = tmp_path / "mastery_overrides.json"
    store = MasteryOverrideStore(path)

    store.mark_topic_mastered("course-a", "Cache Mapping")

    assert store.is_topic_mastered("course-a", "cache mapping")
    assert not store.is_topic_mastered("course-b", "cache mapping")
    assert not store.is_topic_mastered("course-a", "Virtual Memory")

    reloaded = MasteryOverrideStore(path)
    assert reloaded.is_topic_mastered("course-a", "Cache Mapping")

    reloaded.unmark_topic_mastered("course-a", "Cache Mapping")

    assert not MasteryOverrideStore(path).is_topic_mastered("course-a", "Cache Mapping")


def test_clear_removes_all_mastery_overrides(tmp_path):
    path = tmp_path / "mastery_overrides.json"
    store = MasteryOverrideStore(path)
    store.mark_topic_mastered("course-a", "cache")
    store.mark_topic_mastered("course-b", "process")

    store.clear()

    reloaded = MasteryOverrideStore(path)
    assert not reloaded.is_topic_mastered("course-a", "cache")
    assert not reloaded.is_topic_mastered("course-b", "process")
