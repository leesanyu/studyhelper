# Sprint 1: AI 编排层搭建

## 目标

本地部署 Dify，配置大模型凭证，构建并跑通"图片识别 → 知识点提取 → 苏格拉底解答"完整 Chatflow，用真实题目图片验证输出质量。

## 范围

对应产品待办 **Epic 1** 的全部 Story（1.1 - 1.7）。

## 验收标准

1. Dify 管理后台可在本地浏览器正常访问
2. 至少配置 1 个多模态模型 + 1 个文本推理模型，且均可在 Dify 调试面板中正常调用
3. 完整 Chatflow 可用：上传一张数学题图片 → 返回题干文本 + 学科分类 + 知识点标签 + 苏格拉底式引导解答
4. 输出格式符合规范：正文 Markdown + LaTeX 公式；学科、知识点等结构化信息由解析节点和会话变量承载，前端尾部 JSON 解析转入后续联调
5. 使用真实题图验证关键链路；跨学科题库验证沉淀为后续回归测试池

## Sprint 结论

Sprint 1 已完成 AI 编排层的核心闭环：Dify 本地环境可用，模型凭证可用，图片上传、题目识别、知识点提取、多轮引导、直接解答和新题切换均已跑通。

几何题上下文链路已按最终架构收口：题图只进入「题目识别」节点，识别结果写入 `current_question/current_diagram/current_knowledge`，下游「直接解答」和「引导式解答」节点只消费纯文本上下文，Vision 关闭。

Python 绘图执行不纳入 Dify 内部编排验收。Dify 只负责生成 `python:figure` 代码和传递绘图意图，真正执行 matplotlib、生成图片、存储并返回 URL 的能力转入后端沙箱（Epic 2.6）和前端展示（Epic 4.4）。

## 任务分解

### 任务 1: 本地部署 Dify

- [x] 确认本地 Docker 环境可用（Docker 24+、Docker Compose）
- [x] 克隆 Dify 开源版仓库，使用 docker-compose 启动
- [x] 验证管理后台 `http://localhost` 可访问，完成初始化设置
- **交付物**：Dify 管理后台可正常访问和操作
- **工作量**：0.5 天

### 任务 2: 配置大模型凭证

- [x] 注册/准备至少一个多模态模型 API Key（推荐：阿里百炼 Qwen-VL-Max 或 OpenAI GPT-4o）
- [x] 注册/准备至少一个文本推理模型 API Key（推荐：DeepSeek 或 Qwen-Max）
- [x] 在 Dify「设置 → 模型供应商」中配置上述模型凭证
- [x] 在 Dify 调试面板中分别测试各模型是否可正常调用
- **交付物**：Dify 中至少 2 个模型可正常使用
- **工作量**：0.5 天

### 任务 3: 构建"题目识别"工作流节点

- [x] 在 Dify 中创建新的 Chatflow
- [x] 添加「LLM 节点 A」：接收图片输入，输出题干文本 + 学科分类
- [x] 编写 System Prompt，要求模型：
  - 准确识别题目中的文字和数学公式
  - 输出 LaTeX 格式的数学公式（块级用 `$$...$$`，行内用 `\(...\)`）
  - 判定学科分类（如：初中数学、高中物理）
- [x] 用 2-3 张题目图片调试，验证识别准确度
- **交付物**：节点 A 可正确识别题目图片并输出结构化文本
- **工作量**：1 天

### 任务 4: 构建"知识点提取"工作流节点

- [x] 添加「LLM 节点 B」：基于节点 A 输出的题干，提取二级知识点标签
- [x] 编写 System Prompt，要求模型：
  - 输出该题目的二级知识点（如：初中数学-勾股定理、高中物理-牛顿第二定律）
  - 输出格式为 JSON：`{"subject": "初中数学", "knowledge_points": ["勾股定理", "直角三角形"]}`
- [x] 调试验证知识点提取的准确性
- **交付物**：节点 B 可准确提取知识点标签
- **工作量**：0.5 天

### 任务 5: 构建"苏格拉底解答"工作流节点

- [x] 添加「LLM 节点 C」：基于题干和知识点，输出苏格拉底式引导解答
- [x] 编写 System Prompt，核心约束：
  - **严格不直接给出最终答案**
  - 支持三种 mode：step（逐步引导）、framework（分步框架）、cot_visible（展示思维链）
  - CoT 结构化内部推理：思路→关键步骤→易错点→自检（是否泄露答案）
  - 使用 Markdown + LaTeX 格式
- [x] 编写几何图形生成 Prompt：
  - 模型自行判断是否需要画图
  - 需要画图时输出 `python:figure` 标记包裹的 matplotlib 代码
  - 样式约定：已知边黑色实线、辅助线红色虚线、已知条件蓝色、求解目标绿色
- [x] 调试验证解答风格是否符合苏格拉底式引导
- [x] 用几何题验证图形代码生成质量
- **交付物**：节点 C 以苏格拉底式风格引导解题，几何题可输出绘图代码
- **工作量**：1.5 天

### 任务 6: 串联完整 Chatflow 并规范输出格式

- [x] 串联节点 A → B → C，形成完整工作流
- [x] 约束最终输出格式：
  ```
  [苏格拉底式引导解答正文，Markdown + LaTeX]

  <!-- 以下为结构化标签，前端解析用 -->
  ```json
  {
    "subject": "初中数学",
    "knowledge_points": ["勾股定理"],
    "difficulty": "中等"
  }
  ```
  ```
- [x] 处理边界情况：纯文字题目（无图片）、多题合一图片、非学科图片
- [x] 明确 Sprint 1 范围内结构化标签主要由知识点解析节点和会话变量承载，前端尾部 JSON 的稳定渲染/解析归入后续前端联调
- **交付物**：完整 Chatflow 可端到端运行，输出格式规范
- **工作量**：0.5 天

### 任务 6.2: 启用图片上传能力

- [x] 开启 features.file_upload（`enabled = true`, `image.enabled = true`）
- [x] 题目识别节点开启 vision（`vision.enabled = true`, `variable_selector` 指向 `sys.files`）
- [x] 通过 Service API (`/v1/chat-messages` + `files` 参数) 验证图片上传识别
- [x] 验证结果：上传包含 `x² - 5x + 6 = 0` 的图片 → 模型正确识别为"初中数学-解一元二次方程"
- **交付物**：图片上传识别功能正常工作
- **工作量**：0.5 天

### 任务 6.3: 修复数学公式渲染

- [x] 修改 `.env`：`NEXT_PUBLIC_ENABLE_SINGLE_DOLLAR_LATEX=false` → `true`
- [x] 在 `docker-compose.yaml` web 服务中添加 `NEXT_PUBLIC_ENABLE_SINGLE_DOLLAR_LATEX` 环境变量传递
- [x] 重新创建 API + web 容器使环境变量生效
- [x] 更新所有 Prompt 文档：行内公式用 `$...$`，独立公式块用 `$$...$$`（原为统一 `$$...$$`）
- [x] 通过 Dify Console API 更新 Chatflow 中 4 个 LLM 节点的 Prompt
- [x] 发布新版本 Chatflow
- [x] 验证：前端 HTML body 已注入 `data-enable-single-dollar-latex="true"`，AI 回复使用行内 `$...$` 格式
- **根因**：Dify 默认只支持块级 `$$...$$` 渲染，行内 `$...$` 需要启用 feature flag；原 Prompt 统一使用 `$$` 导致行内公式显示为原始文本
- **交付物**：行内和块级数学公式均可在 Dify UI 中正确渲染
- **工作量**：0.5 天

### 任务 6.1: 实现多轮对话分支（上下文状态 + Question Classifier + Memory）

- [x] 添加会话变量：
  - `context_ready`（string, 默认 `"false"`）：标记当前会话是否已有可复用题目上下文
  - `topic_resolved`（string, 默认 `"false"`）：记录是否已给出直接答案
  - `dialogue_started`（string, 默认 `"false"`）：兼容旧流程状态
  - `current_question/current_knowledge/raw_question_info/raw_knowledge_info`：保存题目与知识点上下文
- [x] 在 Start 节点后添加 IF/ELSE 节点，条件：
  - `conversation.context_ready != "true"`：构建题目上下文
  - 否则：进入多轮意图分类
  > 注：原计划使用 `sys.dialogue_count`，但 draft run 时该值始终为 1；后续改为显式 `context_ready` 状态。
- [x] IF 分支（缺少题目上下文）：题目识别 → 解析题目 → 知识点提取 → 解析知识点 → VariableAssigner(写入 `current_question/current_knowledge`，设置 `context_ready=true`) → 解答方式分类
- [x] 新增"解答方式分类"节点（上下文已构建后执行）：
  - "引导式解答"：默认路径，进入引导式解答（首轮）
  - "直接给答案"：用户明确要求最终答案/完整过程时，进入直接解答
- [x] ELSE 分支（已有题目上下文）：进入"意图分类"节点
- [x] 意图分类配置 3 个分类：
  - "继续引导"：用户在回答引导问题或请求继续讲解
  - "直接给答案"：用户明确要求给出最终答案
  - "新题目"：用户提出一道全新题目
- [x] "继续引导" 分支：连接到引导式解答（继续），Memory 开启，节点 prompt 显式注入 `current_question/current_diagram/current_knowledge`，最新用户回复由 Memory query 追加；解题节点使用 `qwen3.6-plus` 纯文本模式，Vision 关闭
- [x] "直接给答案" 分支：连接到"直接解答"节点，Memory 关闭，使用 `current_question/current_diagram/current_knowledge + sys.query`，并使用 `qwen3.6-plus` 纯文本模式，Vision 关闭
- [x] "新题目" 分支：重新进入题目识别链路，覆盖当前上下文后再进入解答方式分类
- [x] 引导式解答拆分为两个节点：
  - 首轮版：Memory 关闭，使用 `current_question/current_diagram/current_knowledge`，Vision 关闭
  - 继续版：Memory 开启，同时显式注入 `current_question/current_diagram/current_knowledge`，Vision 关闭
  > 注：拆分是因为 Dify LLM 节点的变量引用在变量不存在时会报错，首轮和非首轮的输入变量不同。
- [x] 直接解答后仅标记 `topic_resolved=true`，不清空 `current_question/current_knowledge`，支持用户继续追问"为什么这一步成立"
- [x] 引导式解答和直接解答的输出通过 VariableAggregator 合并，统一接入 Answer 节点
- [x] 验证场景（全部通过）：
  1. ✅ 普通首轮：识别题目 → 写入上下文 → 解答方式分类 → 引导式解答（首轮）
  2. ✅ 同会话直接给答案：复用上下文 → 意图分类 → 直接解答，不重新识别题目
  3. ✅ 首轮直接给答案：识别题目 → 写入上下文 → 解答方式分类 → 直接解答
  4. ✅ 直接解答后追问：保留上下文 → 意图分类 → 引导式解答（继续），不重新识别题目
- [x] 发布新版本 Chatflow：`2026-05-08 15:01:29.278282`（标记：上下文修复）
- [x] 发布图形文本版本：题目识别节点输出 `diagram_description`，`code_parse_question` 解析并写入 `conversation.current_diagram`
- [x] 发布纯文本 Qwen 解题版本：引导式解答和直接解答节点切换为 `qwen3.6-plus`，Vision 关闭，只消费 `current_question/current_diagram/current_knowledge`
- [x] 发布直接解答禁草稿版本：`direct_answer` temperature=0.1，禁止草稿式推理和草稿短语，端到端验证几何题最终关系为 $\angle DBE=90^\circ+\frac12\angle C$
- [x] 发布识别解析容错版本：`code_parse_question` 修复 LaTeX 反斜杠导致的 JSON 解析失败，验证 `has_figure=true` 且 `diagram_description` 非空
- **交付物**：多轮苏格拉底式引导对话 + 直接解答上下文复用 + 新题目上下文重建
- **工作量**：1 天

### 任务 7: 真实题目验证

- [x] 使用现有真实题图 `tests/questions/几何-角度-线段.jpg` 做关键路径端到端验证
- [x] 验证题图只进入「题目识别」节点：识别节点 prompt `file_count=2`，直接解答节点 prompt `file_count=0`
- [x] 验证 `code_parse_question` 输出 `has_figure=true` 且 `diagram_description` 非空
- [x] 验证直接解答最终数量关系为 $\angle DBE=90^\circ+\frac{1}{2}\angle C$
- [x] 记录 Python 绘图能力边界：Dify 内部不执行 matplotlib；绘图执行、图片存储和 URL 返回转入后端沙箱与前端展示 Story
- [x] 记录残留风险：直接解答在复杂几何证明中仍可能输出偏长推导，需后续通过验证集继续约束表达质量
- **交付物**：Sprint Review 验证记录 + 最终版 Chatflow
- **工作量**：0.5 天

## 风险与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| Docker 本地资源不足，Dify 启动慢或卡顿 | 中 | 中 | 确保 8G+ 内存，关闭其他占内存的容器 |
| 大模型 API Key 申请审核慢 | 中 | 高 | 提前注册多个平台，优先选用即时开通的（如阿里百炼） |
| 苏格拉底式 Prompt 难以约束，模型仍倾向直接给答案 | 高 | 中 | 迭代 Prompt 加 few-shot 示例；若效果持续差，考虑切换模型 |
| 公式输出格式不统一（`$...$` vs `$$...$$` vs `\[...\]`） | 高 | 低 | 在 Prompt 中明确约束，并预留前端正则清洗逻辑 |
| 几何题绘图代码语法错误或样式不符合约定 | 高 | 中 | Sprint 1 只验证代码生成契约；执行和预校验转入后端沙箱 Story |

## 时间估算

| 任务 | 工作量 | 状态 |
|------|--------|------|
| 任务 1: 部署 Dify | 0.5 天 | ✅ 已完成 |
| 任务 2: 配置模型 | 0.5 天 | ✅ 已完成 |
| 任务 3: 题目识别节点 | 1 天 | ✅ 已完成 |
| 任务 4: 知识点提取节点 | 0.5 天 | ✅ 已完成 |
| 任务 5: 苏格拉底解答节点 | 1.5 天 | ✅ 已完成 |
| 任务 6: 串联 Chatflow | 0.5 天 | ✅ 已完成 |
| 任务 6.1: 多轮对话分支 | 1 天 | ✅ 已完成 |
| 任务 6.2: 图片上传能力 | 0.5 天 | ✅ 已完成 |
| 任务 6.3: 数学公式渲染 | 0.5 天 | ✅ 已完成 |
| 任务 7: 真实题目验证 | 0.5 天 | ✅ 已关闭 |
| **合计** | **7 天** | |

## 预期产出

- 本地运行的 Dify 实例 + 已配置的模型凭证
- 可用的完整 Chatflow（题目识别 → 知识点提取 → 苏格拉底解答）
- 验证报告（关键几何题端到端验证结果，跨学科题库回归转入后续任务）
- 沉淀的 Prompt 模板（后续迭代基础）
