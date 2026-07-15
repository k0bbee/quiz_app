"""Deterministic cross-discipline data for local end-to-end acceptance tests."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path
import shutil

from core.course_initializer import CourseInitializer
from core.course_index import attach_index_to_project, retrieve_course_source_refs
from core.question_validation import validate_question_quality
from models.course_project import CourseProject, CourseProjectManager, CourseTopic
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
class CrossDisciplineSeedReport:
    course_count: int
    question_count: int
    question_set_count: int


@dataclass(frozen=True)
class CrossDisciplineAuditReport:
    course_ids: tuple[str, ...]
    question_count: int
    question_set_count: int
    questions_per_course: dict[str, int]
    sets_per_course: dict[str, int]
    question_types: tuple[QuestionType, ...]
    question_types_per_course: dict[str, tuple[QuestionType, ...]]
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


_BASE_COURSES: tuple[_CourseSeed, ...] = (
    _CourseSeed(
        "computer-systems", "计算机系统", "system-level-io.md",
        (
            ("unix_file_io", "Unix 文件 I/O", ("file", "descriptor", "open", "read")),
            ("robust_io", "健壮 I/O", ("rio", "short count", "buffered", "unbuffered")),
            ("io_metadata_and_sockets", "元数据与套接字 I/O", ("metadata", "stat", "socket", "stream")),
        ),
        (
            _choice(QuestionType.MULTIPLE_CHOICE, 0,
                "Unix 的 open 调用成功时返回什么？",
                "What does a successful Unix open call return?",
                ("文件描述符", "文件全部内容", "目录树", "缓冲区大小"),
                ("A file descriptor", "The entire file", "A directory tree", "The buffer size"), "A",
                "文件描述符是进程后续访问已打开文件所用的非负整数标识。",
                "A file descriptor is the nonnegative integer handle used for later access."),
            _QuestionSeed(QuestionType.MATCHING, 1,
                "将 RIO 接口与用途配对。", "Match each RIO interface to its purpose.",
                {"left": [{"id": "rio_readn", "text": "rio_readn"}, {"id": "rio_readlineb", "text": "rio_readlineb"}],
                 "right": [{"id": "bytes", "text": "读取指定字节数"}, {"id": "line", "text": "按行缓冲读取"}]},
                {"left": [{"id": "rio_readn", "text": "rio_readn"}, {"id": "rio_readlineb", "text": "rio_readlineb"}],
                 "right": [{"id": "bytes", "text": "Read a requested byte count"}, {"id": "line", "text": "Read a buffered text line"}]},
                [["rio_readn", "bytes"], ["rio_readlineb", "line"]],
                "RIO 分别提供无缓冲定长读取和缓冲按行读取接口。",
                "RIO provides unbuffered fixed-count and buffered line-oriented interfaces."),
            _QuestionSeed(QuestionType.ORDERING, 2,
                "按一次普通 Unix 文件读取的顺序排列。", "Order a basic Unix file-read lifecycle.",
                [{"id": "open", "text": "打开文件"}, {"id": "read", "text": "用描述符读取"}, {"id": "close", "text": "关闭描述符"}],
                [{"id": "open", "text": "Open the file"}, {"id": "read", "text": "Read through the descriptor"}, {"id": "close", "text": "Close the descriptor"}],
                ["open", "read", "close"],
                "进程先获得文件描述符，再读取数据，最后释放描述符。",
                "The process obtains a descriptor, reads data, and finally releases it."),
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
            ("moral_objectivity", "道德客观性", ("objective", "moral", "facts", "relativism")),
            ("practical_reason", "实践理性", ("practical reason", "freedom", "desires", "choice")),
            ("ethical_methodology", "伦理学方法", ("methodology", "first order", "principles", "validity")),
        ),
        (
            _choice(QuestionType.SCENARIO_CHOICE, 0,
                "有人主张‘不存在道德客观性’，Nagel 认为该主张最终必须与什么竞争？",
                "Nagel says a denial of moral objectivity must ultimately compete with what?",
                ("具体的一阶道德判断", "词源统计", "个人喜好清单", "自然科学公式"),
                ("Specific first-order moral claims", "Etymological statistics", "Lists of preferences", "Natural-science formulas"), "A",
                "否定客观性的理论必须面对诸如压迫是否错误等具体道德主张。",
                "A denial of objectivity must confront specific claims such as whether oppression is wrong."),
            _text(QuestionType.SHORT_ANSWER, 1,
                "说明 Nagel 为什么认为实践理性使人无法简单逃避评价问题。",
                "Explain why Nagel thinks practical reason prevents us from simply escaping evaluative questions.",
                "当人能够反思自己的欲望和动机时，就必须判断是否按它们行动，因此不可避免地面对‘我应当做什么’。",
                "反思能力把动机转化为需要评价的行动理由。",
                "Reflection turns motives into reasons that must be evaluated when deciding what to do."),
            _text(QuestionType.FILL_IN_BLANK, 2,
                "Nagel 建议通过进行____道德理论研究，检验道德客观性是否可能。",
                "Nagel proposes doing ____ moral theorizing to test whether moral objectivity is possible.",
                ["一阶", "first-order", "first order"],
                "方法论要求先实际进行道德推理，观察能否形成可靠的方法、理由与原则。",
                "The method first practices moral reasoning to see whether reliable methods, reasons, and principles emerge."),
        ),
    ),
)


_SUPPLEMENTAL_QUESTIONS: dict[str, tuple[_QuestionSeed, ...]] = {
    "computer-systems": (
        _choice(QuestionType.TRUE_FALSE, 1, "Unix read 即使没有报错，也可能返回少于请求数量的字节。", "A Unix read may return fewer bytes than requested without reporting an error.", ("正确", "错误"), ("True", "False"), "true", "网络、终端和文件尾等场景都可能产生不足值。", "Networks, terminals, and end-of-file conditions can produce short counts."),
        _choice(QuestionType.SCENARIO_CHOICE, 1, "程序需要从网络套接字逐行读取文本，哪种接口最合适？", "A program needs to read text lines from a network socket. Which interface fits best?", ("rio_readlineb", "stat", "lseek", "close"), ("rio_readlineb", "stat", "lseek", "close"), "A", "缓冲 RIO 按行接口适合网络文本输入。", "The buffered RIO line interface is suitable for textual network input."),
        _text(QuestionType.FILL_IN_BLANK, 0, "进程用来标识已打开文件的非负整数称为文件____。", "The nonnegative integer used to identify an open file is a file ____.", ["描述符", "descriptor"], "Unix I/O 调用通过文件描述符引用已打开文件。", "Unix I/O calls refer to open files through file descriptors."),
        _text(QuestionType.SHORT_ANSWER, 2, "说明健壮 I/O 包为什么必须处理不足值。", "Explain why a robust I/O package must handle short counts.", "一次 read 或 write 可能只传输请求数据的一部分，健壮封装需要继续操作或正确处理结束与错误。", "不足值并不必然表示失败，忽略它会造成数据截断。", "A short count is not necessarily a failure; ignoring it can truncate data."),
    ),
    "microeconomics": (
        _choice(QuestionType.MULTIPLE_CHOICE, 0, "市场价格高于均衡价格时通常出现什么？", "What usually occurs when market price is above equilibrium?", ("短缺", "过剩", "需求曲线消失", "供给量为零"), ("Shortage", "Surplus", "Demand vanishes", "Supply becomes zero"), "B", "高价格下供给量超过需求量，形成过剩。", "At the higher price, quantity supplied exceeds quantity demanded, creating a surplus."),
        _QuestionSeed(QuestionType.MATCHING, 1, "将弹性类型与数值范围配对。", "Match elasticity type to its numerical range.", {"left":[{"id":"elastic","text":"有弹性"},{"id":"inelastic","text":"缺乏弹性"}],"right":[{"id":"gt1","text":"绝对值大于 1"},{"id":"lt1","text":"绝对值小于 1"}]}, {"left":[{"id":"elastic","text":"Elastic"},{"id":"inelastic","text":"Inelastic"}],"right":[{"id":"gt1","text":"Absolute value above 1"},{"id":"lt1","text":"Absolute value below 1"}]}, [["elastic","gt1"],["inelastic","lt1"]], "弹性绝对值大于一表示数量反应更强。", "An absolute elasticity above one indicates a stronger quantity response."),
        _QuestionSeed(QuestionType.ORDERING, 0, "按市场由短缺恢复均衡的典型过程排序。", "Order a typical adjustment from shortage toward equilibrium.", [{"id":"shortage","text":"需求量超过供给量"},{"id":"price","text":"价格上升"},{"id":"adjust","text":"需求量下降且供给量上升"}], [{"id":"shortage","text":"Quantity demanded exceeds supply"},{"id":"price","text":"Price rises"},{"id":"adjust","text":"Demand falls and supply rises"}], ["shortage","price","adjust"], "短缺给价格带来上行压力，随后买卖双方调整数量。", "A shortage puts upward pressure on price, after which buyers and sellers adjust quantities."),
        _text(QuestionType.FILL_IN_BLANK, 2, "选择某方案时放弃的最佳替代方案价值称为____。", "The value of the best alternative forgone by a choice is its ____.", ["机会成本", "opportunity cost"], "机会成本只取最佳被放弃方案的价值。", "Opportunity cost is the value of the single best forgone alternative."),
    ),
    "linear-algebra": (
        _choice(QuestionType.TRUE_FALSE, 1, "矩阵的秩不会超过其行数或列数中的较小者。", "Matrix rank cannot exceed the smaller of its row and column counts.", ("正确", "错误"), ("True", "False"), "true", "线性无关行和列的数量都受矩阵维数限制。", "Independent rows and columns are bounded by the matrix dimensions."),
        _choice(QuestionType.SCENARIO_CHOICE, 0, "三个二维向量是否可能线性无关？", "Can three vectors in a two-dimensional vector space be linearly independent?", ("总是可以", "不可能", "仅当都非零", "仅当长度相等"), ("Always", "No", "Only if nonzero", "Only if equal length"), "B", "二维空间中线性无关组最多含两个向量。", "A linearly independent set in two dimensions contains at most two vectors."),
        _QuestionSeed(QuestionType.MATCHING, 2, "将行变换与作用配对。", "Match each row operation to its action.", {"left":[{"id":"swap","text":"交换两行"},{"id":"scale","text":"一行乘非零常数"}],"right":[{"id":"reorder","text":"改变行的顺序"},{"id":"multiply","text":"缩放该行所有元素"}]}, {"left":[{"id":"swap","text":"Swap rows"},{"id":"scale","text":"Scale a row"}],"right":[{"id":"reorder","text":"Change row order"},{"id":"multiply","text":"Multiply every entry in the row"}]}, [["swap","reorder"],["scale","multiply"]], "两种操作都保持方程组解集不变。", "Both operations preserve the solution set of the system."),
        _text(QuestionType.SHORT_ANSWER, 1, "解释主元列为什么能帮助确定列空间的一组基。", "Explain why pivot columns help identify a basis for the column space.", "原矩阵中对应主元位置的列线性无关，并张成与全部列相同的列空间。", "必须取原矩阵的主元列，而不是行化简后矩阵的列。", "Use pivot columns from the original matrix, not columns of the reduced matrix."),
    ),
    "genetics": (
        _choice(QuestionType.MULTIPLE_CHOICE, 1, "DNA 复制时负责解开双链的酶是哪一种？", "Which enzyme unwinds the DNA double helix during replication?", ("解旋酶", "连接酶", "核糖体", "蛋白酶"), ("Helicase", "Ligase", "Ribosome", "Protease"), "A", "解旋酶破坏碱基间氢键并分开模板链。", "Helicase disrupts base-pair hydrogen bonds and separates the template strands."),
        _choice(QuestionType.SCENARIO_CHOICE, 2, "同卵双胞胎基因型近似相同但身高略有差异，最能说明什么？", "Identical twins have nearly the same genotype but slightly different heights. What does this best show?", ("表型只由基因决定", "环境也会影响表型", "DNA 不携带信息", "等位基因不存在"), ("Only genes determine phenotype", "Environment also affects phenotype", "DNA carries no information", "Alleles do not exist"), "B", "表型通常由基因型与环境共同作用形成。", "Phenotype commonly results from interaction between genotype and environment."),
        _QuestionSeed(QuestionType.ORDERING, 1, "按中心法则中的信息流顺序排列。", "Order the information flow in the central dogma.", [{"id":"dna","text":"DNA"},{"id":"rna","text":"RNA"},{"id":"protein","text":"蛋白质"}], [{"id":"dna","text":"DNA"},{"id":"rna","text":"RNA"},{"id":"protein","text":"Protein"}], ["dna","rna","protein"], "遗传信息通常先转录为 RNA，再翻译为蛋白质。", "Genetic information is generally transcribed to RNA and then translated to protein."),
        _text(QuestionType.SHORT_ANSWER, 0, "说明孟德尔分离定律在配子形成时的含义。", "Explain the law of segregation during gamete formation.", "一对等位基因在形成配子时彼此分离，因此每个配子只获得其中一个等位基因。", "受精后来自两个亲本的等位基因重新成对。", "Alleles from two parents pair again after fertilization."),
    ),
    "emergency-medicine": (
        _choice(QuestionType.MULTIPLE_CHOICE, 1, "分诊的核心目的是什么？", "What is the central purpose of triage?", ("按到达顺序处理", "按紧急程度分配优先级", "只记录姓名", "替代全部诊断"), ("Treat by arrival order", "Prioritize by urgency", "Record names only", "Replace all diagnosis"), "B", "分诊用于在资源有限时优先识别和处理最紧急患者。", "Triage identifies and prioritizes the most urgent patients when resources are limited."),
        _choice(QuestionType.TRUE_FALSE, 2, "休克早期可能出现心率加快而血压仍暂时正常。", "Early shock may present with tachycardia while blood pressure remains temporarily normal.", ("正确", "错误"), ("True", "False"), "true", "代偿机制可暂时维持血压，因此不能只靠低血压识别休克。", "Compensation can temporarily preserve blood pressure, so hypotension alone cannot rule shock in or out."),
        _QuestionSeed(QuestionType.MATCHING, 0, "将初步评估项目与观察内容配对。", "Match primary-assessment components to observations.", {"left":[{"id":"airway","text":"气道"},{"id":"breathing","text":"呼吸"}],"right":[{"id":"patency","text":"是否通畅及有无阻塞声"},{"id":"ventilation","text":"呼吸频率和胸廓起伏"}]}, {"left":[{"id":"airway","text":"Airway"},{"id":"breathing","text":"Breathing"}],"right":[{"id":"patency","text":"Patency and obstruction sounds"},{"id":"ventilation","text":"Rate and chest movement"}]}, [["airway","patency"],["breathing","ventilation"]], "气道关注通畅，呼吸关注通气表现。", "Airway assessment concerns patency; breathing assessment concerns ventilation."),
        _text(QuestionType.FILL_IN_BLANK, 1, "根据病情紧急程度给患者确定救治优先级的过程称为____。", "The process of assigning treatment priority according to urgency is called ____.", ["分诊", "triage"], "分诊不是完整诊断，而是快速确定优先顺序。", "Triage is rapid prioritization, not a complete diagnosis."),
    ),
    "case-law": (
        _choice(QuestionType.SCENARIO_CHOICE, 1, "一份案例摘要只复述事实却没有说明规则如何适用于事实，缺少哪个部分？", "A case brief states facts but never explains how the rule applies. Which part is missing?", ("争点", "适用分析", "案号", "当事人名单"), ("Issue", "Application analysis", "Docket number", "Party list"), "B", "适用分析负责把抽象规则与关键事实连接起来。", "Application analysis connects the abstract rule to the material facts."),
        _QuestionSeed(QuestionType.ORDERING, 1, "按 IRAC 案例分析结构排序。", "Order the IRAC case-analysis structure.", [{"id":"issue","text":"争点"},{"id":"rule","text":"规则"},{"id":"application","text":"适用"},{"id":"conclusion","text":"结论"}], [{"id":"issue","text":"Issue"},{"id":"rule","text":"Rule"},{"id":"application","text":"Application"},{"id":"conclusion","text":"Conclusion"}], ["issue","rule","application","conclusion"], "IRAC 先界定问题，再陈述规则、分析适用并给出结论。", "IRAC identifies the issue, states the rule, applies it, and concludes."),
        _text(QuestionType.FILL_IN_BLANK, 0, "下级法院通常应遵循有约束力的上级法院____。", "A lower court generally follows binding higher-court ____.", ["先例", "precedent"], "有约束力的先例促进相似案件适用法律的一致性。", "Binding precedent promotes consistent application of law in similar cases."),
        _text(QuestionType.SHORT_ANSWER, 2, "说明为什么案例摘要应区分关键事实与无关背景。", "Explain why a case brief should distinguish material facts from irrelevant background.", "关键事实影响法律规则的适用和裁判结果；无关背景会稀释争点并干扰类案比较。", "判断事实是否关键，应看改变该事实是否可能改变法律分析。", "A fact is material when changing it could change the legal analysis."),
    ),
    "ethics": (
        _choice(QuestionType.MULTIPLE_CHOICE, 0, "Nagel 认为判断道德客观性的合适起点是什么？", "What does Nagel treat as the appropriate starting point for assessing moral objectivity?", ("实际进行道德推理", "只研究抽象形而上学", "统计多数偏好", "暂停所有判断"), ("Engage in moral reasoning", "Study abstract metaphysics alone", "Count majority preferences", "Suspend every judgment"), "A", "他主张先进行一阶道德理论研究，再看可靠的方法和原则能否形成。", "He proposes first-order moral theorizing to see whether reliable methods and principles emerge."),
        _choice(QuestionType.TRUE_FALSE, 0, "Nagel 认为道德客观性必须依赖会因果作用于人的独立道德事实宇宙。", "Nagel says moral objectivity must depend on a separate universe of moral facts that causally affects us.", ("正确", "错误"), ("True", "False"), "false", "他明确认为客观性不依赖这种因果作用的道德事实图景。", "He explicitly denies that objectivity depends on moral facts causally impinging on us."),
        _QuestionSeed(QuestionType.MATCHING, 1, "将实践理性的环节与含义配对。", "Match stages of practical reason to their meaning.", {"left":[{"id":"recognize","text":"识别欲望与动机"},{"id":"evaluate","text":"提出评价问题"}],"right":[{"id":"reflect","text":"反思行动倾向"},{"id":"decide","text":"判断应当做什么"}]}, {"left":[{"id":"recognize","text":"Recognize desires and motives"},{"id":"evaluate","text":"Raise the evaluative question"}],"right":[{"id":"reflect","text":"Reflect on inclinations"},{"id":"decide","text":"Judge what one should do"}]}, [["recognize","reflect"],["evaluate","decide"]], "识别动机使行动倾向进入反思，并引出应当如何行动的问题。", "Recognizing motives makes inclinations objects of reflection and raises what one should do."),
        _QuestionSeed(QuestionType.ORDERING, 2, "按 Nagel 的方法排列。", "Order the stages of Nagel's method.", [{"id":"reason","text":"进行一阶道德推理"},{"id":"methods","text":"检验方法、理由与原则"},{"id":"objectivity","text":"评价客观性主张"}], [{"id":"reason","text":"Do first-order moral reasoning"},{"id":"methods","text":"Test methods, reasons, and principles"},{"id":"objectivity","text":"Assess the claim to objectivity"}], ["reason","methods","objectivity"], "先实践道德推理，再根据其可靠性评价客观性。", "Practice moral reasoning first, then assess objectivity through its reliability."),
    ),
}


_ADDITIONAL_COURSES: tuple[_CourseSeed, ...] = (
    _CourseSeed(
        "biology", "生物学", "mit-biology-recitation-1.pdf",
        (("cell_biology","细胞生物学",("cell","membrane","organelle")), ("biochemistry","生物化学",("enzyme","protein","metabolism")), ("gene_expression","基因表达",("dna","rna","protein"))),
        (
            _choice(QuestionType.MULTIPLE_CHOICE,0,"真核细胞与原核细胞相比通常具有哪一结构？","Which structure is generally present in eukaryotic but not prokaryotic cells?",("细胞核","核糖体","细胞膜","DNA"),("Nucleus","Ribosome","Cell membrane","DNA"),"A","真核细胞的遗传物质主要位于膜包围的细胞核中。","Eukaryotic genetic material is mainly enclosed within a membrane-bound nucleus."),
            _choice(QuestionType.TRUE_FALSE,1,"酶会降低反应的活化能，但不改变反应物与产物之间的自由能差。","Enzymes lower activation energy but do not change the free-energy difference between reactants and products.",( "正确","错误"),("True","False"),"true","酶改变反应速率而不改变反应的热力学平衡。","Enzymes alter reaction rate without changing thermodynamic equilibrium."),
            _QuestionSeed(QuestionType.MATCHING,2,"将过程与产物配对。","Match each process to its product.",{"left":[{"id":"transcription","text":"转录"},{"id":"translation","text":"翻译"}],"right":[{"id":"rna","text":"RNA"},{"id":"protein","text":"蛋白质"}]},{"left":[{"id":"transcription","text":"Transcription"},{"id":"translation","text":"Translation"}],"right":[{"id":"rna","text":"RNA"},{"id":"protein","text":"Protein"}]},[["transcription","rna"],["translation","protein"]],"转录以 DNA 为模板产生 RNA，翻译根据 RNA 合成蛋白质。","Transcription makes RNA from DNA; translation synthesizes protein from RNA."),
            _QuestionSeed(QuestionType.ORDERING,2,"按基因表达的一般顺序排列。","Order the general gene-expression sequence.",[{"id":"dna","text":"DNA"},{"id":"mrna","text":"mRNA"},{"id":"protein","text":"蛋白质"}],[{"id":"dna","text":"DNA"},{"id":"mrna","text":"mRNA"},{"id":"protein","text":"Protein"}],["dna","mrna","protein"],"DNA 先转录为 mRNA，再由核糖体翻译为蛋白质。","DNA is transcribed into mRNA, which ribosomes then translate into protein."),
            _choice(QuestionType.SCENARIO_CHOICE,1,"升高温度后某酶活性先增加再骤降，最可能的原因是什么？","An enzyme becomes faster as temperature rises and then loses activity sharply. What is most likely?",("酶发生变性","底物变成 DNA","自由能永久归零","细胞膜消失"),("The enzyme denatures","Substrate becomes DNA","Free energy becomes zero","The membrane disappears"),"A","过高温度会破坏维持酶活性构象的相互作用。","Excess heat disrupts interactions that maintain the enzyme's active conformation."),
            _text(QuestionType.FILL_IN_BLANK,0,"细胞中合成蛋白质的核糖核蛋白复合体称为____。","The ribonucleoprotein complex that synthesizes proteins is the ____.",["核糖体","ribosome"],"核糖体读取 mRNA 并催化肽链形成。","The ribosome reads mRNA and catalyzes peptide-chain formation."),
            _text(QuestionType.SHORT_ANSWER,0,"解释同一个体不同细胞为何拥有相同 DNA 却表现出不同功能。","Explain why cells in one organism can share DNA yet perform different functions.","不同细胞选择性表达不同基因，产生不同的 RNA 和蛋白质组合，从而形成不同结构与功能。","细胞差异主要来自基因表达调控，而不是每种细胞拥有完全不同的基因组。","Cell differences mainly arise from regulation of gene expression, not wholly different genomes."),
        ),
    ),
    _CourseSeed(
        "physics", "物理学", "mit-8-09-advanced-classical-mechanics.pdf",
        (("newtonian_mechanics","牛顿力学",("force","mass","acceleration")), ("energy_momentum","能量与动量",("energy","momentum","conservation")), ("oscillations","振动与动力系统",("oscillation","phase","stability"))),
        (
            _choice(QuestionType.MULTIPLE_CHOICE,0,"质量不变的物体所受合外力等于什么？","For constant mass, net force equals what?",("质量乘加速度","质量除以速度","动量乘时间","位移除以能量"),("Mass times acceleration","Mass divided by velocity","Momentum times time","Displacement divided by energy"),"A","牛顿第二定律在质量不变时写作 F=ma。","Newton's second law for constant mass is F=ma."),
            _choice(QuestionType.TRUE_FALSE,1,"只有保守力做功时，系统的机械能保持不变。","Mechanical energy remains constant when only conservative forces do work.",( "正确","错误"),("True","False"),"true","保守力在动能与势能之间转换而不耗散机械能。","Conservative forces exchange kinetic and potential energy without dissipating mechanical energy."),
            _QuestionSeed(QuestionType.MATCHING,1,"将物理量与表达式配对。","Match each quantity to its expression.",{"left":[{"id":"momentum","text":"动量"},{"id":"kinetic","text":"平动动能"}],"right":[{"id":"mv","text":"mv"},{"id":"half","text":"½mv²"}]},{"left":[{"id":"momentum","text":"Momentum"},{"id":"kinetic","text":"Translational kinetic energy"}],"right":[{"id":"mv","text":"mv"},{"id":"half","text":"½mv²"}]},[["momentum","mv"],["kinetic","half"]],"动量与速度一次成正比，动能与速度平方成正比。","Momentum is linear in velocity, while kinetic energy is quadratic in velocity."),
            _QuestionSeed(QuestionType.ORDERING,0,"按建立经典力学模型的一般过程排序。","Order a typical classical-mechanics modeling workflow.",[{"id":"system","text":"确定系统与坐标"},{"id":"forces","text":"列出相互作用和约束"},{"id":"equations","text":"写出运动方程"},{"id":"solve","text":"结合初始条件求解"}],[{"id":"system","text":"Define system and coordinates"},{"id":"forces","text":"List interactions and constraints"},{"id":"equations","text":"Write equations of motion"},{"id":"solve","text":"Solve with initial conditions"}],["system","forces","equations","solve"],"明确系统后才能正确列力和约束，再由方程及初始条件确定运动。","Defining the system precedes forces, equations, and solution with initial conditions."),
            _choice(QuestionType.SCENARIO_CHOICE,2,"小振幅单摆近似满足哪类运动？","A small-angle pendulum approximately exhibits which motion?",("简谐运动","匀速直线运动","完全随机运动","静止"),("Simple harmonic motion","Uniform linear motion","Completely random motion","Rest"),"A","小角度下 sinθ≈θ，恢复力矩与角位移近似成正比。","For small angles sin theta is approximately theta, making restoring torque proportional to displacement."),
            _text(QuestionType.FILL_IN_BLANK,1,"若系统不受外力冲量，总____保持不变。","With no external impulse, total ____ is conserved.",["动量","momentum"],"动量守恒来自系统所受外力冲量为零。","Momentum conservation follows when the system receives no external impulse."),
            _text(QuestionType.SHORT_ANSWER,0,"说明惯性参考系在牛顿力学中的作用。","Explain the role of inertial reference frames in Newtonian mechanics.","惯性系中不受合力的物体保持匀速直线运动，牛顿定律可直接使用而无需引入惯性力。","在加速或旋转参考系中通常需要加入离心力、科里奥利力等惯性力。","Accelerating or rotating frames generally require fictitious forces such as centrifugal or Coriolis forces."),
        ),
    ),
    _CourseSeed(
        "philosophy", "哲学导论", "mit-philosophy-handout-1.pdf",
        (("analytic_argument","分析哲学与论证",("argument","premise","validity")), ("mind_and_identity","心灵与人格同一性",("mind","identity","physicalism")), ("free_will_responsibility","自由意志与责任",("freedom","responsibility","compatibilism"))),
        (
            _choice(QuestionType.MULTIPLE_CHOICE,0,"在演绎论证中，‘有效’主要表示什么？","In a deductive argument, what does validity primarily mean?",("若前提为真则结论不可能为假","所有前提事实上都为真","结论广受欢迎","论证文字很长"),("If premises are true, the conclusion cannot be false","Every premise is actually true","The conclusion is popular","The argument is long"),"A","有效性描述前提与结论之间的必然支持关系。","Validity describes the necessary support relation between premises and conclusion."),
            _choice(QuestionType.TRUE_FALSE,1,"人格同一性问题只是在询问两个人是否长得相似。","The problem of personal identity asks only whether two people look alike.",( "正确","错误"),("True","False"),"false","人格同一性研究一个人在时间中保持为同一主体的条件。","Personal identity studies conditions under which a person remains the same subject over time."),
            _QuestionSeed(QuestionType.MATCHING,2,"将立场与主张配对。","Match each position to its claim.",{"left":[{"id":"compat","text":"相容论"},{"id":"incompat","text":"不相容论"}],"right":[{"id":"can","text":"决定论与自由意志可以共存"},{"id":"cannot","text":"决定论与自由意志不能共存"}]},{"left":[{"id":"compat","text":"Compatibilism"},{"id":"incompat","text":"Incompatibilism"}],"right":[{"id":"can","text":"Determinism and free will can coexist"},{"id":"cannot","text":"Determinism and free will cannot coexist"}]},[["compat","can"],["incompat","cannot"]],"两种立场分歧在于决定论是否排除自由意志。","The positions disagree over whether determinism rules out free will."),
            _QuestionSeed(QuestionType.ORDERING,0,"按分析一个哲学论证的步骤排序。","Order the steps for analyzing a philosophical argument.",[{"id":"conclusion","text":"识别结论"},{"id":"premises","text":"列出前提"},{"id":"validity","text":"检查推理关系"},{"id":"soundness","text":"评价前提真实性"}],[{"id":"conclusion","text":"Identify conclusion"},{"id":"premises","text":"List premises"},{"id":"validity","text":"Check inference"},{"id":"soundness","text":"Assess premise truth"}],["conclusion","premises","validity","soundness"],"先重构论证，再分别评价推理形式与前提。","Reconstruct the argument before assessing inference and premises separately."),
            _choice(QuestionType.SCENARIO_CHOICE,1,"某思想实验设想人的心理连续性被复制到另一身体，主要挑战什么问题？","A thought experiment copies a person's psychological continuity into another body. What issue does it target?",("人格同一性的标准","供求均衡","矩阵的秩","诉讼时效"),("Criterion of personal identity","Market equilibrium","Matrix rank","Limitation period"),"A","此类思想实验检验身体连续性与心理连续性哪一个构成同一性。","Such cases test whether bodily or psychological continuity constitutes identity."),
            _text(QuestionType.FILL_IN_BLANK,0,"前提为真且推理有效的演绎论证称为____论证。","A deductive argument with true premises and valid inference is ____.",["可靠的","sound"],"可靠性要求有效性与全部前提为真。","Soundness requires validity and true premises."),
            _text(QuestionType.SHORT_ANSWER,2,"解释相容论如何尝试调和决定论与道德责任。","Explain how compatibilism attempts to reconcile determinism with moral responsibility.","相容论通常把自由理解为行动出自行为者自身的理由和欲望且不受外在强迫，而非要求行为完全无因。","因此即使行为有因果来源，行为者仍可能对反映其意愿的行动负责。","Thus causally determined actions may still ground responsibility when they express the agent's will."),
        ),
    ),
)


_DIFFICULTY_CYCLE = (
    Difficulty.EASY,
    Difficulty.MEDIUM,
    Difficulty.HARD,
    Difficulty.EASY,
    Difficulty.MEDIUM,
    Difficulty.HARD,
    Difficulty.MEDIUM,
)


def _balance_question_difficulties(questions: tuple[_QuestionSeed, ...]) -> tuple[_QuestionSeed, ...]:
    return tuple(
        replace(question, difficulty=_DIFFICULTY_CYCLE[index % len(_DIFFICULTY_CYCLE)])
        for index, question in enumerate(questions)
    )


_COURSES = tuple(
    replace(
        course,
        questions=_balance_question_difficulties(
            course.questions + _SUPPLEMENTAL_QUESTIONS[course.slug]
        ),
    )
    for course in _BASE_COURSES
) + tuple(
    replace(course, questions=_balance_question_difficulties(course.questions))
    for course in _ADDITIONAL_COURSES
)

CROSS_DISCIPLINE_COURSE_IDS = tuple(f"test-course-{course.slug}" for course in _COURSES)

CROSS_DISCIPLINE_SOURCES: dict[str, tuple[str, ...]] = {
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
    "biology": ("mit-biology-*.pdf", "biology.md"),
    "physics": ("mit-8-09-advanced-classical-mechanics.pdf", "physics.md"),
    "philosophy": ("mit-philosophy-handout-*.pdf", "philosophy.md"),
}

def seed_cross_discipline_data(
    root: str | Path,
    *,
    source_root: str | Path,
) -> CrossDisciplineSeedReport:
    """Import the cross-discipline original-source groups and bind test questions."""
    data_root = Path(root).resolve()
    original_root = Path(source_root).resolve()
    if not original_root.is_dir():
        raise FileNotFoundError(f"Original source root does not exist: {original_root}")
    course_manager = CourseProjectManager(str(data_root / "courses"))
    question_bank = QuestionBank(str(data_root / "questions"))
    set_manager = SetManager(str(data_root / "question_sets"))
    initializer = CourseInitializer(manager=course_manager)

    pending_questions: list[Question] = []
    pending_sets: list[QuestionSet] = []
    for course_seed in _COURSES:
        staged_folder = _stage_original_sources(original_root, data_root, course_seed.slug)
        project = initializer.initialize(
            str(staged_folder),
            title=course_seed.title,
            make_current=False,
            course_id=f"test-course-{course_seed.slug}",
        )
        project = _apply_seed_topics(project, course_seed)
        if not course_manager.save(project, make_current=False):
            raise OSError(f"Failed to save semantic topics for {project.course_id}")
        question_ids: list[str] = []
        for index, question_seed in enumerate(course_seed.questions, start=1):
            question = _build_question(project, course_seed, question_seed, index)
            pending_questions.append(question)
            question_ids.append(question.question_id)
        pending_sets.append(QuestionSet(
            set_id=f"test-set-{course_seed.slug}",
            title={"zh": f"{course_seed.title}综合练习", "en": f"{course_seed.slug.replace('-', ' ').title()} Practice"},
            description={"zh": "跨学科端到端测试题集", "en": "Cross-discipline end-to-end test set"},
            topics=list(project.topics),
            difficulty=Difficulty.MEDIUM,
            estimated_minutes=10,
            questions=question_ids,
            metadata={"course_id": project.course_id, "source": "cross_discipline_test_seed", "created_at": _STAMP},
        ))

    question_count = question_bank.save_many(pending_questions)
    if question_count != len(pending_questions):
        raise OSError(
            f"Failed to save all test questions ({question_count}/{len(pending_questions)})"
        )
    for question_set in pending_sets:
        if not set_manager.save(question_set):
            raise OSError(f"Failed to save test set {question_set.set_id}")

    return CrossDisciplineSeedReport(len(_COURSES), question_count, len(_COURSES))


def audit_cross_discipline_data(root: str | Path) -> CrossDisciplineAuditReport:
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
    return CrossDisciplineAuditReport(
        course_ids=tuple(sorted(course_ids)),
        question_count=len(questions),
        question_set_count=len(question_sets),
        questions_per_course=dict(questions_per_course),
        sets_per_course=dict(sets_per_course),
        question_types=tuple(sorted({question.type for question in questions}, key=lambda item: item.value)),
        question_types_per_course={
            course_id: tuple(sorted(
                {question.type for question in questions if _course_id(question.metadata) == course_id},
                key=lambda item: item.value,
            ))
            for course_id in sorted(course_ids)
        },
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
    candidates = CROSS_DISCIPLINE_SOURCES[slug]
    selected = sorted({
        path.resolve()
        for pattern in candidates
        for path in source_root.glob(pattern)
        if path.is_file()
    }, key=lambda path: path.name)
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
    intended_topic_id = course_seed.topics[seed.topic_index][0]
    topic = next(
        (candidate for candidate in project.topics if candidate.topic_id == intended_topic_id),
        None,
    )
    if topic is None:
        raise ValueError(
            f"Imported course {project.course_id} is missing semantic topic {intended_topic_id}"
        )
    source_queries = [
        topic.topic_id,
        seed.stem_en,
        seed.explanation_en,
        *_correct_answer_queries(seed),
    ]
    source_refs = retrieve_course_source_refs(project, source_queries, limit=1)
    if not source_refs:
        raise ValueError(
            f"Imported course {project.course_id} has no source evidence for {topic.topic_id}"
        )
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
            "source": "cross_discipline_test_seed",
            "source_ref_status": "verified",
            "source_refs": source_refs,
            "created_at": _STAMP,
            "version": 1,
        },
    )


def _apply_seed_topics(project: CourseProject, course_seed: _CourseSeed) -> CourseProject:
    """Install stable semantic topics and rebuild source attribution for the fixture."""
    project.topics = [
        CourseTopic(topic_id=topic_id, title=title, keywords=list(keywords))
        for topic_id, title, keywords in course_seed.topics
    ]
    for document in project.documents:
        document.pop("_source_index", None)
    attach_index_to_project(project)

    topic_ids = [topic.topic_id for topic in project.topics]
    profile = dict(project.generation_profile or {})
    profile["selected_topics"] = topic_ids
    profile["topic_weights"] = _equal_topic_weights(topic_ids)
    project.generation_profile = profile
    return project


def _equal_topic_weights(topic_ids: list[str]) -> dict[str, int]:
    if not topic_ids:
        return {}
    share, remainder = divmod(100, len(topic_ids))
    return {
        topic_id: share + (1 if index < remainder else 0)
        for index, topic_id in enumerate(topic_ids)
    }


def _correct_answer_queries(seed: _QuestionSeed) -> list[str]:
    if seed.type in {QuestionType.MULTIPLE_CHOICE, QuestionType.SCENARIO_CHOICE}:
        options = seed.options_en if isinstance(seed.options_en, (list, tuple)) else ()
        answer = str(seed.answer or "").strip().upper()
        index = ord(answer) - ord("A") if len(answer) == 1 and answer.isalpha() else -1
        if 0 <= index < len(options):
            option = options[index]
            return [str(option.get("text", "") if isinstance(option, dict) else option)]
        return []
    if seed.type == QuestionType.FILL_IN_BLANK:
        answers = seed.answer if isinstance(seed.answer, list) else [seed.answer]
        return [str(answer) for answer in answers if str(answer or "").strip()]
    return []


def _summary(seed: _CourseSeed) -> str:
    lines = [f"# {seed.title} 课程内容", "", "## 测试范围"]
    for _topic_id, title, keywords in seed.topics:
        lines.extend(["", f"### {title}", f"核心术语：{', '.join(keywords)}。"])
    lines.extend(["", "## 用途", "该课程用于跨学科导入、检索、出题、答题和数据迁移验收。"])
    return "\n".join(lines)


def _course_id(metadata: dict) -> str:
    return str((metadata or {}).get("course_id", "") or "").strip()
