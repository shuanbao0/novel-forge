# novel-forge

基于 AI 的中文长篇小说生成系统。后端 FastAPI + SQLAlchemy(async) + ChromaDB,前端 React + Vite + Ant Design。
核心能力是把"用户给的一句简介"沿着 **项目 → 世界观 → 角色 → 契约 → 大纲节点 → 章节蓝图 → 章节正文** 这条链路逐步具体化,中间所有结构都允许人工与 AI 协同修改。

## 顶层布局

```
backend/                      FastAPI 主体
  app/
    api/        路由层(按资源拆文件),所有路由挂在 /api 前缀下
    services/   业务逻辑、AI 调用、prompt 装配、后处理管线
    models/     SQLAlchemy ORM 表
    schemas/    Pydantic 入参/出参
    repositories/ 部分聚合查询(motif/style 等)
    middleware/ 认证、请求 ID
    infra/      Redis / ChromaDB 等基础设施客户端
    mcp/        MCP 插件协议接入
    main.py     应用入口与 lifespan
  alembic/      数据库迁移(postgres/sqlite 两套并列)
  data/         ChromaDB 持久化与本地缓存
frontend/                     React + Vite 单页
  src/
    pages/      每个一级路由对应一个 .tsx
    services/   API 客户端
    store/      Zustand 全局状态
docker-compose.yml + Dockerfile  一键部署
```

## 技术栈与关键依赖

- Python 3.11、FastAPI、SQLAlchemy 2.x(async)
- PostgreSQL(生产)/ SQLite(开发) — Alembic 两套迁移并行维护
- ChromaDB + sentence-transformers (`paraphrase-multilingual-MiniLM-L12-v2`) 做向量记忆
- AI Provider 抽象在 `services/ai_clients/` + `ai_providers/`,统一走 `AIService.generate_text` / `generate_text_stream`
- 前端 React 18 + Zustand + AntD,SSE 流式接 wizard / 章节生成

## 数据库主表(只列与生成链路相关的)

| 表 | 关键字段 | 用途 |
|---|---|---|
| `projects` | title/genre/theme/world_*/narrative_perspective/`creative_contract`(JSON)/`generation_settings`(JSON)/`style_patterns`(JSON) | 全局根 |
| `characters` | name/role_type/personality/.. | 角色/组织 |
| `outlines` | title/content/`structure`(JSON)/`creative_brief`(JSON,VolumeBrief) | 大纲节点(一个项目多个节点) |
| `chapters` | chapter_number/title/content/`expansion_plan`(JSON,**冻结蓝图**)/`creative_brief`(JSON,ChapterBrief) | 单章 |
| `plot_analysis` | hooks/foreshadows/`plot_points`(含 scene_skeleton)/`character_states`(含 fact_deltas)/`scenes`/pacing/score_* | 章节落库后的结构化分析,反哺下一章 |
| `story_memories` | type/content/related_characters/related_locations/`importance_score`/`vector_id` | 向量记忆条目;ChromaDB 与 SQL 双写;`memory_type='fact_ledger'` 复用本表存项目级事实台账(单 project 单行) |
| `foreshadows` | content/status/strength/.. | 伏笔台账 |
| `chapter_commits` | hash/diff | 章节快照,失败回滚用 |

## 完整执行流程(7 个阶段)

下面的链路是这本书从"创建项目"到"产出章节正文"的完整路径。每一阶段的入口、模板、落库字段、关键调用都标了文件:行。

### 阶段 1 — 创建项目
- 入口:`POST /api/projects` → `api/projects.py:45`
- 入参:`ProjectCreate`(title/theme/genre/target_words/narrative_perspective 等)
- 落库:`projects` 行,`wizard_status='incomplete'`、`wizard_step=0`

### 阶段 2 — 生成世界观(向导)
- 入口:`POST /api/wizard-stream/world-building` → `api/wizard_stream.py:300`
- 模板:`PromptService.WORLD_BUILDING`(`services/prompt_service.py`)
- LLM 输出 `{time_period, location, atmosphere, rules}` 流式写回 `projects.world_*` 字段
- 失败重试上限 `MAX_WORLD_RETRIES = 3`,JSON 解析用 `_clean_json_response`

### 阶段 3 — 生成角色与职业体系
- 入口:`POST /api/wizard-stream/characters`(`wizard_stream.py:1237`)、`/career-system`、`/relationships`
- 模板:`PromptService.CHARACTER_*` / `CAREER_*`
- 落库:`characters` 多行;组织(`is_organization=True`)与角色同表

### 阶段 4 — 起草项目级 / 卷级契约(可选,推荐)
- 入口:`PUT /api/creative-contracts/{project_id}`(`api/creative_contracts.py`)、`POST /api/outlines/{oid}/suggest-brief-stream`(`outlines.py:2954`)
- 数据结构:`services/creative_contract.py`
  - `CreativeContract`(项目级):style_baseline、forbidden_zones、anti_patterns、required_tropes、narrative_promises
  - `VolumeBrief`(卷级):volume_goal、pacing、`pacing_milestones`(里程碑数组)
  - `ChapterBrief`(章级):directive、forbidden_zones、must_check_nodes
- 优先级 章 > 卷 > 项目;每一层都有 `is_empty()` 与 `to_prompt_block()`,空块自动跳过

### 阶段 5 — 生成大纲节点
- 入口:`POST /api/wizard-stream/outline`(`wizard_stream.py:1663` → `outline_generator()` 行 1255)
- 模板:`OUTLINE_CREATE`(`prompt_service.py:323`)— 默认产 3 个节点,只产高度抽象的题纲不展开章节
- 落库:`outlines` 多行,`structure` 字段存场景/key_points/emotion/goal 的结构化 JSON

### 阶段 6 — 大纲节点展开为章节蓝图 ⚠️ **冻结蓝图阶段**
- 入口:
  - 单节点:`POST /api/outlines/{oid}/expand-stream`(`outlines.py:2862`)
  - 批量:`POST /api/outlines/batch-expand-stream`(`outlines.py:3480`)
- 服务:`PlotExpansionService.analyze_outline_for_chapters`(`plot_expansion_service.py:112`)
  - ≤ batch_size:`_generate_chapters_single_batch` 使用 `OUTLINE_EXPAND_SINGLE`(`prompt_service.py:1446`)
  - > batch_size:`_generate_chapters_in_batches` 使用 `OUTLINE_EXPAND_MULTI`(`prompt_service.py:1576`),跨 batch 传 previous_context 字符串
- LLM 产出每章:
  ```json
  {"sub_index","title","plot_summary","key_events",
   "character_focus","character_beats","emotional_tone",
   "narrative_goal","conflict_type","estimated_words",
   "story_time_anchor","story_time_advance",
   "scenes"?, "subplot_progression"?}
  ```
- 落库:`PlotExpansionService.create_chapters_from_plans`(行 484)把整个 JSON 写到 `chapters.expansion_plan`(Text),`chapter_number` 由 `start_chapter_number + idx` 自动算

> **本阶段产出的 `expansion_plan` 是整本书后续章节生成所遵循的"冻结蓝图"。阶段 7 只是按蓝图复述。**

### 阶段 7 — 章节正文生成(主循环)

#### 7a. 入口与编排
- 批量:`POST /api/chapters/project/{pid}/batch-generate` → `batch_generate_chapters_in_order`(`chapters.py:2920`)→ `execute_batch_generation_in_order`(行 3143)→ 循环 `generate_single_chapter_for_batch`(行 3378)
- 单章流式:`POST /api/chapters/{cid}/generate-stream`(`chapters.py:1507`)
- 后台任务:`/generate-background`(`chapters.py:1917`)— 走 `BackgroundTaskService`
- 重新生成:`/regenerate-stream`、`/partial-regenerate-stream`、`/reset-for-rewrite`

#### 7b. 上下文构建(策略模式)
- `OneToManyContextBuilder.build`(`chapter_context_service.py:197`)— 默认模式
- `OneToOneContextBuilder.build`(行 1046)— 旧的一对一模式
- 产出 `OneToManyContext`,字段:
  - `chapter_outline` ← 本章 `expansion_plan` 渲染
  - `recent_chapters_context` ← 最近 10 章 `expansion_plan` 摘要(行 252)
  - `continuation_point` ← 上一章末尾 500 字(`_tail_on_boundary`,行 793)
  - `previous_chapter_summary` ← `StoryMemory.chapter_summary` 截 300 字(行 806)
  - `previous_chapter_events` ← `expansion_plan.key_events[:5]`(行 822)
  - `chapter_characters` / `chapter_careers` ← 完整角色+职业信息
  - `relevant_memories` ← ChromaDB 语义检索 top10、相关度 ≥ 0.6
  - `foreshadow_reminders` ← 待回收伏笔提醒

#### 7c. Prompt 装配(管线 + 装饰器模式)
- 入口:`assemble_chapter_prompt`(`chapter_prompt_builder.py:495`)
- 基础 prompt:`build_base_chapter_prompt`(行 55)— 拼模板 + 上下文
- 装饰器管线:`build_decorated_chapter_pipeline`(行 421)→ `PromptPipeline.for_chapter_generation`(`prompt_decorators.py`)
- 装饰器执行顺序(16 个,粒度由低到高):
  1. WritingStyle 2. StylePattern 3. CreativeContract 4. VolumeBrief 5. ChapterBrief
  6. MemoryScratchpad 7. **FactConsistency**(项目级事实台账) 8. CharacterArc 9. NarratorVoice
  10. MotifCooling 11. LocationVariety 12. **PlotBeatCooling**(场景骨架去重)
  13. StoryTimeline 14. PacingMilestone
  15. AntiAIFlavor 16. OutputFormat
- 每个装饰器实现 `_is_active()` + `apply(ctx)`,空数据自动跳过

#### 7d. AI 调用与硬截断
- 调 `AIService.generate_text_stream`(`ai_service.py:466`)
- 字数防线(详见 `chapters.py:1740-1748`、`3419`):
  - `target_word_count` 优先取本章 `expansion_plan.estimated_words`,batch 兜底
  - `max_tokens = target_word_count * 1.0`(收紧到 1.0,见 commit `8cb97f7`)
  - 字符层硬截断 `hard_cap = target_word_count * 1.3`,句末标点处主动断流
- 流式 chunk 累积到 `full_content`,落库 `chapters.content` + `ChapterHistory`

#### 7e. 后处理管线(命令模式 / Hook 模式)
- 入口:`PostGenPipeline.for_batch(enable_analysis=True).execute(ctx)`(`post_generation_pipeline.py`)
- Hook 顺序:
  1. `AutoPlantForeshadowHook` — 把 pending 伏笔标记为 planted
  2. `CreateChapterCommitHook` — 写章节快照
  3. `TitleRegenerationHook` — bigram Jaccard + 前后缀双层校验,撞车则重生
  4. `MotifExtractionHook` — 抽 3-5 个意象写入 `MotifRepository`
  5. `CreateAnalysisTaskHook` — 创建 `analysis_tasks` 行
  6. `SyncAnalyzeHook` — **同步**跑 `PlotAnalyzer`(批量场景),失败抛错中断整批
  7. `ChapterReviewHook` — 异步审稿
- 单章 SSE 走 `default()`,区别是 `ScheduleAnalysisHook` 后台跑
- 事实台账投影由 `services/fact_ledger_projection.project_fact_state` 统一在 `analyze_chapter_background` 内部完成,SSE/批量两条路径都覆盖,无需独立 Hook

#### 7f. PlotAnalyzer:章节落库后写回反馈数据
- `services/plot_analyzer.py` 调 `PLOT_ANALYSIS` 模板(`prompt_service.py:1041`)
- 写入 `plot_analysis` 行:
  - `plot_points`(供下章 PlotBeatCoolingDecorator 读)
  - `scenes`(供 LocationVarietyDecorator 读)
  - `character_states`(供 CharacterArcDecorator 读 + `character_state_update_service` 同步)
  - `foreshadows`(供伏笔台账)
- 同时把 importance ≥ 0.6 的情节点写进 `story_memories`(行 586),ChromaDB 写入向量

## 重要的循环依赖一定要看懂

```
阶段 6 (LLM 写 expansion_plan)
   └─→ 阶段 7b 读 expansion_plan 作为本章大纲
        └─→ 阶段 7c 装饰器把上几章的 PlotAnalysis 反馈进来
             └─→ 阶段 7d LLM 写正文
                  └─→ 阶段 7f PlotAnalyzer 又把正文分析成 plot_points/scenes/character_states
                       └─→ 下一章 7c 再读
```

也就是说,**阶段 6 是一次性"冻结"的、不再被反馈环路修正的;阶段 7 是闭环的**。这是已知质量问题(场景反复、情节零推进、事实漂移)的结构性根因。详见 `docs/` 下的实测样本与分析。

## 常用开发命令

```bash
# 后端开发
cd backend && python -m uvicorn app.main:app --host localhost --port 8000 --reload

# 前端开发
cd frontend && npm run dev

# 数据库迁移(选其一)
alembic -c backend/alembic-postgres.ini upgrade head
alembic -c backend/alembic-sqlite.ini   upgrade head

# Docker 一键启动
docker-compose up -d
```

## 代码风格与约定

- 中文优先:所有面向用户的字符串、表 `comment`、提示词模板全部中文;变量名/类型/日志结构化键名英文
- 单例 + 全局实例:大型服务(`memory_service`、`foreshadow_service`、`prompt_service`)文件末尾导出小写实例
- 装饰器/Hook 都实现 `_is_active()` 或 `if not data: return`;空数据自动跳过,工厂层无感
- 兼容旧数据:新增的 JSON 字段必须 `obj.get("k") or default`,不依赖 alembic 立即跑过
- 日志用结构化前缀 emoji:`📝 / ✅ / ⚠️ / 🔧 / 📊` 区分阶段;不要新增更多种类
- 不引入新框架解决已有抽象能解决的问题;能加 Decorator 解决就不要新建 service

## 已知问题与修复方向

1. **章节复读 / 情节零推进 / 事实漂移** — 已通过三处闭环修复(见下),不再是已知问题。
2. **批量分析串行 LLM 调用** — `SyncAnalyzeHook` 让批量生成的瓶颈从生成迁到了分析。

## 三大质量问题的修复(2026-05-15)

针对样本《重回 2008》暴露的"10 章 = 1 节晚自习/苏晚晴抬眼复读 7 次/数学 48 锚定但英语 53→70 漂移"三类失败模式,落地了三处正交修复:

### Fix 1 — 蓝图验证关 (Strategy + Chain of Responsibility)
- `services/blueprint_validator.py` — 新增 `BlueprintValidator` 与三条规则:
  - `SceneVarietyRule` — N 章主场景至少 ⌈N/3⌉ 个唯一值
  - `TimeAdvanceRule` — `story_time_advance` 含"紧接/同一"类章数 ≤ 2/3
  - `KeyEventSkeletonRule` — 跨章 key_events Jaccard 高重复 ≤ N/2
- `services/plot_expansion_service.py` — `_generate_and_validate()` 包装 LLM 调用,失败时把违规清单注入 prompt 重试,上限 `MAX_BLUEPRINT_RETRIES = 2`,最终仍失败时打 warning 放行(不阻塞用户主流程)
- `services/prompt_service.py` — `OUTLINE_EXPAND_MULTI` / `OUTLINE_EXPAND_SINGLE` constraints 段删除"放慢节奏不要快速推进",换成与验证关同步的"推进硬约束"显式说明

### Fix 2 — 场景骨架去重 (Value Object + Decorator 扩展 + 同义词归一化)
- `services/prompt_service.py` — `PLOT_ANALYSIS` 模板要求 LLM 在每个 `plot_points[i]` 内嵌 `scene_skeleton`(location/action_kind/role_pair_key/emotion_beat,后两者为枚举);<constraints> 段把 `scene_skeleton` 标为必填
- `services/scene_skeleton_normalize.py` — 把"训诫/质问/施压"等近义词映射到规范枚举值;role_pair_key 字典序归一化让"a↔b"与"b↔a"等价
- `services/prompt_decorators.py` — `PlotBeatCoolingDecorator` 重写为骨架元组比对,新增 `_compute_hot()` 检测超用维度并强制 LLM 切换
- `services/chapter_prompt_builder.py` — `_build_plot_beat_cooling_decorator` 改读 plot_points[i].scene_skeleton 并先经归一化;旧数据缺字段时整个装饰器跳过,与历史项目兼容

### Fix 3 — 事实台账 (Repository + 统一投影服务 + Decorator)
- `services/fact_ledger.py` — `FactLedger` / `FactDeltas` / `CharacterFacts` 三类 Value Object,merge 默认"已有不覆盖",显式 `force_overwrite=true` 才能改写
- `repositories/fact_ledger_repo.py` — 复用 `StoryMemory.memory_type='fact_ledger'`,每 project 单行,零 alembic 迁移
- `services/prompt_service.py` — `PLOT_ANALYSIS.character_states[i]` 新增 `fact_deltas` 字段(scores/inventory/identities/relationships/force_overwrite);<constraints> 段把 `fact_deltas` 标为"涉及变更则必填"
- `services/fact_ledger_projection.py` — `project_fact_state()` 统一投影函数
- `api/chapters.py:analyze_chapter_background` — 在分析任务内部调用投影函数,**SSE/批量两条路径都覆盖**,**不另起 LLM 调用**
- `services/prompt_decorators.py` — 新增 `FactConsistencyDecorator`,插在第 7 位(MemoryScratchpad 之后,CharacterArc 之前)
- `services/chapter_prompt_builder.py` — `_build_fact_consistency_decorator` 从台账仓库加载并注入

### 配套加固(同期落地)
- **枚举同义词归一化** — `services/scene_skeleton_normalize.py` 把 LLM 输出的"训诫/质问/憋屈/挫败"等近义词映射回 7+6 个规范枚举,让 cooling 装饰器跨同义词正确累计计数
- **SSE 路径事实台账延迟** — 用 `services/fact_ledger_projection.py` 统一在 `analyze_chapter_background` 内部投影,SSE 单章生成路径下台账也能正确更新(原方案下 Hook 读 DB 会读不到刚写的行,数据延迟 1 章)
- **自定义模板兼容性警告** — `PromptService.get_template` 加 `_warn_outdated_custom_template`,用户自定义模板若缺 `scene_skeleton`/`fact_deltas` 等质量修复字段,首次使用时打 warning 提示重新克隆系统模板
- **fact_deltas 必填强化** — 标记从"可选, 但强烈推荐"改为"必填(如本章涉及任一变更)",并在 PLOT_ANALYSIS 的 <constraints> 段加显式硬约束

### 流程一致性二次审查后的修复(2026-05-15 第二轮)
首轮 Fix 落地后再次审查"建项目 → 生成章节"完整流程,发现 5 个执行流程层 bug,全部已修:
- **P1 (严重) — OUTLINE_EXPAND 模板未要求输出 scenes 字段**
  - `scene_field=""` 和 `scene_instruction=""` 让 LLM 不输出 scenes,SceneVarietyRule 永远拿到空 → 100% 触发兜底错误 → 重试无效 → 最后放行 = Fix 1 实际不工作
  - 修复:`plot_expansion_service.py` 定义 `_DEFAULT_SCENE_INSTRUCTION` / `_DEFAULT_SCENE_FIELD` 常量,4 处调用都改为传入默认值;同时给 `OUTLINE_EXPAND_*` 模板的 `<constraints>` 段加 `{scene_instruction}` 占位符
- **P2 (严重) — FactLedger 可能被 reset 误删**
  - `_reset_chapter_for_rewrite` 用 `delete(StoryMemory).where(chapter_id==X)` 一锅端清理,fact_ledger 行的 chapter_id 是"最近合并的章节 id",重置该章会抹掉整个项目的台账;chapter DELETE 也会因 FK CASCADE 把台账冲掉
  - 修复:`FactLedgerRepository.save()` 强制 `chapter_id=None`(台账本就是项目级);`_reset_chapter_for_rewrite` 增加 `_PROJECT_SCOPED_MEMORY_TYPES` 排除(`fact_ledger` / `used_motif`)
- **P3 (中) — 章节生成不渲染 expansion_plan.scenes**
  - 蓝图阶段填了场景但生成正文时 LLM 看不到 → 容易回退到上章场景
  - 修复:`_build_chapter_outline_1n` 新增 `_render_scenes_block()`,渲染主场景/氛围/时长到本章 prompt
- **P4 (中) — OUTLINE_CREATE 仍含反推进话术**
  - "开篇不宜过快/节奏控制/留白艺术/节奏过快"等让初始 3 个大纲节点容易塞进同场景
  - 修复:删除反推进短语,新增"场景与时间硬约束"段(主场景多样性 ≥ ⌈N/2⌉)
- **P5 (中) — 跨大纲节点不验证**
  - 单 outline 内部 SceneVarietyRule 通过,但多 outline 合起来全是同场景,验证关捕捉不到
  - 修复:新增 `validate_project_blueprint()` 函数,在 `batch_expand_outlines` 末尾跑跨 outline 检查,发现项目级场景塌缩时打 warning 写入返回结构
- **P6 (中) — OUTLINE_CREATE 新加的 scenes[0].location 约束与 schema 不一致**
  - 这是首轮加固自身引入的:OUTLINE_CREATE 阶段的 scenes 是字符串数组,不是对象数组,引用 .location 是错的
  - 修复:把约束改为 "主场景描述首关键词" 这种 schema-agnostic 表述,不引用具体 JSON path
- **P7 (中) — OUTLINE_EXPAND_SINGLE 缺 story_time 字段**
  - SINGLE 模板 JSON schema 不输出 story_time_anchor / story_time_advance,导致 SINGLE 模式下 StoryTimelineDecorator 永远拿到空,TimeAdvanceRule 永远不触发
  - 修复:把 MULTI 里的两个字段及其格式规范补齐到 SINGLE,保证两条路径产出的 expansion_plan 字段一致

### 部署与回归
- 全部零 alembic 迁移(全部落到现有 JSON 列 / 复用 `StoryMemory` 类型化扩展)
- 通过 `python -m py_compile` + 端到端 smoke test(首轮 11 + 加固 7 + 二次审查 5 = 23 断言全过)
- 回归测试基线:`memory/project_test_novel_baseline.md` 描述的复跑流程
