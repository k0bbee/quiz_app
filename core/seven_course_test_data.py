"""Deterministic cross-discipline data for local end-to-end acceptance tests."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
import shutil

from core.course_initializer import CourseInitializer
from core.question_validation import validate_question_quality
from models.course_project import CourseProject, CourseProjectManager
from models.question import Question, QuestionBank
from models.question_set import QuestionSet, SetManager
from utils.constants import Difficulty, QuestionType


_STAMP = "2026-07-15T00:00:00+00:00"


@dataclass(frozen=True)
class _QuestionSeed:
    type: QuestionType
    topic_index: int
    stem_zh: str
    stem_en: str
    options_zh: object
    options_en: object
    answer: object
    explanation_zh: str
    explanation_en: str
    difficulty: Difficulty = Difficulty.MEDIUM


@dataclass(frozen=True)
class _CourseSeed:
    slug: str
    title: str
    source_name: str
    topics: tuple[tuple[str, str, tuple[str, ...]], ...]
    questions: tuple[_QuestionSeed, ...]


@dataclass(frozen=True)
class SevenCourseSeedReport:
    course_count: int
    question_count: int
    question_set_count: int


@dataclass(frozen=True)
class SevenCourseAuditReport:
    course_ids: tuple[str, ...]
    question_count: int
    question_set_count: int
    questions_per_course: dict[str, int]
    sets_per_course: dict[str, int]
    question_types: tuple[QuestionType, ...]
    stale_question_refs: tuple[str, ...]
    orphan_course_refs: tuple[str, ...]
    structurally_invalid_question_ids: tuple[str, ...]
    quality_issue_question_ids: tuple[str, ...]
    documents_per_course: dict[str, int]
    source_chunks_per_course: dict[str, int]


def _choice(
    qtype: QuestionType,
    topic: int,
    zh: str,
    en: str,
    zh_options: tuple[str, ...],
    en_options: tuple[str, ...],
    answer: str,
    zh_reason: str,
    en_reason: str,
    difficulty: Difficulty = Difficulty.MEDIUM,
) -> _QuestionSeed:
    return _QuestionSeed(
        qtype, topic, zh, en, zh_options, en_options, answer,
        zh_reason, en_reason, difficulty,
    )


def _text(
    qtype: QuestionType,
    topic: int,
    zh: str,
    en: str,
    answer: object,
    zh_reason: str,
    en_reason: str,
    difficulty: Difficulty = Difficulty.MEDIUM,
) -> _QuestionSeed:
    return _QuestionSeed(
        qtype, topic, zh, en, (), (), answer,
        zh_reason, en_reason, difficulty,
    )


_COURSES: tuple[_CourseSeed, ...] = (
    _CourseSeed(
        "computer-systems", "计算机系统", "system-level-io.md",
        (
            ("io_interrupts", "中断驱动 I/O", ("interrupt", "polling", "cpu")),
            ("direct_memory_access", "直接存储器访问", ("dma", "memory", "device")),
            ("io_request_lifecycle", "I/O 请求生命周期", ("request", "completion", "driver")),
        ),
        (
            _choice(QuestionType.MULTIPLE_CHOICE, 0,
                "设备完成操作后才通知 CPU，最符合哪种 I/O 机制？",
                "Which I/O mechanism notifies the CPU only after the device completes?",
                ("轮询", "中断驱动 I/O", "忙等待", "同步循环"),
                ("Polling", "Interrupt-driven I/O", "Busy waiting", "Synchronous loop"), "B",
                "中断驱动 I/O 允许 CPU 在设备工作期间执行其他任务。",
                "Interrupt-driven I/O lets the CPU do other work while the device runs."),
            _QuestionSeed(QuestionType.MATCHING, 1,
                "将 I/O 机制与主要特征配对。", "Match each I/O mechanism to its main property.",
                {"left": [{"id": "poll", "text": "轮询"}, {"id": "dma", "text": "DMA"}],
                 "right": [{"id": "check", "text": "CPU 反复检查状态"}, {"id": "direct", "text": "控制器直接传输内存块"}]},
                {"left": [{"id": "poll", "text": "Polling"}, {"id": "dma", "text": "DMA"}],
                 "right": [{"id": "check", "text": "CPU repeatedly checks status"}, {"id": "direct", "text": "Controller transfers memory blocks directly"}]},
                [["poll", "check"], ["dma", "direct"]],
                "轮询占用 CPU 检查状态，DMA 则把块传输交给控制器。",
                "Polling spends CPU cycles checking status, while DMA delegates block transfer."),
            _QuestionSeed(QuestionType.ORDERING, 2,
                "按中断驱动 I/O 的处理顺序排列。", "Order the interrupt-driven I/O lifecycle.",
                [{"id": "issue", "text": "CPU 发出命令"}, {"id": "work", "text": "设备执行操作"}, {"id": "interrupt", "text": "设备发出完成中断"}],
                [{"id": "issue", "text": "CPU issues command"}, {"id": "work", "text": "Device performs operation"}, {"id": "interrupt", "text": "Device raises completion interrupt"}],
                ["issue", "work", "interrupt"],
                "命令先提交给设备，设备完成后才产生中断。",
                "The command is submitted first; the device interrupts only after completion."),
        ),
    ),
    _CourseSeed(
        "microeconomics", "微观经济学", "microeconomics-summary.md",
        (
            ("supply_and_demand", "供给与需求", ("supply", "demand", "equilibrium")),
            ("price_elasticity", "价格弹性", ("elasticity", "price", "quantity")),
            ("opportunity_cost", "机会成本", ("choice", "tradeoff", "cost")),
        ),
        (
            _choice(QuestionType.SCENARIO_CHOICE, 0,
                "其他条件不变，消费者收入提高且该商品为正常品，均衡市场最可能怎样变化？",
                "With other factors fixed, income rises for a normal good. What most likely happens?",
                ("需求曲线左移", "需求曲线右移", "供给曲线左移", "供给曲线右移"),
                ("Demand shifts left", "Demand shifts right", "Supply shifts left", "Supply shifts right"), "B",
                "正常品的收入增加会提高各价格下的需求量，使需求曲线右移。",
                "Higher income raises demand for a normal good at each price, shifting demand right."),
            _choice(QuestionType.TRUE_FALSE, 1,
                "若需求价格弹性的绝对值大于 1，则需求具有弹性。",
                "Demand is elastic when the absolute value of price elasticity exceeds one.",
                ("正确", "错误"), ("True", "False"), "true",
                "绝对弹性大于 1 表示需求量变化比例超过价格变化比例。",
                "An absolute elasticity above one means quantity changes proportionally more than price."),
            _text(QuestionType.SHORT_ANSWER, 2,
                "说明参加两小时讲座的机会成本应如何判断。",
                "Explain how to identify the opportunity cost of attending a two-hour lecture.",
                "放弃的最佳替代活动所带来的净收益。",
                "机会成本不是所有备选收益之和，而是未选择的最佳替代方案价值。",
                "Opportunity cost is the value of the best forgone alternative, not the sum of all alternatives."),
        ),
    ),
    _CourseSeed(
        "linear-algebra", "线性代数", "linear-algebra-notes.md",
        (
            ("linear_independence", "线性无关", ("independence", "basis", "span")),
            ("matrix_rank", "矩阵的秩", ("rank", "pivot", "column")),
            ("gaussian_elimination", "高斯消元", ("elimination", "row", "pivot")),
        ),
        (
            _text(QuestionType.FILL_IN_BLANK, 0,
                "一组向量若只有全部系数为零时线性组合才等于零，则称这组向量____。",
                "Vectors are ____ if only the all-zero coefficients produce the zero vector.",
                ["线性无关", "linearly independent"],
                "这是线性无关的定义。", "This is the definition of linear independence."),
            _choice(QuestionType.MULTIPLE_CHOICE, 1,
                "矩阵的秩等于其行最简形中的什么数量？",
                "Matrix rank equals which count in reduced row-echelon form?",
                ("零行", "主元", "自由变量加一", "矩阵元素"),
                ("Zero rows", "Pivots", "Free variables plus one", "Matrix entries"), "B",
                "每个主元对应一个线性无关方向，因此主元数等于秩。",
                "Each pivot identifies an independent direction, so pivot count equals rank."),
            _QuestionSeed(QuestionType.ORDERING, 2,
                "按高斯消元求解线性方程组的一般顺序排列。",
                "Order the usual Gaussian-elimination workflow.",
                [{"id": "augment", "text": "写出增广矩阵"}, {"id": "eliminate", "text": "进行初等行变换"}, {"id": "solve", "text": "回代或读取解"}],
                [{"id": "augment", "text": "Form the augmented matrix"}, {"id": "eliminate", "text": "Apply elementary row operations"}, {"id": "solve", "text": "Back-substitute or read the solution"}],
                ["augment", "eliminate", "solve"],
                "先表示方程组，再消元形成阶梯形，最后确定解。",
                "Represent the system, eliminate to echelon form, then determine the solution."),
        ),
    ),
    _CourseSeed(
        "genetics", "遗传学", "genetics-lecture.md",
        (
            ("mendelian_inheritance", "孟德尔遗传", ("allele", "segregation", "dominant")),
            ("dna_replication", "DNA 复制", ("dna", "replication", "polymerase")),
            ("genotype_phenotype", "基因型与表型", ("genotype", "phenotype", "environment")),
        ),
        (
            _QuestionSeed(QuestionType.MATCHING, 0,
                "将遗传学术语与含义配对。", "Match each genetics term to its meaning.",
                {"left": [{"id": "geno", "text": "基因型"}, {"id": "pheno", "text": "表型"}],
                 "right": [{"id": "alleles", "text": "个体的等位基因组成"}, {"id": "traits", "text": "可观察性状"}]},
                {"left": [{"id": "geno", "text": "Genotype"}, {"id": "pheno", "text": "Phenotype"}],
                 "right": [{"id": "alleles", "text": "An individual's allele composition"}, {"id": "traits", "text": "Observable traits"}]},
                [["geno", "alleles"], ["pheno", "traits"]],
                "基因型描述个体拥有的等位基因组合；表型描述这些遗传信息与环境共同作用后表现出的可观察性状。",
                "Genotype describes genetic composition; phenotype describes observable outcomes."),
            _choice(QuestionType.TRUE_FALSE, 1,
                "DNA 聚合酶沿新生链的 5′ 到 3′ 方向合成 DNA。",
                "DNA polymerase synthesizes DNA in the 5-prime to 3-prime direction.",
                ("正确", "错误"), ("True", "False"), "true",
                "聚合酶把核苷酸加到新生链的 3′ 端。",
                "Polymerase adds nucleotides to the 3-prime end of the growing strand."),
            _text(QuestionType.FILL_IN_BLANK, 2,
                "同一基因的不同形式称为____。", "Alternative forms of the same gene are called ____.",
                ["等位基因", "alleles"],
                "等位基因位于同源染色体的相同基因座。",
                "Alleles occupy the same locus on homologous chromosomes."),
        ),
    ),
    _CourseSeed(
        "emergency-medicine", "急诊医学", "basic-emergency-care.md",
        (
            ("primary_assessment", "初步评估", ("airway", "breathing", "circulation")),
            ("triage", "分诊", ("triage", "priority", "severity")),
            ("shock_recognition", "休克识别", ("shock", "perfusion", "pulse")),
        ),
        (
            _choice(QuestionType.SCENARIO_CHOICE, 0,
                "患者意识不清并出现鼾声样呼吸，初步评估中应首先处理什么？",
                "An unconscious patient has snoring respirations. What should be addressed first?",
                ("气道通畅", "完整病史", "饮食记录", "长期康复计划"),
                ("Airway patency", "Complete history", "Diet record", "Long-term rehabilitation"), "A",
                "鼾声提示上气道部分阻塞，初步评估应优先开放并保护气道。",
                "Snoring suggests partial upper-airway obstruction, so airway opening and protection come first."),
            _QuestionSeed(QuestionType.ORDERING, 1,
                "按常用初步评估顺序排列。", "Order the common primary-assessment sequence.",
                [{"id": "airway", "text": "气道"}, {"id": "breathing", "text": "呼吸"}, {"id": "circulation", "text": "循环"}],
                [{"id": "airway", "text": "Airway"}, {"id": "breathing", "text": "Breathing"}, {"id": "circulation", "text": "Circulation"}],
                ["airway", "breathing", "circulation"],
                "初步评估依次处理气道、呼吸和循环的立即威胁。",
                "Primary assessment addresses immediate threats to airway, breathing, then circulation."),
            _text(QuestionType.SHORT_ANSWER, 2,
                "列出两项可能提示组织灌注不足的观察结果。",
                "Give two observations that may indicate inadequate tissue perfusion.",
                "可包括意识改变、皮肤湿冷、脉搏细速或毛细血管再充盈延迟。",
                "灌注不足会影响脑、皮肤和外周循环，因此需结合多项体征判断。",
                "Poor perfusion affects the brain, skin, and peripheral circulation, so multiple findings should be combined."),
        ),
    ),
    _CourseSeed(
        "case-law", "法学案例分析", "case-law-opinion.md",
        (
            ("precedent", "判例与先例", ("precedent", "holding", "court")),
            ("issue_rule_application", "争点—规则—适用", ("issue", "rule", "application")),
            ("facts_and_holding", "事实与裁判要旨", ("facts", "holding", "reasoning")),
        ),
        (
            _choice(QuestionType.MULTIPLE_CHOICE, 0,
                "阅读判决时，哪一部分最直接表达法院解决争议所采用的法律结论？",
                "Which part of an opinion most directly states the court's legal resolution of the dispute?",
                ("裁判要旨", "当事人姓名", "页码", "附件目录"),
                ("Holding", "Party names", "Page number", "Appendix index"), "A",
                "裁判要旨是法院对关键法律争点作出的结论。",
                "The holding is the court's conclusion on the material legal issue."),
            _choice(QuestionType.TRUE_FALSE, 1,
                "案例分析中，事实、法律规则和规则对事实的适用应当区分。",
                "Case analysis should distinguish facts, legal rules, and application of rules to facts.",
                ("正确", "错误"), ("True", "False"), "true",
                "分层书写可以避免把法院结论误当作案件事实或抽象规则。",
                "Separating the layers prevents confusing facts, abstract rules, and the court's conclusion."),
            _QuestionSeed(QuestionType.MATCHING, 2,
                "将案例分析要素与问题配对。", "Match each case-analysis element to its question.",
                {"left": [{"id": "issue", "text": "争点"}, {"id": "application", "text": "适用"}],
                 "right": [{"id": "question", "text": "法院需要解决什么法律问题"}, {"id": "fit", "text": "规则如何作用于本案事实"}]},
                {"left": [{"id": "issue", "text": "Issue"}, {"id": "application", "text": "Application"}],
                 "right": [{"id": "question", "text": "What legal question must the court resolve"}, {"id": "fit", "text": "How the rule operates on these facts"}]},
                [["issue", "question"], ["application", "fit"]],
                "争点提出法律问题，适用部分把规则与具体事实连接起来。",
                "The issue frames the legal question; application connects the rule to specific facts."),
        ),
    ),
    _CourseSeed(
        "ethics", "伦理学", "ethics-handout.md",
        (
            ("utilitarian_reasoning", "功利主义推理", ("utility", "consequence", "welfare")),
            ("deontological_reasoning", "义务论推理", ("duty", "rule", "rights")),
            ("argument_evaluation", "论证评价", ("premise", "conclusion", "objection")),
        ),
        (
            _choice(QuestionType.SCENARIO_CHOICE, 0,
                "某方案主要依据‘能使所有受影响者的总体福祉最大化’来辩护，这最接近哪种推理？",
                "A policy is defended because it maximizes total welfare for everyone affected. Which reasoning is closest?",
                ("功利主义", "纯粹诉诸传统", "词源分析", "描述性统计"),
                ("Utilitarianism", "Appeal to tradition", "Etymology", "Descriptive statistics"), "A",
                "功利主义根据行为或规则的后果及总体福祉评价其正当性。",
                "Utilitarian reasoning evaluates justification through consequences and aggregate welfare."),
            _text(QuestionType.SHORT_ANSWER, 1,
                "说明义务论为何可能反对一个能增加总体利益但侵犯个人权利的行为。",
                "Explain why deontological reasoning may reject an act that raises total benefit but violates a person's rights.",
                "义务论认为某些义务或权利对行为构成约束，不能仅以结果总量抵消。",
                "义务论关注行为是否遵守可辩护的规则与对人的尊重，而不只比较结果。",
                "Deontology asks whether conduct respects defensible duties and persons, not only whether outcomes improve."),
            _text(QuestionType.FILL_IN_BLANK, 2,
                "在论证中，用来支持结论的陈述称为____。",
                "Statements offered in support of a conclusion are called ____.",
                ["前提", "premises"],
                "前提为结论提供理由，评价论证需分别检查前提真实性和推理关系。",
                "Premises support a conclusion; evaluation checks both their truth and the inference."),
        ),
    ),
)


SEVEN_COURSE_IDS = tuple(f"test-course-{course.slug}" for course in _COURSES)

SEVEN_COURSE_SOURCES: dict[str, tuple[str, ...]] = {
    "computer-systems": (
        "cmu-15-213-system-level-io.pdf",
        "cmu-15-213-system-level-io.pptx",
        "computer-systems.md",
    ),
    "microeconomics": ("mit-14-01-microeconomics-summaries.pdf", "microeconomics.md"),
    "linear-algebra": ("mit-18-06-linear-algebra-zoomnotes.pdf", "linear-algebra.md"),
    "genetics": ("mit-7-03-genetics-lecture-1.pdf", "genetics.md"),
    "emergency-medicine": ("who-basic-emergency-care.pdf", "emergency-medicine.md"),
    "case-law": ("cornell-law-georgia-v-public-resource.pdf", "case-law.md"),
    "ethics": ("mit-24-00-ethics-handout.pdf", "ethics.md"),
}


def seed_seven_course_data(
    root: str | Path,
    *,
    source_root: str | Path,
) -> SevenCourseSeedReport:
    """Import seven original-source groups and bind deterministic test questions."""
    data_root = Path(root).resolve()
    original_root = Path(source_root).resolve()
    if not original_root.is_dir():
        raise FileNotFoundError(f"Original source root does not exist: {original_root}")
    course_manager = CourseProjectManager(str(data_root / "courses"))
    question_bank = QuestionBank(str(data_root / "questions"))
    set_manager = SetManager(str(data_root / "question_sets"))
    initializer = CourseInitializer(manager=course_manager)

    question_count = 0
    for course_seed in _COURSES:
        staged_folder = _stage_original_sources(original_root, data_root, course_seed.slug)
        project = initializer.initialize(
            str(staged_folder),
            title=course_seed.title,
            make_current=False,
            course_id=f"test-course-{course_seed.slug}",
        )
        question_ids: list[str] = []
        for index, question_seed in enumerate(course_seed.questions, start=1):
            question = _build_question(project, course_seed, question_seed, index)
            if not question_bank.save(question):
                raise OSError(f"Failed to save test question {question.question_id}")
            question_ids.append(question.question_id)
            question_count += 1
        question_set = QuestionSet(
            set_id=f"test-set-{course_seed.slug}",
            title={"zh": f"{course_seed.title}综合练习", "en": f"{course_seed.slug.replace('-', ' ').title()} Practice"},
            description={"zh": "跨学科端到端测试题集", "en": "Cross-discipline end-to-end test set"},
            topics=list(project.topics),
            difficulty=Difficulty.MEDIUM,
            estimated_minutes=10,
            questions=question_ids,
            metadata={"course_id": project.course_id, "source": "seven_course_test_seed", "created_at": _STAMP},
        )
        if not set_manager.save(question_set):
            raise OSError(f"Failed to save test set {question_set.set_id}")

    return SevenCourseSeedReport(len(_COURSES), question_count, len(_COURSES))


def audit_seven_course_data(root: str | Path) -> SevenCourseAuditReport:
    """Check ownership, references, type coverage, and structural validity."""
    data_root = Path(root).resolve()
    courses = CourseProjectManager(str(data_root / "courses")).load_all()
    questions = QuestionBank(str(data_root / "questions")).load_all()
    question_sets = SetManager(str(data_root / "question_sets")).load_all()
    course_ids = {course.course_id for course in courses}
    question_ids = {question.question_id for question in questions}
    questions_per_course = Counter(_course_id(question.metadata) for question in questions)
    sets_per_course = Counter(_course_id(question_set.metadata) for question_set in question_sets)
    stale_refs = sorted(
        f"{question_set.set_id}:{question_id}"
        for question_set in question_sets
        for question_id in question_set.questions
        if question_id not in question_ids
    )
    orphan_refs = sorted(
        f"question:{question.question_id}:{_course_id(question.metadata)}"
        for question in questions
        if _course_id(question.metadata) not in course_ids
    ) + sorted(
        f"set:{question_set.set_id}:{_course_id(question_set.metadata)}"
        for question_set in question_sets
        if _course_id(question_set.metadata) not in course_ids
    )
    invalid = tuple(sorted(question.question_id for question in questions if question.validate()))
    quality_issues = tuple(sorted(
        question.question_id for question in questions if validate_question_quality(question)
    ))
    return SevenCourseAuditReport(
        course_ids=tuple(sorted(course_ids)),
        question_count=len(questions),
        question_set_count=len(question_sets),
        questions_per_course=dict(questions_per_course),
        sets_per_course=dict(sets_per_course),
        question_types=tuple(sorted({question.type for question in questions}, key=lambda item: item.value)),
        stale_question_refs=tuple(stale_refs),
        orphan_course_refs=tuple(orphan_refs),
        structurally_invalid_question_ids=invalid,
        quality_issue_question_ids=quality_issues,
        documents_per_course={course.course_id: len(course.documents) for course in courses},
        source_chunks_per_course={
            course.course_id: sum(
                len(document.get("_source_index", []) or [])
                for document in course.documents
                if isinstance(document, dict)
            )
            for course in courses
        },
    )


def _stage_original_sources(source_root: Path, data_root: Path, slug: str) -> Path:
    candidates = SEVEN_COURSE_SOURCES[slug]
    selected = [source_root / name for name in candidates if (source_root / name).is_file()]
    fallback_name = f"{slug}.md"
    real_selected = [path for path in selected if path.name != fallback_name]
    if real_selected:
        selected = real_selected
    if not selected:
        expected = ", ".join(candidates)
        raise FileNotFoundError(f"No original source for {slug}; expected one of: {expected}")
    staged = data_root / "source_materials" / slug
    staged.mkdir(parents=True, exist_ok=True)
    selected_names = {path.name for path in selected}
    for existing in staged.iterdir():
        if existing.is_file() and existing.name not in selected_names:
            existing.unlink()
    for source in selected:
        shutil.copy2(source, staged / source.name)
    return staged


def _build_question(
    project: CourseProject,
    course_seed: _CourseSeed,
    seed: _QuestionSeed,
    index: int,
) -> Question:
    if not project.topics:
        raise ValueError(f"Imported course {project.course_id} has no topics")
    topic = project.topics[min(seed.topic_index, len(project.topics) - 1)]
    return Question(
        question_id=f"test-question-{course_seed.slug}-{index}",
        type=seed.type,
        difficulty=seed.difficulty,
        bilingual={
            "zh": {"stem": seed.stem_zh, "options": seed.options_zh, "explanation": seed.explanation_zh},
            "en": {"stem": seed.stem_en, "options": seed.options_en, "explanation": seed.explanation_en},
        },
        correct_answer=seed.answer,
        topic=topic,
        subtopic=topic.title,
        metadata={
            "course_id": project.course_id,
            "topic_title": topic.title,
            "source": "seven_course_test_seed",
            "source_ref_status": "verified",
            "created_at": _STAMP,
            "version": 1,
        },
    )


def _summary(seed: _CourseSeed) -> str:
    lines = [f"# {seed.title} 课程内容", "", "## 测试范围"]
    for _topic_id, title, keywords in seed.topics:
        lines.extend(["", f"### {title}", f"核心术语：{', '.join(keywords)}。"])
    lines.extend(["", "## 用途", "该课程用于跨学科导入、检索、出题、答题和数据迁移验收。"])
    return "\n".join(lines)


def _course_id(metadata: dict) -> str:
    return str((metadata or {}).get("course_id", "") or "").strip()
