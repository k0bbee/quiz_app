"""Build generic course projects from imported materials."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from core.course_index import attach_index_to_project
from core.course_build_pipeline import CourseBuildPipeline
from core.document_parser import DocumentParser, ExtractedDocument
from core.term_extraction import extract_course_terms, is_low_value_keyword
from core.background_task import TaskControl
from core.course_parse_checkpoint import CourseParseCheckpointStore
from models.course_project import CourseProject, CourseProjectManager, CourseTopic
from utils.logger import warning
from utils.constants import topic_alias_values, topic_value
from ai.course_generation_profile import (
    CourseGenerationProfileGenerator,
)

def _is_generic_title(title: str) -> bool:
    """Heuristic: is this title too generic to be a meaningful course topic?

    Uses patterns (not an exhaustive word list) to detect:
      - Single short English words (likely metadata)
      - Slide/page numbers
      - Administrative labels (handout, notes, readme, feedback)
      - Assessment labels (quiz, exam, test, homework)
      - Structure labels (introduction, overview, summary, agenda)
      - Chinese equivalents of the above
    """
    t = title.strip().lower()
    if not t or len(t) < 3:
        return True
    if is_low_value_keyword(t):
        return True
    # Do not reject short single-word subjects. Legitimate course topics such
    # as Ethics, Law, Logic, Algebra, Genetics, and Cache cannot be separated
    # from metadata by length or by a discipline-specific allowlist. The
    # structural patterns below handle actual labels such as notes and slides.
    # Two short English words: reject only if BOTH words are short (≤4 chars each).
    # "Cache Mapping" (5+7) → keep; "Diff Summary" (4+7) → reject
    m2 = re.match(r"^([a-z]{2,7})\s+([a-z]{2,7})$", t)
    if m2:
        w1, w2 = m2.group(1), m2.group(2)
        if len(w1) <= 4 and len(w2) <= 4:
            return True
    # Pattern-based detection (covers both EN and ZH)
    patterns = [
        # Administrative
        r"^(handout|notes|slides|lecture|readme|feedback|standard|untitled|unknown|sources?|bibliography)s?$",
        r"^(page|slide|sheet)\s*\d+$",
        r"^\d{1,3}\s*(page|slide|sheet)$",
        # Assessment
        r"^(quiz|test|exam|tutorial|homework|assignment|checkpoint|discussion)\b",
        r"^question(s)?\s*(\d+|sets?|bank)?$",
        r"^(first|next|previous|last)\s*(checkpoint\s*)?question$",
        # Structure
        r"^(introduction|overview|conclusion|summary|recap|agenda|outline|contents|appendix|references|index|glossary)\b",
        r"^(review|warm.up|opening|closing)\b",
        r"^(today|this.lecture|lecture.plan|main.line|in.class)\b",
        r"^(reality.check|one.solution|why.we.need|let.us|using.the)\b",
        # "Introduction to X" / "Overview of X" — only reject if X is also generic
        r"^(introduction|overview|conclusion)(\s+(to|of))?$",
        # Chinese
        r"^(参考|参考资料|资料来源|书目|标准|答案|笔记|总结|复习|作业|考试|测试|试卷|模拟|模拟卷|选择题|反馈)$",
        r"^[Ā-ɏ]+",  # Garbled Latin-ext chars → likely mojibake
        r"^第[一二三四五六七八九十\d]+[页章节]",
        r"^课程(内容|介绍|说明)$",
        r"^成绩反馈$",
    ]
    return any(re.match(p, t) for p in patterns)


class CourseInitializer:
    """Create a reusable course project from a folder of documents."""

    def __init__(
        self,
        manager: CourseProjectManager | None = None,
        summary_generator=None,
        profile_generator=None,
        checkpoint_store: CourseParseCheckpointStore | None = None,
        build_pipeline: CourseBuildPipeline | None = None,
    ):
        self.parser = DocumentParser()
        self.manager = manager or CourseProjectManager()
        self.summary_generator = summary_generator
        self.profile_generator = profile_generator or CourseGenerationProfileGenerator()
        self.checkpoint_store = checkpoint_store
        self._build_pipeline_override = build_pipeline

    def initialize(
        self,
        folder: str,
        title: str = "",
        make_current: bool = True,
        task: TaskControl | None = None,
        course_id: str = "",
    ) -> CourseProject:
        """Parse a folder and save a course project."""
        self._report(task, "parsing", detail=str(folder))
        docs = self._parse_documents(
            folder,
            operation="initialize",
            course_id=course_id,
            task=task,
        )
        self._check(task)
        self._require_readable_documents(docs)

        course_title = title.strip() or Path(folder).name
        artifacts = self._semantic_pipeline().build(
            course_title,
            docs,
            previous_topics=None,
            task=task,
        )
        now = datetime.now(timezone.utc).isoformat()
        project = CourseProject(
            course_id=course_id.strip() or CourseProjectManager.new_id(),
            title=course_title,
            source_folder=str(Path(folder).resolve()),
            summary_markdown=artifacts.summary_markdown,
            summary_path="",
            topics=artifacts.topics,
            documents=_document_records(docs),
            created_at=now,
            updated_at=now,
            summary_source=artifacts.summary_source,
            summary_warning=artifacts.summary_warning,
            generation_profile=artifacts.generation_profile,
            generation_profile_source=artifacts.generation_profile_source,
            generation_profile_warning=artifacts.generation_profile_warning,
        )
        self._report(task, "index")
        project = attach_index_to_project(project)
        self._report(task, "saving")
        if not self.manager.save(project, make_current=make_current):
            raise OSError("Failed to save course data.")
        self._clear_checkpoint(folder, operation="initialize", course_id=course_id)
        if task is not None:
            task.complete("saved")
        return project

    def _semantic_pipeline(self) -> CourseBuildPipeline:
        if self._build_pipeline_override is not None:
            return self._build_pipeline_override
        return CourseBuildPipeline(
            topic_inferer=infer_topics,
            summary_builder=build_summary_markdown,
            topic_reconciler=reconcile_topic_identities,
            summary_generator=self.summary_generator,
            profile_generator=self.profile_generator,
        )

    def regenerate_summary(
        self,
        project: CourseProject,
        make_current: bool = True,
        task: TaskControl | None = None,
    ) -> CourseProject:
        """Re-parse an existing course's source folder and update its reusable summary."""
        self._report(task, "parsing", detail=project.source_folder)
        docs = self._parse_documents(
            project.source_folder,
            operation="regenerate",
            course_id=project.course_id,
            task=task,
        )
        self._check(task)
        self._require_readable_documents(docs)

        artifacts = self._semantic_pipeline().build(
            project.title,
            docs,
            previous_topics=project.topics,
            task=task,
        )

        updated = CourseProject(
            course_id=project.course_id,
            title=project.title,
            source_folder=project.source_folder,
            summary_markdown=artifacts.summary_markdown,
            summary_path=project.summary_path,
            topics=artifacts.topics,
            documents=_document_records(docs),
            created_at=project.created_at,
            updated_at=datetime.now(timezone.utc).isoformat(),
            summary_source=artifacts.summary_source,
            summary_warning=artifacts.summary_warning,
            generation_profile=artifacts.generation_profile,
            generation_profile_source=artifacts.generation_profile_source,
            generation_profile_warning=artifacts.generation_profile_warning,
            exam_scope_mode=project.exam_scope_mode,
            exam_scope_topic_ids=list(project.exam_scope_topic_ids),
        )
        self._report(task, "index")
        updated = attach_index_to_project(updated)
        self._report(task, "saving")
        if not self.manager.save(updated, make_current=make_current):
            raise OSError("Failed to save course data.")
        self._clear_checkpoint(
            project.source_folder,
            operation="regenerate",
            course_id=project.course_id,
        )
        if task is not None:
            task.complete("saved")
        return updated

    def _parse_documents(
        self,
        folder: str,
        *,
        operation: str,
        course_id: str,
        task: TaskControl | None,
    ) -> list[ExtractedDocument]:
        if self.checkpoint_store is None:
            return self.parser.parse_folder(folder, task=task) if task else self.parser.parse_folder(folder)

        source_paths = self.parser.source_paths(folder)
        cached = self.checkpoint_store.load_documents(
            folder,
            operation=operation,
            course_id=course_id,
            source_paths=source_paths,
        )

        def save_checkpoint(path: Path, document: ExtractedDocument) -> None:
            try:
                self.checkpoint_store.save_document(
                    folder,
                    operation=operation,
                    course_id=course_id,
                    source_path=path,
                    document=document,
                )
            except OSError as exc:
                warning(f"Course parse checkpoint unavailable; continuing import: {exc}")

        return self.parser.parse_folder(
            folder,
            task=task,
            cached_documents=cached,
            on_document_parsed=save_checkpoint,
        )

    def _clear_checkpoint(self, folder: str, *, operation: str, course_id: str) -> None:
        if self.checkpoint_store is None:
            return
        try:
            self.checkpoint_store.clear(
                folder,
                operation=operation,
                course_id=course_id,
            )
        except OSError as exc:
            warning(f"Failed to clear completed course parse checkpoint: {exc}")

    @staticmethod
    def _require_readable_documents(documents: list[ExtractedDocument]) -> None:
        if not documents:
            raise ValueError(
                "No supported course files found. Supported: docx, pptx, pdf, txt, md."
            )
        if not any(document.text.strip() for document in documents):
            raise ValueError(
                "No readable course content was extracted. Check damaged files, OCR, or text encoding."
            )

    @staticmethod
    def _check(task: TaskControl | None) -> None:
        if task is not None:
            task.check_cancelled()

    @staticmethod
    def _report(
        task: TaskControl | None,
        stage: str,
        current: int = 0,
        total: int = 0,
        detail: str = "",
    ) -> None:
        if task is not None:
            task.report(stage, current, total, detail)

def _document_records(docs: list[ExtractedDocument]) -> list[dict]:
    return [
        {
            "path": doc.path,
            "title": doc.title,
            "extension": doc.extension,
            "word_count": doc.word_count,
            "page_count": len(doc.pages),
            "pages": list(doc.pages),
            "warnings": doc.warnings,
        }
        for doc in docs
    ]


def infer_topics(docs: list[ExtractedDocument]) -> list[CourseTopic]:
    """Build one primary topic per file; merge siblings; rank by file count.

    Strategy:
      1. Each file gets one cleaned title → primary topic candidate.
         Uninformative titles fall back to first-meaningful-sentence extraction.
      2. Candidates with identical cleaned titles merge automatically.
      3. Sibling merge: keyword overlap ≥ 50% or substring relationship.
      4. Score = file_count * 10.  No hard cap on topic count.
    """
    import math

    # ── Step 1: file → topic ──────────────────────────────────
    file_topics: dict[str, dict] = {}  # cleaned_title → {title, files, keywords, total_words}
    for doc in docs:
        # Skip noise: files with too little content to be course materials
        if doc.word_count < 80:
            continue
        if _is_auxiliary_material(doc):
            continue
        if _is_noise_content(doc.text):
            continue
        # Skip markdown files generated by the app itself (course-*_summary.md)
        fname = Path(doc.path).name.lower()
        if doc.extension == "md" and re.match(r"^course-.*summary", fname):
            continue
        title = _clean_title(doc.title)
        if not title or _is_generic_title(title):
            fallback = _extract_first_meaningful_sentence(doc.text)
            # Only use fallback if it's also not generic
            if fallback and not _is_generic_title(fallback):
                title = fallback
            else:
                continue
        if not title:
            continue  # skip unidentifiable files
        display = _title_case(title)
        key = _normalize_key(title)
        if key not in file_topics:
            file_topics[key] = {
                "title": display,
                "files": [],
                "keywords": set(),
                "keyword_counts": Counter(),
                "total_words": 0,
            }
        file_topics[key]["files"].append(doc.path)
        file_topics[key]["total_words"] += doc.word_count
        # Collect keywords from headings + key terms
        term_text = _without_repeated_page_boilerplate(doc.text)
        for h in _extract_heading_candidates(term_text):
            for t in re.findall(r"[A-Za-z][A-Za-z0-9_+-]{2,}|[一-鿿]{2,8}", _clean_title(h)):
                keyword = t.lower()
                file_topics[key]["keywords"].add(keyword)
                file_topics[key]["keyword_counts"][keyword] += 2
        for term, count in _extract_key_terms(term_text).items():
            keyword = term.lower()
            file_topics[key]["keywords"].add(keyword)
            file_topics[key]["keyword_counts"][keyword] += count

    # ── Step 2: sibling merge ─────────────────────────────────
    items = list(file_topics.items())
    merged = []
    used = set()
    for i, (ki, vi) in enumerate(items):
        if i in used:
            continue
        ki_norm = _normalize_key(ki)
        ki_kw = set(vi["keywords"])
        for j, (kj, vj) in enumerate(items[i + 1 :], i + 1):
            if j in used:
                continue
            kj_norm = _normalize_key(kj)
            kj_kw = set(vj["keywords"])
            # Merge if: substring OR ≥50% keyword overlap (bidirectional)
            if ki_norm in kj_norm or kj_norm in ki_norm:
                vi["files"].extend(vj["files"])
                vi["total_words"] += vj["total_words"]
                vi["keywords"] |= vj["keywords"]
                vi["keyword_counts"].update(vj.get("keyword_counts", Counter()))
                used.add(j)
            elif ki_kw and kj_kw:
                overlap = len(ki_kw & kj_kw)
                threshold = min(len(ki_kw), len(kj_kw)) // 2
                if overlap >= max(1, threshold):
                    vi["files"].extend(vj["files"])
                    vi["total_words"] += vj["total_words"]
                    vi["keywords"] |= vj["keywords"]
                    vi["keyword_counts"].update(vj.get("keyword_counts", Counter()))
                    used.add(j)
        merged.append((ki, vi))

    # ── Step 3: score & sort ──────────────────────────────────
    scored = []
    for key, data in merged:
        file_count = len(set(data["files"]))  # deduplicate
        score = file_count * 10 + math.log(data["total_words"] + 1) * 0.3
        scored.append((score, key, data))

    scored.sort(key=lambda x: -x[0])

    # ── Step 4: build CourseTopic list (all, no cap) ──────────
    topics: list[CourseTopic] = []
    for score, key, data in scored:
        counts = data.get("keyword_counts", Counter())
        kw_list = sorted(
            data["keywords"],
            key=lambda k: (-counts.get(k, 0), -len(k), k),
        )[:8]
        topics.append(CourseTopic(
            topic_id=_slugify(data["title"]),
            title=data["title"],
            keywords=kw_list,
            source_files=sorted(set(data["files"])),
        ))

    if not topics:
        topics.append(CourseTopic("general", "General Course Review", [],
                                   [doc.path for doc in docs]))
    return topics


def reconcile_topic_identities(
    previous_topics: list[CourseTopic],
    inferred_topics: list[CourseTopic],
) -> list[CourseTopic]:
    """Preserve stable topic IDs when a course is re-parsed.

    Topic titles can shift after OCR/parsing/summary regeneration. This keeps
    the old topic_id when the new topic can be matched by identity, title,
    source files, or keyword overlap, while recording old/new labels as aliases
    for legacy question files and model outputs.
    """
    if not previous_topics or not inferred_topics:
        return inferred_topics

    used_previous: set[int] = set()
    reconciled: list[CourseTopic] = []
    for inferred in inferred_topics:
        best_index = -1
        best_score = 0.0
        for index, previous in enumerate(previous_topics):
            if index in used_previous:
                continue
            score = _topic_identity_score(previous, inferred)
            if score > best_score:
                best_score = score
                best_index = index
        if best_index >= 0 and best_score >= 50.0:
            previous = previous_topics[best_index]
            used_previous.add(best_index)
            reconciled.append(_merge_topic_identity(previous, inferred))
        else:
            reconciled.append(inferred)
    return reconciled


def _merge_topic_identity(previous: CourseTopic, inferred: CourseTopic) -> CourseTopic:
    aliases = _merged_topic_aliases(previous, inferred)
    return CourseTopic(
        topic_id=topic_value(previous),
        title=inferred.title,
        keywords=inferred.keywords,
        source_files=inferred.source_files,
        aliases=aliases,
    )


def _merged_topic_aliases(previous: CourseTopic, inferred: CourseTopic) -> list[str]:
    candidates = [
        previous.title,
        inferred.title,
        inferred.topic_id,
        *list(getattr(previous, "aliases", []) or []),
        *list(getattr(inferred, "aliases", []) or []),
    ]
    aliases: list[str] = []
    seen: set[str] = {topic_value(previous), str(inferred.title or "").strip().lower()}
    for candidate in candidates:
        text = str(candidate or "").strip()
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        aliases.append(text)
    return aliases


def _topic_identity_score(previous: CourseTopic, inferred: CourseTopic) -> float:
    previous_aliases = topic_alias_values(previous)
    inferred_aliases = topic_alias_values(inferred)
    if previous_aliases & inferred_aliases:
        return 100.0

    score = 0.0
    previous_sources = {str(path).lower() for path in previous.source_files or []}
    inferred_sources = {str(path).lower() for path in inferred.source_files or []}
    if previous_sources and inferred_sources:
        overlap = previous_sources & inferred_sources
        if overlap:
            score += 70.0 * (len(overlap) / min(len(previous_sources), len(inferred_sources)))

    previous_keywords = {str(keyword).lower() for keyword in previous.keywords or []}
    inferred_keywords = {str(keyword).lower() for keyword in inferred.keywords or []}
    if previous_keywords and inferred_keywords:
        overlap = previous_keywords & inferred_keywords
        if overlap:
            score += 35.0 * (len(overlap) / min(len(previous_keywords), len(inferred_keywords)))

    previous_title_key = _normalize_key(previous.title)
    inferred_title_key = _normalize_key(inferred.title)
    if previous_title_key and inferred_title_key and (
        previous_title_key in inferred_title_key or inferred_title_key in previous_title_key
    ):
        score += 25.0

    return min(score, 99.0)


def _is_auxiliary_material(doc: ExtractedDocument) -> bool:
    """Return True for helper artifacts that should not become course topics."""
    name = Path(doc.path).name.lower()
    title = str(doc.title or "").strip().lower()
    head = str(doc.text or "")[:2500].lower()
    combined = f"{name}\n{title}\n{head}"

    category_markers = [
        # Generated or hand-written study helpers.
        ("课程内容", "核心概念", "推演流程", "答题要点"),
        ("复习辅助", "模拟卷", "辅助提示词"),
        ("高频考点", "变式提示"),
        ("模拟卷", "高频核心概念"),
        ("最后 40 分钟", "优先级"),
        ("study helper", "review helper"),
        ("prompt template", "study guide"),
        # Rubrics, grading feedback, and answer keys.
        ("出题标准", "干扰项"),
        ("成绩反馈", "批改"),
        ("marking rubric",),
        ("grading feedback",),
        ("answer key", "partial credit"),
        # Exercise sheets should not become topic headings.
        ("tutorial questions",),
        ("checkpoint question", "answer"),
        # Notebook exports are usually lab/code output rather than a lecture topic.
        ("jupyterlab",),
        ("notebook", "cell"),
    ]
    return any(all(marker in combined for marker in markers) for markers in category_markers)


def _extract_first_meaningful_sentence(text: str) -> str:
    """Fallback: extract the first sentence that looks like a topic title."""
    # Skip common slide-openers
    skip_prefixes = {"slide", "agenda", "outline", "overview", "today", "lecture",
                     "introduction", "welcome", "recap", "review", "summary",
                     "checkpoint", "question", "homework", "assignment"}
    for line in text.splitlines()[:30]:
        clean = line.strip(" -*#\t")
        clean = re.sub(r"^\d+[\.\)]\s*", "", clean)
        if not (6 <= len(clean) <= 90):
            continue
        if is_low_value_keyword(clean.lower()):
            continue
        words = clean.split()
        if not words:
            continue
        first_word = words[0].lower().rstrip(":,.!")
        if first_word in skip_prefixes:
            continue
        if re.match(r"^[A-Z一-鿿]", clean):
            return clean
    return ""


def build_summary_markdown(
    title: str,
    docs: list[ExtractedDocument],
    topics: list[CourseTopic],
) -> str:
    """Build a local Markdown study summary from extracted documents."""
    lines = [
        f"# {title} 课程内容",
        "",
        "> 由 quiz_app 从指定课件文件夹自动抽取生成。可在此基础上继续人工编辑，AI 出题会优先使用本总结。",
        "",
        "## 资料来源",
    ]
    for doc in docs:
        warn = f"；警告：{'; '.join(doc.warnings)}" if doc.warnings else ""
        lines.append(f"- `{Path(doc.path).name}`：{doc.extension}，约 {doc.word_count} words，{len(doc.pages)} 页/段{warn}")

    lines.extend(["", "## 自动提取主题"])
    for i, topic in enumerate(topics, 1):
        keywords = "、".join(topic.keywords) if topic.keywords else "无"
        lines.append(f"{i}. {topic.title}：关键词 {keywords}")

    lines.extend(["", "## 课程整理"])
    for i, topic in enumerate(topics, 1):
        evidence = _topic_evidence(topic, docs)
        lines.extend([
            "",
            f"### {i}. {topic.title}",
            "",
            "#### 核心概念",
        ])
        if evidence:
            for bullet in evidence[:5]:
                lines.append(f"- {bullet}")
        else:
            lines.append("- 该主题由课件标题或高频术语推断，需要进一步人工补充。")

        lines.extend([
            "",
            "#### 推演流程",
            "- 根据课件上下文，按输入、关键条件、中间状态和输出结果整理概念关系或计算步骤。",
            "",
            "#### 实际例子",
        ])
        if evidence:
            lines.append(f"- 课件示例或证据：{evidence[0]}")
        else:
            lines.append("- 当前抽取内容中没有足够的具体示例，需要结合原课件补充。")

        lines.extend([
            "",
            "#### 易错点",
            "- 注意区分相似术语、适用条件、边界情况和题干中的隐含前提。",
            "",
            "#### 可考方向",
            "- 概念辨析：解释关键术语及其边界。",
            "- 场景判断：给定状态、队列、参数或文件结构，判断下一步结果。",
            "- 计算/推演：若课件包含公式、地址、时间线或表格，按步骤写出中间过程。",
            "",
            "#### 答题要点",
            "- 先写明关键概念和适用条件，再展示必要的中间推演，最后给出明确结论。",
            "- 优先引用课件中的术语、公式、状态或例子，不补充材料之外的结论。",
        ])

    lines.extend([
        "",
        "## 附录：抽取文本摘录",
    ])
    for doc in docs:
        excerpt = doc.text[:2500].strip()
        lines.extend(["", f"### {doc.title}", "", excerpt or "_No extractable text._"])

    return "\n".join(lines).strip() + "\n"


def _extract_heading_candidates(text: str) -> list[str]:
    """Infer heading-like lines, filtering out noise (code stats, git output, etc.)."""
    # Patterns that indicate non-course content
    noise_patterns = [
        r"^Total\s*:", r"^\d+\s+Files?,", r"^\d+\s+Codes?,", r"^\d+\s+Comments?,",
        r"^\d+\s+Blanks?,", r"^All\s+\d+\s+Lines", r"^diff\s+--git", r"^@@\s",
        r"^\+{3}\s", r"^---\s", r"^index\s", r"^commit\s", r"^Author:", r"^Date:",
        r"^\d+/\d+/\d+",  # dates
    ]
    headings = []
    for raw in text.splitlines():
        line = raw.strip(" -\t*#")
        # Remove trailing colons
        line = line.rstrip(":")
        if not (6 <= len(line) <= 90):
            continue
        # Skip obvious noise
        if any(re.match(p, raw.strip()) for p in noise_patterns):
            continue
        # Skip lines that are purely numbers, dates, or single generic words
        if re.match(r"^[\d\s./-]+$", line):
            continue
        # Markdown headings
        if re.match(r"^#{1,4}\s+", raw):
            headings.append(re.sub(r"^#{1,4}\s+", "", line))
            continue
        # Numbered sections: "1. Memory Hierarchy", "3.2 Cache Mapping"
        if re.match(r"^\d+[\.)]\s+[A-Z\u4e00-\u9fff][\w\s/&,:()-]{4,80}$", line):
            headings.append(re.sub(r"^\d+[\.)]\s+", "", line))
            continue
        # Title-case English headings (at least 2 words, not single generic terms)
        if re.match(r"^[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+$", line):
            headings.append(line)
            continue
        # Chinese headings (2-15 chars, with optional English)
        if re.match(r"^[\u4e00-\u9fff]{2,15}(?:[\s/&]+[A-Za-z]+)?$", line):
            headings.append(line)
    return headings[:80]


def _extract_key_terms(text: str) -> Counter:
    """Extract frequent technical terms with shared course-term filtering."""
    return extract_course_terms(_without_repeated_page_boilerplate(text), limit=40)


def _without_repeated_page_boilerplate(text: str) -> str:
    """Exclude exact short lines repeated across many pages from term counts."""
    lines = text.splitlines()
    section = 0
    line_sections: dict[str, set[int]] = defaultdict(set)
    for raw in lines:
        if re.match(r"^\[(?:Page|Slide)\s+\d+\]$", raw.strip(), flags=re.I):
            section += 1
            continue
        clean = re.sub(r"\s+", " ", raw).strip().lower()
        if section and 1 <= len(clean) <= 160:
            line_sections[clean].add(section)

    if section < 3:
        return text
    threshold = max(3, int(section * 0.2 + 0.999))
    boilerplate = {
        line
        for line, sections in line_sections.items()
        if len(sections) >= threshold
    }
    if not boilerplate:
        return text
    return "\n".join(
        raw
        for raw in lines
        if re.sub(r"\s+", " ", raw).strip().lower() not in boilerplate
    )


def _clean_title(title: str) -> str:
    """Clean a raw file title. Returns '' if the result is garbage."""
    if not title or len(title) > 120:
        return ""
    # Strip one or more file extensions; some exports have names like .pdf.pdf.
    while re.search(r"\.(pptx|pdf|docx|txt|md)$", title, flags=re.I):
        title = re.sub(r"\.(pptx|pdf|docx|txt|md)$", "", title, flags=re.I)
    # Remove high-unicode garbage
    title = re.sub(r"[^\x20-\x7E一-鿿぀-ヿ가-힯]", " ", title)
    # Strip repository/course-catalog prefixes such as "MIT-14-01-" or
    # "CMU-15-213-" without maintaining institution-specific allowlists.
    title = re.sub(
        r"^(?:[A-Za-z][A-Za-z0-9]{1,12}[\s_-]+)?"
        r"\d{1,3}(?:[._-]\d{1,3}){1,2}[\s_-]+",
        "",
        title,
    )
    # Strip common lecture numbering prefixes: "2.", "L15_2_", "Week 03 -".
    title = re.sub(
        r"^(?:l|lecture|week)?\s*\d{1,3}(?:[\._-]\d{1,3})?[\.\)\s_-]+",
        "",
        title,
        flags=re.I,
    )
    title = re.sub(r"[_-]+", " ", title)
    # Strip copy/export suffixes like "Title (1)" without eating real years
    # or version labels such as "Operating Systems (2024)".
    title = re.sub(r"\s*\([1-9]\d{0,2}\)$", "", title)
    title = re.sub(r"\bL\d+\b|\bLecture\s*\d+\b|\bWeek\s*\d+\b|\bDI\d+\b|\bCS\d+\b", "", title, flags=re.I)
    # Export/container labels describe the file rather than its subject.
    title = re.sub(
        r"\s+(?:handouts?|slides?|summar(?:y|ies)|zoom\s*notes?|zoomnotes)$",
        "",
        title,
        flags=re.I,
    )
    title = re.sub(r"\s+", " ", title).strip(" -.")
    # Truncate at the first run of non-ASCII, non-CJK characters (garbled suffix)
    match = re.match(r"^([\x20-\x7E一-鿿\s]+)", title)
    if match:
        title = match.group(1).strip(" -.")
    # Reject if too short or not enough meaningful characters
    alpha_cjk = sum(1 for c in title if c.isalpha() or '一' <= c <= '鿿')
    if len(title) < 4 or alpha_cjk < 2:
        return ""
    return title


def _is_noise_content(text: str) -> bool:
    """Quick content check: detect CLOC reports, git diffs, and other non-course files."""
    head = text[:800]
    # CLOC (Count Lines of Code) diff reports
    if re.search(r"Total\s*:\s*\d+\s+files?,\s*[\d-]+\s+codes?,", head):
        return True
    # Git patches
    if re.search(r"^diff\s+--git", head, re.MULTILINE):
        return True
    if re.search(r"^@@\s+-\d+,\d+\s+\+\d+,\d+\s+@@", head, re.MULTILINE):
        return True
    # Commit logs
    if re.search(r"^commit\s+[0-9a-f]{40}", head, re.MULTILINE):
        return True
    return False


def _add_candidate(candidates: dict[str, dict], title: str, score: int, source: str, word_count: int = 0):
    title = _clean_title(title)
    if not title:
        return
    key = title[:100]
    if key not in candidates:
        candidates[key] = {"raw_score": 0, "score": 0, "sources": set(),
                           "_doc_count": 0, "_total_words": 0}
    candidates[key]["raw_score"] += score
    if source not in candidates[key]["sources"]:
        candidates[key]["sources"].add(source)
        candidates[key]["_doc_count"] += 1
        candidates[key]["_total_words"] += word_count


def _related_keywords(title: str, candidates: dict[str, dict]) -> list[str]:
    title_terms = set(re.findall(r"[A-Za-z][A-Za-z0-9_+-]{2,}|[\u4e00-\u9fff]{2,8}", title.lower()))
    related = []
    for candidate, data in sorted(candidates.items(), key=lambda item: item[1]["score"], reverse=True):
        if candidate == title:
            continue
        terms = set(re.findall(r"[A-Za-z][A-Za-z0-9_+-]{2,}|[\u4e00-\u9fff]{2,8}", candidate.lower()))
        if title_terms & terms:
            related.append(_title_case(candidate))
    return related


def _topic_evidence(topic: CourseTopic, docs: list[ExtractedDocument]) -> list[str]:
    terms = [topic.title, *topic.keywords]
    evidence = []
    for doc in docs:
        if doc.path not in topic.source_files:
            continue
        sentences = re.split(r"(?<=[.!?。！？])\s+|\n+", doc.text)
        for sentence in sentences:
            clean = sentence.strip()
            if not (20 <= len(clean) <= 220):
                continue
            lowered = clean.lower()
            if any(term and term.lower() in lowered for term in terms):
                evidence.append(clean)
            if len(evidence) >= 8:
                return evidence
    return evidence


def _slugify(title: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9\u4e00-\u9fff]+", "_", title).strip("_").lower()
    return slug[:48] or "topic"


def _normalize_key(text: str) -> str:
    return re.sub(r"\W+", "", text.lower())


def _title_case(text: str) -> str:
    text = text.strip()
    if re.search(r"[\u4e00-\u9fff]", text):
        return text
    if text.isupper():
        return text
    return " ".join(word if word.isupper() else word.capitalize() for word in text.split())
