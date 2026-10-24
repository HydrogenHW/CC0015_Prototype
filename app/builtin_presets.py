"""内置学科预设：每个领域一份中英混合的词表。

词的挑选标准：**课堂上会反复出现、且语音识别容易听错**的词。
不是把教科书目录抄一遍——「函数」这种词模型本来就认识，
而「本征值」「焓变」「减数分裂」这类才是热词该管的。

中医那份在 glossary.json 里（267 条，跟翻译层的强制译法同源），
其余几份都是这里手写的。
"""

BUILTIN: list[dict] = [
    {
        "id": "tcm",
        "name": "中医 / TCM",
        "zh": [],          # 中医的词来自 glossary，运行时空着，由 presets 注入
        "en": [],
    },
    {
        "id": "cs",
        "name": "计算机 / Computer Science",
        "zh": [
            "算法", "数据结构", "链表", "数组", "栈", "队列", "哈希表", "二叉树", "图论",
            "递归", "时间复杂度", "空间复杂度", "编译", "解释器", "操作系统", "进程", "线程",
            "内存", "缓存", "数据库", "索引", "事务", "网络协议", "接口", "继承", "多态",
            "封装", "并发", "分布式", "虚拟化", "机器学习", "神经网络", "梯度下降",
            "正则化", "过拟合", "超参数", "特征向量", "反向传播", "卷积", "注意力机制",
        ],
        "en": [
            "algorithm", "data structure", "linked list", "array", "stack", "queue",
            "hash table", "binary tree", "graph", "recursion", "time complexity",
            "space complexity", "compiler", "interpreter", "operating system", "process",
            "thread", "memory", "cache", "database", "index", "transaction",
            "network protocol", "interface", "inheritance", "polymorphism", "encapsulation",
            "concurrency", "distributed system", "virtualization", "machine learning",
            "neural network", "gradient descent", "regularization", "overfitting",
            "hyperparameter", "eigenvector", "backpropagation", "convolution", "attention mechanism",
        ],
    },
    {
        "id": "math",
        "name": "数学 / Mathematics",
        "zh": [
            "函数", "导数", "积分", "极限", "连续", "可导", "微分", "偏导数", "梯度",
            "矩阵", "向量", "行列式", "特征值", "特征向量", "线性变换", "概率",
            "随机变量", "期望", "方差", "正态分布", "假设检验", "置信区间", "回归",
            "级数", "收敛", "发散", "泰勒展开", "傅里叶变换", "拉普拉斯变换", "拓扑",
            "群论", "同构", "素数", "整除", "模运算", "映射", "奇点", "洛必达法则",
        ],
        "en": [
            "function", "derivative", "integral", "limit", "continuity", "differentiable",
            "differential", "partial derivative", "gradient", "matrix", "vector",
            "determinant", "eigenvalue", "eigenvector", "linear transformation",
            "probability", "random variable", "expectation", "variance", "normal distribution",
            "hypothesis test", "confidence interval", "regression", "series", "convergence",
            "divergence", "Taylor expansion", "Fourier transform", "Laplace transform",
            "topology", "group theory", "isomorphism", "prime", "divisibility",
            "modular arithmetic", "mapping", "singularity", "L'Hopital's rule",
        ],
    },
    {
        "id": "physics",
        "name": "物理 / Physics",
        "zh": [
            "质点", "位移", "加速度", "牛顿定律", "动量", "冲量", "动能", "势能",
            "机械能守恒", "角动量", "力矩", "转动惯量", "万有引力", "电场", "磁场",
            "电势", "电容", "电感", "电流", "电压", "电阻", "电磁感应", "麦克斯韦方程",
            "波长", "频率", "振幅", "干涉", "衍射", "折射", "热力学", "熵增", "内能",
            "理想气体", "量子态", "波函数", "测不准原理", "薛定谔方程", "光子", "相对论",
        ],
        "en": [
            "particle", "displacement", "acceleration", "Newton's law", "momentum",
            "impulse", "kinetic energy", "potential energy",
            "conservation of mechanical energy", "angular momentum", "torque",
            "moment of inertia", "universal gravitation", "electric field", "magnetic field",
            "electric potential", "capacitance", "inductance", "current", "voltage",
            "resistance", "electromagnetic induction", "Maxwell's equations", "wavelength",
            "frequency", "amplitude", "interference", "diffraction", "refraction",
            "thermodynamics", "entropy", "internal energy", "ideal gas", "quantum state",
            "wave function", "uncertainty principle", "Schrodinger equation", "photon",
            "relativity",
        ],
    },
    {
        "id": "chem",
        "name": "化学 / Chemistry",
        "zh": [
            "原子", "分子", "离子", "共价键", "离子键", "化学式", "摩尔", "摩尔质量",
            "浓度", "溶解度", "酸碱", "中和反应", "氧化还原", "催化剂", "化学平衡",
            "反应速率", "焓变", "熵变", "吉布斯自由能", "有机物", "烃", "醇", "醛", "酮",
            "羧酸", "酯化", "苯环", "聚合物", "异构体", "官能团", "电解", "电泳",
            "色谱", "滴定", "配位化合物",
        ],
        "en": [
            "atom", "molecule", "ion", "covalent bond", "ionic bond", "chemical formula",
            "mole", "molar mass", "concentration", "solubility", "acid-base",
            "neutralization", "redox", "catalyst", "chemical equilibrium", "reaction rate",
            "enthalpy", "entropy", "Gibbs free energy", "organic compound", "hydrocarbon",
            "alcohol", "aldehyde", "ketone", "carboxylic acid", "esterification",
            "benzene ring", "polymer", "isomer", "functional group", "electrolysis",
            "electrophoresis", "chromatography", "titration", "coordination compound",
        ],
    },
    {
        "id": "bio",
        "name": "生物 / Biology",
        "zh": [
            "细胞膜", "细胞核", "线粒体", "叶绿体", "核糖体", "基因", "染色体", "转录",
            "翻译", "复制", "突变", "蛋白质", "酶", "代谢", "光合作用", "呼吸作用",
            "有丝分裂", "减数分裂", "显性", "隐性", "等位基因", "种群", "生态系统",
            "食物链", "自然选择", "免疫", "抗体", "神经元", "突触", "内环境稳态",
            "基因表达", "细胞凋亡",
        ],
        "en": [
            "cell membrane", "nucleus", "mitochondrion", "chloroplast", "ribosome",
            "gene", "chromosome", "transcription", "translation", "replication",
            "mutation", "protein", "enzyme", "metabolism", "photosynthesis",
            "cellular respiration", "mitosis", "meiosis", "dominant", "recessive",
            "allele", "population", "ecosystem", "food chain", "natural selection",
            "immunity", "antibody", "neuron", "synapse", "homeostasis",
            "gene expression", "apoptosis",
        ],
    },
    {
        "id": "econ",
        "name": "经济 / Economics",
        "zh": [
            "供给", "需求", "均衡价格", "弹性", "边际效用", "机会成本", "通货膨胀",
            "通货紧缩", "利率", "汇率", "国内生产总值", "货币政策", "财政政策",
            "市场结构", "垄断", "寡头", "外部性", "公共品", "博弈论", "纳什均衡",
            "贴现", "净现值", "资产负债表", "现金流", "规模经济", "比较优势",
            "国际贸易", "关税", "中央银行", "商业银行", "债券", "边际成本",
        ],
        "en": [
            "supply", "demand", "equilibrium price", "elasticity", "marginal utility",
            "opportunity cost", "inflation", "deflation", "interest rate", "exchange rate",
            "GDP", "monetary policy", "fiscal policy", "market structure", "monopoly",
            "oligopoly", "externality", "public goods", "game theory", "Nash equilibrium",
            "discounting", "net present value", "balance sheet", "cash flow",
            "economies of scale", "comparative advantage", "international trade", "tariff",
            "central bank", "commercial bank", "bond", "marginal cost",
        ],
    },
    {
        "id": "law",
        "name": "法律 / Law",
        "zh": [
            "合同", "要约", "承诺", "违约责任", "侵权", "损害赔偿", "所有权", "物权",
            "债权", "知识产权", "专利", "商标", "著作权", "刑事责任", "民事责任",
            "犯罪构成", "正当防卫", "紧急避险", "诉讼", "管辖", "证据", "举证责任",
            "判决", "上诉", "仲裁", "调解", "代理", "法人", "自然人", "诉讼时效",
        ],
        "en": [
            "contract", "offer", "acceptance", "breach of contract", "tort", "damages",
            "ownership", "property right", "claim", "intellectual property", "patent",
            "trademark", "copyright", "criminal liability", "civil liability",
            "elements of crime", "self-defense", "necessity", "litigation", "jurisdiction",
            "evidence", "burden of proof", "judgment", "appeal", "arbitration",
            "mediation", "agency", "legal person", "natural person", "statute of limitations",
        ],
    },
    {
        "id": "med",
        "name": "医学 / Medicine",
        "zh": [
            "症状", "体征", "鉴别诊断", "预后", "并发症", "感染", "炎症", "肿瘤",
            "良性", "恶性", "高血压", "糖尿病", "冠心病", "肺炎", "哮喘", "肾衰竭",
            "肝功能", "血常规", "心电图", "超声", "核磁共振", "病理", "活检", "抗生素",
            "激素", "输液", "麻醉", "康复", "护理", "疫苗", "免疫接种", "流行病学",
            "收缩压", "舒张压",
        ],
        "en": [
            "symptom", "sign", "differential diagnosis", "prognosis", "complication",
            "infection", "inflammation", "tumor", "benign", "malignant", "hypertension",
            "diabetes", "coronary heart disease", "pneumonia", "asthma", "renal failure",
            "liver function", "complete blood count", "ECG", "ultrasound", "MRI",
            "pathology", "biopsy", "antibiotic", "hormone", "infusion", "anesthesia",
            "rehabilitation", "nursing", "vaccine", "immunization", "epidemiology",
            "systolic pressure", "diastolic pressure",
        ],
    },
]
