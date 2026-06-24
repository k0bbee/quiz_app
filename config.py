"""Application configuration — file paths, defaults, constants."""

import os

# Base directory of the quiz_app package
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ── Data directories ──────────────────────────────────────────
DATA_DIR = os.path.join(BASE_DIR, "data")

# Course projects: internal storage for imported courses
#   data/courses/<course_id>/project.json   — CourseProject metadata
#   data/courses/<course_id>/summary.md     — generated summary
#   data/courses/<course_id>/source/        — copied source files
COURSES_DIR = os.path.join(DATA_DIR, "courses")
COURSE_PROJECTS_DIR = COURSES_DIR  # alias for backward compatibility

# Questions: individual JSON files, reusable across sets
QUESTIONS_DIR = os.path.join(DATA_DIR, "questions")

# Question sets: collections referencing question IDs
QUESTION_SETS_DIR = os.path.join(DATA_DIR, "question_sets")

# Progress: per-session records
PROGRESS_DIR = os.path.join(DATA_DIR, "progress")

# Settings
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
API_KEY_STORE_FILE = os.path.join(DATA_DIR, ".api_key.dpapi")

# Active course pointer
CURRENT_COURSE_FILE = os.path.join(DATA_DIR, "current_course.json")

# ── External course materials ─────────────────────────────────
# Users can place original course files (pptx/pdf/docx/md/txt)
# anywhere. The recommended location is a "courses/" folder next
# to quiz_app/, with one subfolder per course:
#
#   courses/
#     Computer-Systems-2B/
#       *.pptx
#       *.pdf
#     Another-Course/
#       *.md
#       *.txt
#
# The app imports from any folder the user selects via the
# Course Materials screen. Source files are COPIED into the
# internal data/courses/<course_id>/source/ directory so the
# originals are never modified.

# Default course materials search path (optional convenience)
COURSES_SEARCH_DIR = os.path.join(os.path.dirname(BASE_DIR), "courses")

# ── Default settings ──────────────────────────────────────────
DEFAULT_SETTINGS = {
    "language": "zh",
    "ai_api_key": "",
    "ai_provider": "anthropic",
    "ai_base_url": "https://api.anthropic.com/v1",
    "ai_model": "claude-sonnet-4-6",
    "default_question_count": 15,
    "default_difficulty": "medium",
    "show_timer": False,
}

# ── Application metadata ──────────────────────────────────────
APP_NAME = "Course Quiz Studio"
APP_NAME_ZH = "课程刷题工具"
APP_VERSION = "1.0.0"
