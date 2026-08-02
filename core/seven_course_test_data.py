"""Compatibility imports for the former seven-course acceptance-pack name."""

from core.cross_discipline_test_data import (
    CROSS_DISCIPLINE_COURSE_IDS,
    CROSS_DISCIPLINE_SOURCES,
    CrossDisciplineAuditReport,
    CrossDisciplineSeedReport,
    audit_cross_discipline_data,
    seed_cross_discipline_data,
)


SEVEN_COURSE_IDS = CROSS_DISCIPLINE_COURSE_IDS
SEVEN_COURSE_SOURCES = CROSS_DISCIPLINE_SOURCES
SevenCourseSeedReport = CrossDisciplineSeedReport
SevenCourseAuditReport = CrossDisciplineAuditReport
seed_seven_course_data = seed_cross_discipline_data
audit_seven_course_data = audit_cross_discipline_data


__all__ = [
    "CROSS_DISCIPLINE_COURSE_IDS",
    "CROSS_DISCIPLINE_SOURCES",
    "SEVEN_COURSE_IDS",
    "SEVEN_COURSE_SOURCES",
    "SevenCourseSeedReport",
    "SevenCourseAuditReport",
    "seed_seven_course_data",
    "audit_seven_course_data",
]
