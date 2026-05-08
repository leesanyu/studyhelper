# 节点 D：直接解答

> 位置：Dify Chatflow → LLM 节点（直接解答）
> 触发：解答方式分类 / 意图分类为"直接给答案"
> 输入：`conversation.current_question` + `conversation.current_knowledge` + 用户请求（`sys.query`）+ 用户上传题图（`sys.files`，如有）
> 输出：完整解题过程和最终答案
> 后续：VariableAssigner(设置 `topic_resolved="true"`，保留题目上下文) → VariableAggregator → Answer
> 模型：`qwen3.6-plus`

## Prompt

```
你是一位专业的学科辅导老师。请根据题目内容，直接给出完整解题过程和最终答案。

## 格式要求

1. Markdown 格式，行内数学公式用 $...$ 包裹，独立公式块用 $$...$$ 包裹
2. 给出详细的解题步骤，每步说明思路和计算
3. 最后明确给出最终答案
4. 如果涉及几何图形，按照 matplotlib 规范生成绘图代码，用 ```python:figure 标记包裹
5. 语气专业、清晰
```

## 设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 独立节点 | 与引导式解答分开 | Prompt 和输出风格完全不同（直接给答案 vs 引导式） |
| Memory | 不配置 Memory | 避免历史引导内容、错误推理或原始 `sys.query` 追加污染最终答案 |
| 上下文来源 | 会话变量 `current_question/current_knowledge` | 由题目识别和知识点提取链路提前写入，保证直接解答有干净题目上下文 |
| Vision | 开启，指向 Start 节点 `sys.files` | 几何题直接解答需要原始题图，避免 OCR 后纯文本缺少图形拓扑导致错误推理 |
| 模型 | `qwen3.6-plus` | 当前 Dify/Tongyi 插件中该模型会保留图片 prompt；`glm-5.1` 的图片会被 schema 过滤，导致解题节点实际仍是纯文本 |

## 已知限制

Dify 的 LLM 节点只要配置 `memory`，就可能追加 `sys.query` 或历史消息。直接解答节点不配置 Memory，只使用当前题目上下文和用户最新请求。

直接解答后不清空 `current_question/current_knowledge`，这样用户继续问"为什么这一步成立"时仍能复用当前题目上下文。

当用户当前消息携带题图时，直接解答节点必须开启 Vision 并接收 `sys.files`，否则几何图中的点线位置关系会丢失，模型只能根据题干文本补全图形关系，容易产生错误答案。

仅开启 Vision 不够，还必须使用支持图片输入的模型。实测 `glm-5.1` 节点 inputs 中能看到 `#files#`，但 process_data.prompts 中 `files=[]`；切换到 `qwen3.6-plus` 后 direct_answer 的 user prompt 中 `files` 正常保留。
