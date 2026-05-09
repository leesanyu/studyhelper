# 经验教训汇总

## Dify 部署与配置

### 1. Dify 环境变量需同时配置 .env 和 docker-compose.yaml

**问题**：修改 `.env` 中的 `NEXT_PUBLIC_ENABLE_SINGLE_DOLLAR_LATEX=true` 后，重启 web 容器（`restart`）不生效，变量未出现在容器中。

**根因**：
- `docker-compose.yaml` 的 web 服务 `environment` 中没有显式列出 `NEXT_PUBLIC_ENABLE_SINGLE_DOLLAR_LATEX`，只有 API/worker 服务有
- 即使 `.env` 中设置了值，docker compose 只会将 yaml 中声明的变量传递给容器
- `restart` 不会重新读取环境变量，必须 `up -d` 重建容器

**规则**：
1. 修改 `.env` 后，需确认 `docker-compose.yaml` 对应服务的 `environment` 中有该变量的映射（如 `VAR_NAME: ${VAR_NAME:-default}`）
2. 环境变量变更后用 `docker compose up -d <service>` 重建容器，不是 `restart`
3. 验证方式：`docker exec <container> env | grep VAR_NAME`

### 2. Dify 数学公式渲染需区分行内和块级格式

**问题**：Chatflow 输出的数学公式全部显示为原始 Markdown 字符，无法渲染。

**根因**：
- Dify 默认 `NEXT_PUBLIC_ENABLE_SINGLE_DOLLAR_LATEX=false`，只渲染块级 `$$...$$`，行内 `$...$` 不渲染
- 原先所有 Prompt 统一要求用 `$$` 包裹公式（无论行内还是块级），导致行内公式被当作块级处理，显示异常
- Dify 前端使用 `@streamdown/math` + KaTeX 渲染，需 `data-enable-single-dollar-latex="true"` 注入到 HTML body 才支持行内公式

**规则**：
1. Prompt 中必须区分：行内公式用 `$...$`，独立公式块用 `$$...$$`
2. 启用行内公式需两步：`.env` 设 `NEXT_PUBLIC_ENABLE_SINGLE_DOLLAR_LATEX=true` + `docker-compose.yaml` web 服务 environment 中添加该变量
3. 验证方式：`curl -sL http://localhost/ | grep 'data-enable-single-dollar-latex'`

### 3. Dify Console API 同步 workflow graph 需要 hash

**问题**：POST `/console/api/apps/{id}/workflows/draft` 返回 `409 draft_workflow_not_sync`。

**根因**：Dify 使用 hash 做乐观锁，同步时必须携带当前 draft 的 hash，否则拒绝写入。

**规则**：
1. 先 GET draft 获取最新 `hash`
2. 修改 graph 后提交 payload 须包含 `hash`、`graph`、`features`、`environment_variables`、`conversation_variables`
3. 如果提交失败重新 GET 最新 draft 再改再提交

### 4. Dify features 修改走单独 API

**问题**：通过 workflow graph sync API 修改 `file_upload.enabled` 不生效。

**根因**：Dify 的 features（如文件上传、opening statement）与 graph 是独立的，需通过单独 API `POST /console/api/apps/{id}/workflows/draft/features` 修改。

**规则**：features 和 graph 分开更新，不要混在一个 API 调用中。

## Dify Chatflow 编排

### 5. Dify LLM 节点变量引用在变量不存在时报错

**问题**：Question Classifier 将"继续引导"路由到引导式解答节点时，报 `Variable #1778215176758.text# not found`，因为知识点提取节点未执行，其输出变量不存在。

**根因**：Dify LLM 节点的 prompt_template 中引用上游变量时，如果该变量不存在（对应节点未执行），会直接报错而非返回空值。

**规则**：当不同分支的 LLM 节点输入变量不同时，必须拆分为独立节点。首轮节点使用已写入的 `conversation.current_question/current_knowledge`，继续节点使用显式题目上下文 + Memory 追加的最新用户回复。

### 6. Dify LLM Memory 是 per-node 的，跨节点上下文必须显式保存

**问题**：用户说"别引导了，直接给我答案"时，直接解答节点看不到引导式解答的对话历史。

**根因**：Dify 的 LLM Memory 按节点隔离，不同 LLM 节点之间不共享对话历史。

**规则**：跨节点共享题目上下文时，不依赖 Memory；在 Chatflow 内用 `conversation.current_question/current_knowledge` 显式保存题目和知识点。后续接入 FastAPI 后，再由业务后端管理更完整的对话历史。

### 7. sys.dialogue_count 在 draft run 中不可靠

**问题**：使用 `sys.dialogue_count = 1` 判断首轮对话，但 draft run 中该值始终为 1。

**根因**：`sys.dialogue_count` 在调试模式下行为与生产不一致。

**规则**：使用会话变量（conversation_variables）如 `context_ready` 替代 `sys.dialogue_count` 判断是否已有题目上下文，会话变量 ID 必须为 UUID 格式。

### 8. Dify Variable Assigner v2 的变量输入字段是 value，不是 value_selector

**问题**：`VariableAssigner` 写入 `conversation.current_question/current_knowledge` 时运行失败，报 `Invalid input value None`。

**根因**：Dify 1.14 的 Variable Assigner v2 数据结构中，变量输入也使用 `value` 字段保存 selector（如 `["code_parse_question", "question_text"]`）。如果写成 `value_selector`，引擎会把输入解析为 `None`。

**规则**：通过 API 修改 graph 时，assigner item 必须使用：
```json
{
  "input_type": "variable",
  "operation": "over-write",
  "value": ["node_id", "output_name"],
  "variable_selector": ["conversation", "target_name"]
}
```

### 9. Dify LLM 节点配置 memory 会影响 sys.query 注入

**问题**：首轮引导节点和直接解答节点即使关闭 `memory.window.enabled`，实际 prompt 仍额外追加了用户原始 `sys.query`，导致"直接给答案"等指令污染首轮引导，或让直接解答混入历史上下文。

**根因**：Dify LLM 节点只要存在 `memory` 配置，就会解析 `memory.query_prompt_template`；若模板存在则追加该 query，若模板为空也可能回退到默认 `sys.query`。`window.enabled=false` 只关闭历史窗口，不等于关闭 query 注入。

**规则**：
1. 不需要历史上下文的 LLM 节点（如"引导式解答（首轮）"、"直接解答"）不要配置 `memory` 字段
2. 需要多轮历史的节点（如"引导式解答（继续）"）才开启 Memory
3. 继续节点的 prompt_template 不要再手动写 `{{#sys.query#}}`，避免和 Memory query 追加重复

### 10. 直接解答后不要清空题目上下文

**问题**：直接解答后清空 `current_question/current_knowledge`，用户继续追问"为什么这一步成立"时会被误判为新题，导致重新识别或上下文丢失。

**根因**：`topic_resolved=true` 被当作"下一轮重走完整流程"的触发条件，但学习场景里直接答案后仍常有追问。

**规则**：直接解答后只记录已给出直接答案，不清空题目上下文；只有用户明确提出"新题目"时才重建 `current_question/current_knowledge`。

### 11. Dify 流程修复必须用真实题图验证最终答案质量

**问题**：只检查路由、变量写入和节点是否执行，会漏掉"上下文存在但语义不足"的问题，例如几何题直接解答仍可能因缺少图形关系而给出错误答案。

**根因**：工作流编排正确不等于答案上下文充分；对图形题尤其需要验证题目识别输出是否包含可供后续节点推理的图形拓扑关系。

**规则**：修复解题链路后，必须用 `tests/questions/` 中的真实题图跑端到端验证，检查最终答案是否尊重题图关系，而不只检查 workflow run 是否成功。

### 12. Dify LLM Vision 生效要同时看 inputs 和 process_data.prompts

**问题**：解题节点开启 Vision 后，节点 inputs 中能看到 `#files#`，但实际模型请求 `process_data.prompts[*].files` 仍为空，几何题直接解答继续按纯文本推理。

**根因**：Dify 会根据当前模型 schema 过滤 prompt content；如果模型在插件 schema 中不支持图片，文件变量会被取到但不会进入最终 LLM prompt。实测 `glm-5.1` 出现该问题，`qwen3.6-plus` 能保留图片 prompt。

**规则**：
1. 验证图片上下文时必须同时检查节点 `inputs.#files#` 和 `process_data.prompts[*].files`
2. 如果某个节点设计上需要直接看图，应使用当前 Dify 插件中确认为 vision-capable 的模型；当前 Sprint1 解题节点已改为纯文本，不再直接看图
3. 不要把"节点 Vision 开启"等同于"模型实际看到了图片"

### 13. 题图只进识别节点，解题节点消费图形文本

**问题**：为修复几何题错误，曾把题图继续传给直接解答/引导式解答节点，但这会让流程职责不清，也无法保证多轮追问时上下文一致。

**根因**：`题目识别` 节点已经具备 Vision 能力，正确架构应由它把图片转成稳定的 `question_text + diagram_description`；下游解题节点只消费会话变量中的文本上下文。

**规则**：
1. 图片只进入 `题目识别` 节点；`直接解答`、`引导式解答（首轮）`、`引导式解答（继续）` 的 Vision 保持关闭
2. `题目识别` 必须输出 `diagram_description`，`code_parse_question` 必须解析并写入 `conversation.current_diagram`
3. 验证解题节点上下文时，必须确认 `process_data.prompts[*].files=[]` 且 user prompt 中包含 `## 图形关系`

### 14. 题目识别不能把图形推导写入上下文

**问题**：识别节点曾在 `diagram_description` 中写入“角和、互余、互补”等推导性关系，直接解答节点把这些内容当作已知，导致几何题证明混乱甚至判断图文冲突。

**根因**：识别节点和解题节点职责混用。识别节点应描述直接可见的点线角、垂直、共线、位置顺序，不应替下游完成证明。

**规则**：
1. `diagram_description` 只描述题干和图片直接给出的拓扑/标记
2. 禁止输出“因此、所以、故、可得、推出、说明、表明”等推导结论
3. 禁止输出角度代数关系、角和、互余、互补、全等、相似等结论，除非题干文字直接给出或图上明确标注
4. 解析节点应兜底过滤残留推导性语句，避免污染 `current_diagram`

### 15. 题目识别 JSON 要容错 LaTeX 反斜杠

**问题**：识别节点有时会输出形似 JSON 的文本，但 LaTeX 中的 `\angle`、`\circ` 没有按 JSON 字符串规则转义，导致 `json.loads` 失败，解析节点回退为原始文本，`current_diagram` 变空。

**根因**：LLM 的“严格 JSON”并不稳定，数学题 OCR/识别输出里高频出现反斜杠，必须在解析层做有限容错。

**规则**：
1. `code_parse_question` 先按标准 JSON 解析，失败后只修复非法 JSON 反斜杠转义，再重试
2. 容错逻辑不能吞掉解析失败；如果最终失败，必须让 `has_figure=false` 和 `diagram_description=""` 的回退行为可观测
3. 端到端验证必须检查 `code_parse_question.has_figure=true` 且 `diagram_description` 非空，不能只看最终答案是否碰巧正确
