"""Build generic course projects from imported materials."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from core.document_parser import DocumentParser, ExtractedDocument
from core.course_index import attach_index_to_project
from models.course_project import CourseProject, CourseProjectManager, CourseTopic
from ai.course_generation_profile import (
    CourseGenerationProfileGenerator,
    build_local_course_profile,
)


STOP_WORDS = {
    "the", "and", "for", "with", "from", "that", "this", "have", "will", "into",
    "your", "about", "when", "which", "where", "what", "why", "how", "can",
    "you", "are", "was", "were", "has", "use", "using", "page", "slide",
    "一个", "一种", "以及", "或者", "因此", "因为", "如果", "可以", "需要",
    "什么", "如何", "为什么", "主要", "系统", "课程", "内容", "问题",
    "handout", "notes", "slides", "lecture", "chapter", "course", "review",
    "uses", "order",
    # Common noise from non-course files (README stats, git output, etc.)
    "files", "data", "details", "summary", "results", "diff", "total",
    "codes", "comments", "blanks", "lines", "all", "question", "questions",
    "discussion", "checkpoint", "previous",
}

TECHNICAL_KEYWORDS = {
    "address", "block", "byte", "cache", "cpu", "dma", "gpu", "index", "line",
    "mapping", "mmu", "offset", "pcb", "raid", "set", "simd", "simt", "tag",
    "tlb", "warp",
}

LOW_VALUE_KEYWORD_FRAGMENTS = {
    "根据课件", "课件上下文", "关键条件", "中间状态", "输出结果", "整理概念",
    "概念关系", "计算步骤", "人工补充", "当前抽取", "可考方向", "答题要点",
    "实际例子", "易错点", "核心概念", "推演流程",
}
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
    # Allowlist: technical terms/acronyms that are short but legitimate
    _TECH_TERMS = {"cache", "dma", "gpu", "cpu", "raid", "tlb", "pcb", "simd",
                   "simt", "warp", "mutex", "fcfs", "sjf", "srt", "mmu", "gpgpu"}
    # Single short English word (≤7 chars) → reject, unless it's a known tech term
    m = re.match(r"^[a-z]{2,7}$", t)
    if m and not any('一' <= c <= '鿿' for c in t):
        if t not in _TECH_TERMS:
            return True
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
        r"^(handout|notes|slides|lecture|readme|feedback|standard|untitled|unknown)s?$",
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
        r"^(参考|标准|答案|笔记|总结|复习|作业|考试|测试|试卷|模拟|模拟卷|选择题|反馈)$",
        r"^[Ā-ɏ]+",  # Garbled Latin-ext chars → likely mojibake
        r"^第[一二三四五六七八九十\d]+[页章节]",
        r"^课程[内容介绍说明]$",
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
    ):
        self.parser = DocumentParser()
        self.manager = manager or CourseProjectManager()
        self.summary_generator = summary_generator
        self.profile_generator = profile_generator or CourseGenerationProfileGenerator()

    def initialize(self, folder: str, title: str = "", make_current: bool = True) -> CourseProject:
        """Parse a folder and save a course project."""
        docs = self.parser.parse_folder(folder)
        if not docs:
            raise ValueError("No supported course files found. Supported: docx, pptx, pdf, txt, md.")

        course_title = title.strip() or Path(folder).name
        topics = infer_topics(docs)
        summary = build_summary_markdown(course_title, docs, topics)
        summary_source = "local"
        summary_warning = ""
        if self.summary_generator is not None:
            summary = self.summary_generator.generate(course_title, docs, topics, summary)
            summary_source = getattr(self.summary_generator, "summary_source", "llm")
            summary_warning = getattr(self.summary_generator, "summary_warning", "")
        generation_profile, profile_source, profile_warning = self._generate_profile(
            course_title, topics, summary
        )
        now = datetime.now(timezone.utc).isoformat()
        project = CourseProject(
            course_id=CourseProjectManager.new_id(),
            title=course_title,
            source_folder=str(Path(folder).resolve()),
            summary_markdown=summary,
            summary_path="",
            topics=topics,
            documents=_document_records(docs),
            created_at=now,
            updated_at=now,
            summary_source=summary_source,
            summary_warning=summary_warning,
            generation_profile=generation_profile,
            generation_profile_source=profile_source,
            generation_profile_warning=profile_warning,
        )
        project = attach_index_to_project(project)
        self.manager.save(project, make_current=make_current)
        return project

    def regenerate_summary(self, project: CourseProject, make_current: bool = True) -> CourseProject:
        """Re-parse an existing course's source folder and update its reusable summary."""
        docs = self.parser.parse_folder(project.source_folder)
        if not docs:
            raise ValueError("No supported course files found. Supported: docx, pptx, pdf, txt, md.")

        topics = infer_topics(docs)
        summary = build_summary_markdown(project.title, docs, topics)
        summary_source = "local"
        summary_warning = ""
        if self.summary_generator is not None:
            summary = self.summary_generator.generate(project.title, docs, topics, summary)
            summary_source = getattr(self.summary_generator, "summary_source", "llm")
            summary_warning = getattr(self.summary_generator, "summary_warning", "")
        generation_profile, profile_source, profile_warning = self._generate_profile(
            project.title, topics, summary
        )

        updated = CourseProject(
            course_id=project.course_id,
            title=project.title,
            source_folder=project.source_folder,
            summary_markdown=summary,
            summary_path=project.summary_path,
            topics=topics,
            documents=_document_records(docs),
            created_at=project.created_at,
            updated_at=datetime.now(timezone.utc).isoformat(),
            summary_source=summary_source,
            summary_warning=summary_warning,
            generation_profile=generation_profile,
            generation_profile_source=profile_source,
            generation_profile_warning=profile_warning,
        )
        updated = attach_index_to_project(updated)
        self.manager.save(updated, make_current=make_current)
        return updated

    def _generate_profile(self, title, topics, summary) -> tuple[dict, str, str]:
        """Generate defaults without allowing an optional LLM failure to block import."""
        try:
            plan = self.profile_generator.generate(title, topics, summary)
            source = getattr(self.profile_generator, "profile_source", "local")
            warning = getattr(self.profile_generator, "profile_warning", "")
        except Exception as exc:
            plan = build_local_course_profile(topics, summary)
            source = "local"
            warning = f"Course generation profile failed: {exc}"
        return plan.to_dict(), source, warning


def _document_records(docs: list[ExtractedDocument]) -> list[dict]:
    return [
        {
            "path": doc.path,
            "title": doc.title,
            "extension": doc.extension,
            "word_count": doc.word_count,
            "page_count": len(doc.pages),
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
        for h in _extract_heading_candidates(doc.text):
            for t in re.findall(r"[A-Za-z][A-Za-z0-9_+-]{2,}|[一-鿿]{2,8}", _clean_title(h)):
                keyword = t.lower()
                file_topics[key]["keywords"].add(keyword)
                file_topics[key]["keyword_counts"][keyword] += 2
        for term, count in _extract_key_terms(doc.text).items():
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
    """Extract frequent technical terms. Filters generic single English words."""
    # Multi-word English phrases (2-3 words, e.g. "Cache_Mapping")
    phrases = re.findall(r"[A-Z][a-z]+_[A-Z][a-z]+(?:_[A-Z][a-z]+)?", text)
    # Chinese compounds (2-8 chars) and English compounds (3+ chars, not all lowercase)
    tokens = re.findall(r"[\u4e00-\u9fff]{2,8}|[A-Za-z][A-Za-z0-9_+-]{2,}", text)
    normalized = []
    for token in phrases + tokens:
        key = token.lower()
        if key in STOP_WORDS:
            continue
        if _is_low_value_keyword(key):
            continue
        if token.isdigit():
            continue
        # Skip single English words that are just generic nouns
        if re.match(r"^[a-z]{2,10}$", key) and key not in TECHNICAL_KEYWORDS:
            continue
        normalized.append(token)
    counts = Counter(normalized)
    return Counter(dict(counts.most_common(40)))


def _is_low_value_keyword(term: str) -> bool:
    """Reject generated-summary scaffolding terms before they become topic keywords."""
    return any(fragment in term for fragment in LOW_VALUE_KEYWORD_FRAGMENTS)


def _clean_title(title: str) -> str:
    """Clean a raw file title. Returns '' if the result is garbage."""
    if not title or len(title) > 120:
        return ""
    # Strip file extension
    title = re.sub(r"\.(pptx|pdf|docx|txt|md)$", "", title, flags=re.I)
    # Remove high-unicode garbage
    title = re.sub(r"[^\x20-\x7E一-鿿぀-ヿ가-힯]", " ", title)
    # Strip leading numbers and separators
    title = re.sub(r"^\d+[\.\)\-_]\s*", "", title)
    title = re.sub(r"[_-]+", " ", title)
    title = re.sub(r"\s*\(\d+\)$", "", title)  # PowerPoint suffix like "Title (1)"
    title = re.sub(r"\bL\d+\b|\bLecture\s*\d+\b|\bWeek\s*\d+\b|\bDI\d+\b|\bCS\d+\b", "", title, flags=re.I)
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
