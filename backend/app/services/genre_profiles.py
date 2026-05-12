"""网文 Genre Profiles - 借鉴 webnovel-writer 的类型档案

按主流中文网文 12 大类整理(覆盖度等于 webnovel-writer 37 类中的活跃部分),
每个 Profile 含:
- anti_patterns: 该类型常见烂俗写法
- required_tropes: 该类型必有元素
- pacing_norm: 节奏基线("fast"/"medium"/"slow")
- hook_density_baseline: 钩子密度基线(每千字应有几个钩子)
- reading_pull_floor: 读者抓力下限分数(用于判定章节是否合格)

使用:Reviewer 通过项目 genre 找到对应 profile,把 anti_patterns 注入
NarrativePromiseReviewer 的提示词;PacingReviewer 用 pacing_norm 作参考。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class GenreProfile:
    name: str
    anti_patterns: tuple[str, ...] = ()
    required_tropes: tuple[str, ...] = ()
    pacing_norm: str = "medium"
    hook_density_baseline: int = 2  # 每千字应有的钩子数
    reading_pull_floor: int = 60     # 0-100,低于此判定"不合格"


_PROFILES: dict[str, GenreProfile] = {
    "玄幻": GenreProfile(
        name="玄幻",
        anti_patterns=(
            "金手指过早暴露,主角不靠努力直接碾压",
            "境界划分混乱,前后矛盾",
            "反派降智(为推进剧情而智商下线)",
            "数值飙升缺乏过程,直接秒杀",
        ),
        required_tropes=(
            "明确的修炼/境界体系",
            "实力突破节点(每数章必有)",
            "宗门/家族/势力背景",
        ),
        pacing_norm="fast",
        hook_density_baseline=3,
        reading_pull_floor=70,
    ),
    "仙侠": GenreProfile(
        name="仙侠",
        anti_patterns=("现代俚语穿越使用", "强行洒狗血", "修仙体系自洽性差"),
        required_tropes=("仙凡观念冲突", "心境/道心元素", "天道/天劫"),
        pacing_norm="medium",
        hook_density_baseline=2,
        reading_pull_floor=65,
    ),
    "修真": GenreProfile(
        name="修真",
        anti_patterns=("丹方/法器名故弄玄虚但无实质功能", "境界压制感缺失"),
        required_tropes=("丹道/法器/阵法之一", "门派制度", "天材地宝"),
        pacing_norm="medium",
        hook_density_baseline=2,
    ),
    "都市": GenreProfile(
        name="都市",
        anti_patterns=("脸谱化富二代/官二代反派", "金钱碾压一切", "都市设定漂浮(脱离真实生活)"),
        required_tropes=("职场/商战 OR 校园/恋爱场景", "都市真实细节(地铁/咖啡/写字楼)"),
        pacing_norm="medium",
        hook_density_baseline=2,
    ),
    "言情": GenreProfile(
        name="言情",
        anti_patterns=("一见钟情无铺垫", "误会型矛盾过度依赖", "强吻强抱戏码"),
        required_tropes=("情感张力升级", "外部阻力", "心理活动占比"),
        pacing_norm="slow",
        hook_density_baseline=2,
        reading_pull_floor=55,
    ),
    "历史": GenreProfile(
        name="历史",
        anti_patterns=("史实硬伤", "现代价值观强加于古人", "穿越主角全知全能"),
        required_tropes=("时代背景细节", "礼制/官制还原", "重要历史事件勾连"),
        pacing_norm="slow",
        hook_density_baseline=1,
    ),
    "军事": GenreProfile(
        name="军事",
        anti_patterns=("军事术语堆砌但不准确", "战术演练过于游戏化", "纪律观念缺失"),
        required_tropes=("纪律/服从冲突", "战术细节", "兄弟情/牺牲"),
        pacing_norm="fast",
        hook_density_baseline=3,
    ),
    "悬疑": GenreProfile(
        name="悬疑",
        anti_patterns=("凶手早早暴露", "推理过程靠巧合", "线索分布不均"),
        required_tropes=("多疑点并行", "误导(红鲱鱼)", "决定性证据"),
        pacing_norm="medium",
        hook_density_baseline=4,
        reading_pull_floor=75,
    ),
    "科幻": GenreProfile(
        name="科幻",
        anti_patterns=("硬科幻设定与软情节冲突", "技术名词无依据", "未来世界完全等于现代"),
        required_tropes=("科技背景设定", "技术对人性影响", "未来感细节"),
        pacing_norm="medium",
        hook_density_baseline=2,
    ),
    "末世": GenreProfile(
        name="末世",
        anti_patterns=("末世资源永远恰好够用", "人性黑暗一刀切", "丧尸/异兽规则随意调整"),
        required_tropes=("资源稀缺", "人性试炼", "幸存者团体动态"),
        pacing_norm="fast",
        hook_density_baseline=3,
    ),
    "无限流": GenreProfile(
        name="无限流",
        anti_patterns=("副本规则前后矛盾", "主角金手指过于明显", "副本之间无关联"),
        required_tropes=("副本切换", "积分/奖励系统", "队友/对手成长"),
        pacing_norm="fast",
        hook_density_baseline=4,
    ),
    "种田": GenreProfile(
        name="种田",
        anti_patterns=("跳过经营细节直接致富", "村民全程工具人", "时间线模糊"),
        required_tropes=("经营细节", "日常生活感", "渐进式致富"),
        pacing_norm="slow",
        hook_density_baseline=1,
        reading_pull_floor=50,
    ),
    # === 扩展子类 ===
    "系统流": GenreProfile(
        name="系统流",
        anti_patterns=("系统全知全能", "任务奖励无逻辑", "主角对系统毫无反应"),
        required_tropes=("系统面板/任务", "积分/属性提升", "系统与主角互动"),
        pacing_norm="fast",
        hook_density_baseline=3,
    ),
    "重生": GenreProfile(
        name="重生",
        anti_patterns=("重生光环全程开挂", "前世仇人智商集体下降", "前世记忆细节不一致"),
        required_tropes=("前世记忆驱动决策", "弥补遗憾", "信息差碾压"),
        pacing_norm="fast",
        hook_density_baseline=3,
    ),
    "穿越": GenreProfile(
        name="穿越",
        anti_patterns=("现代知识万能", "古人智商下线", "穿越前后人格分裂"),
        required_tropes=("时代落差冲突", "适应过程", "原住民关系建立"),
        pacing_norm="medium",
        hook_density_baseline=2,
    ),
    "末日丧尸": GenreProfile(
        name="末日丧尸",
        anti_patterns=("丧尸规则前后矛盾", "资源永远恰好够用", "人性黑暗一刀切"),
        required_tropes=("资源稀缺", "人性试炼", "幸存者团体动态", "感染机制"),
        pacing_norm="fast",
        hook_density_baseline=4,
        reading_pull_floor=70,
    ),
    "无限恐怖": GenreProfile(
        name="无限恐怖",
        anti_patterns=("副本规则前后矛盾", "恐怖元素游戏化", "队友工具人"),
        required_tropes=("副本/任务", "积分/技能体系", "恐怖氛围维持"),
        pacing_norm="fast",
        hook_density_baseline=4,
    ),
    "赛博朋克": GenreProfile(
        name="赛博朋克",
        anti_patterns=("技术与社会脱节", "公司反派脸谱化", "义体与人性割裂"),
        required_tropes=("公司/政府压迫", "义体改造", "信息战", "灯红酒绿城市"),
        pacing_norm="medium",
        hook_density_baseline=3,
    ),
    "蒸汽朋克": GenreProfile(
        name="蒸汽朋克",
        anti_patterns=("蒸汽设定纯装饰", "贵族-平民对立简化"),
        required_tropes=("蒸汽机械", "工业革命阶层", "齿轮美学"),
        pacing_norm="medium",
        hook_density_baseline=2,
    ),
    "废土": GenreProfile(
        name="废土",
        anti_patterns=("废土与现代生活无差别", "辐射/变异规则随意"),
        required_tropes=("资源争夺", "聚居地政治", "变异生物"),
        pacing_norm="medium",
        hook_density_baseline=3,
    ),
    "同人": GenreProfile(
        name="同人",
        anti_patterns=("原作角色 OOC", "无视原作设定", "强行融入主角"),
        required_tropes=("原作世界观尊重", "原作角色刻画"),
        pacing_norm="medium",
        hook_density_baseline=2,
    ),
    "综漫": GenreProfile(
        name="综漫",
        anti_patterns=("跨作品角色突兀同框", "原作能力体系混乱"),
        required_tropes=("跨作品穿梭", "能力对照", "角色重逢"),
        pacing_norm="fast",
        hook_density_baseline=3,
    ),
    "网游": GenreProfile(
        name="网游",
        anti_patterns=("游戏与现实割裂", "公会成员脸谱化", "PK 描写干瘪"),
        required_tropes=("职业/技能体系", "公会/团队", "PK 战斗", "装备/经济系统"),
        pacing_norm="fast",
        hook_density_baseline=3,
    ),
    "电竞": GenreProfile(
        name="电竞",
        anti_patterns=("比赛场面流水账", "战术解说生硬", "队友智商不在线"),
        required_tropes=("战术对决", "团队磨合", "粉丝/对手互动", "训练日常"),
        pacing_norm="fast",
        hook_density_baseline=3,
    ),
    "娱乐圈": GenreProfile(
        name="娱乐圈",
        anti_patterns=("行业细节悬浮", "粉丝/黑粉脸谱化", "成名过于偶然"),
        required_tropes=("剧组/录音棚日常", "舆论风波", "圈内人脉"),
        pacing_norm="medium",
        hook_density_baseline=2,
    ),
    "竞技": GenreProfile(
        name="竞技",
        anti_patterns=("技术描写浮于表面", "对手降智", "夺冠靠主角光环"),
        required_tropes=("训练/复盘", "强敌对抗", "心态转折"),
        pacing_norm="medium",
        hook_density_baseline=2,
    ),
    "校园": GenreProfile(
        name="校园",
        anti_patterns=("现代校园用 80 年代设定", "老师/家长全程缺位"),
        required_tropes=("校园生活细节", "同学关系", "升学/考试压力"),
        pacing_norm="slow",
        hook_density_baseline=1,
        reading_pull_floor=50,
    ),
    "职场": GenreProfile(
        name="职场",
        anti_patterns=("商战靠点子,不靠细节", "职场术语堆砌", "上下级关系单一"),
        required_tropes=("项目/KPI", "办公室政治", "客户/合作博弈"),
        pacing_norm="medium",
        hook_density_baseline=2,
    ),
    "官场": GenreProfile(
        name="官场",
        anti_patterns=("官场用语不准确", "腐败描写过分露骨"),
        required_tropes=("权力博弈", "上下级关系", "政策落地细节"),
        pacing_norm="slow",
        hook_density_baseline=1,
    ),
    "商战": GenreProfile(
        name="商战",
        anti_patterns=("收购/上市流程错误", "对手反应单一"),
        required_tropes=("资本运作", "股东/董事会", "行业关系网"),
        pacing_norm="medium",
        hook_density_baseline=2,
    ),
    "民国": GenreProfile(
        name="民国",
        anti_patterns=("时代用词混乱(现代词出现在民国)", "上海/北平之外无地名"),
        required_tropes=("时代风貌(租界/军阀)", "新旧文化冲突", "服饰/食物细节"),
        pacing_norm="slow",
        hook_density_baseline=2,
    ),
    "谍战": GenreProfile(
        name="谍战",
        anti_patterns=("密码/电台描写不专业", "敌我双方智商失衡", "情报传递过于轻松"),
        required_tropes=("情报传递", "身份伪装", "信任危机", "组织内部斗争"),
        pacing_norm="medium",
        hook_density_baseline=3,
        reading_pull_floor=70,
    ),
    "盗墓": GenreProfile(
        name="盗墓",
        anti_patterns=("墓室结构随意瞎写", "机关靠玄学", "队友突然出问题"),
        required_tropes=("墓葬规制", "机关陷阱", "团队配合", "诡异遭遇"),
        pacing_norm="fast",
        hook_density_baseline=4,
        reading_pull_floor=70,
    ),
    "灵异": GenreProfile(
        name="灵异",
        anti_patterns=("解谜靠主角福至心灵", "灵异元素随意叠加"),
        required_tropes=("超自然事件", "民俗规则", "氛围渲染"),
        pacing_norm="medium",
        hook_density_baseline=3,
    ),
    "惊悚": GenreProfile(
        name="惊悚",
        anti_patterns=("惊悚靠突然 BGM", "受害者智商集体下线"),
        required_tropes=("不安铺垫", "正常被打破", "心理压迫"),
        pacing_norm="medium",
        hook_density_baseline=4,
        reading_pull_floor=75,
    ),
    "恐怖": GenreProfile(
        name="恐怖",
        anti_patterns=("血腥代替恐怖", "鬼怪规则随心所欲"),
        required_tropes=("未知/不可名状", "封闭场景", "幸存者团体"),
        pacing_norm="medium",
        hook_density_baseline=4,
        reading_pull_floor=75,
    ),
    "侦探": GenreProfile(
        name="侦探",
        anti_patterns=("证据呈现不公平", "凶手过于明显或过于隐藏"),
        required_tropes=("案件设置", "侦探-助手搭档", "推理链条公开"),
        pacing_norm="medium",
        hook_density_baseline=3,
        reading_pull_floor=70,
    ),
    "医学": GenreProfile(
        name="医学",
        anti_patterns=("术语硬伤(不符合医学常识)", "病人作为道具"),
        required_tropes=("病例/诊治", "医院政治", "医患关系"),
        pacing_norm="medium",
        hook_density_baseline=2,
    ),
    "法医": GenreProfile(
        name="法医",
        anti_patterns=("尸检过程草率", "证据链漏洞百出"),
        required_tropes=("尸检/痕迹分析", "现场重建", "凶手心理"),
        pacing_norm="medium",
        hook_density_baseline=3,
    ),
    "律政": GenreProfile(
        name="律政",
        anti_patterns=("法律程序错误", "庭审戏靠激情演讲"),
        required_tropes=("案件/证据", "庭审对抗", "事务所人际"),
        pacing_norm="medium",
        hook_density_baseline=2,
    ),
}

# 别名映射(用户填写的 genre 可能是变体)
_ALIASES: dict[str, str] = {
    "玄幻奇幻": "玄幻",
    "奇幻": "玄幻",
    "玄幻仙侠": "仙侠",
    "都市言情": "都市",
    "现代言情": "言情",
    "现代都市": "都市",
    "历史架空": "历史",
    "古代": "历史",
    "悬疑推理": "悬疑",
    "推理": "悬疑",
    "灾难末日": "末世",
    "末日": "末世",
    "科幻未来": "科幻",
    "丧尸": "末日丧尸",
    "末日求生": "末日丧尸",
    "无限恐怖": "无限恐怖",
    "无限恐惧": "无限恐怖",
    "无限世界": "无限流",
    "网游小说": "网游",
    "虚拟现实": "网游",
    "电子竞技": "电竞",
    "明星": "娱乐圈",
    "演艺": "娱乐圈",
    "体育": "竞技",
    "高校": "校园",
    "大学": "校园",
    "白领": "职场",
    "公务员": "官场",
    "金融": "商战",
    "民国旧事": "民国",
    "特工": "谍战",
    "间谍": "谍战",
    "鬼怪": "灵异",
    "侦探推理": "侦探",
    "悬念推理": "侦探",
    "医生": "医学",
    "急诊": "医学",
    "尸体": "法医",
    "律师": "律政",
    "法庭": "律政",
    "重生改命": "重生",
    "重活": "重生",
    "穿越时空": "穿越",
    "时空穿越": "穿越",
    "系统": "系统流",
    "金手指": "系统流",
    "同人衍生": "同人",
    "综合同人": "综漫",
    "无限": "无限流",
}


def get_profile(genre: str) -> Optional[GenreProfile]:
    """根据 genre 字符串返回 Profile,找不到返回 None(调用方按 None 处理)"""
    if not genre:
        return None
    g = genre.strip()
    if g in _PROFILES:
        return _PROFILES[g]
    if g in _ALIASES:
        return _PROFILES.get(_ALIASES[g])
    # 子串匹配兜底
    for key in _PROFILES:
        if key in g:
            return _PROFILES[key]
    return None


def list_supported_genres() -> list[str]:
    return sorted(_PROFILES.keys())


def profile_to_prompt_block(profile: Optional[GenreProfile]) -> str:
    """把 profile 渲染成可注入审稿/生成 prompt 的文本"""
    if not profile:
        return ""
    sections = [f"【🎭 {profile.name}类型档案】"]
    if profile.anti_patterns:
        sections.append("\n## 类型反模式(应避免)")
        sections.extend(f"❌ {p}" for p in profile.anti_patterns)
    if profile.required_tropes:
        sections.append("\n## 类型必备元素")
        sections.extend(f"✅ {t}" for t in profile.required_tropes)
    sections.append(f"\n## 节奏基线: {profile.pacing_norm}")
    sections.append(f"## 钩子密度基线: 每千字 {profile.hook_density_baseline} 个钩子")
    return "\n".join(sections)
