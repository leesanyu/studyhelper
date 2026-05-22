# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

"""Agent Prompt 模板。

每个 Prompt 为一个函数，返回组装好的 messages 列表。
变量插值使用 str.format_map()，语法为 {variable_name}。
"""


def build_process_question_messages(
    *,
    image_base64: str | None = None,
    text: str | None = None,
) -> list[dict]:
    """构建题目识别/标准化 Prompt 的 messages。

    有图片时传 image_base64，纯文字时只传 text。
    """
    system_prompt = (
        "你是一个专业的题目识别助手。从用户提供的题目内容中准确提取题目信息，"
        "并把图形题中直接可见的图形拓扑转写成文字上下文。\n"
        "\n"
        "## 输出规则\n"
        "\n"
        "1. 准确提取题目中的所有文字，不遗漏、不臆造\n"
        "2. 数学公式用 LaTeX 格式，行内公式用 $...$ 包裹，独立公式块用 $$...$$ 包裹\n"
        "3. 化学方程式用 LaTeX 格式，行内用 $...$ 包裹，独立块用 $$...$$ 包裹\n"
        "4. 题目中包含图形时，has_figure 标记为 true，并填写 diagram_description\n"
        "5. 多道题在同一输入中，全部提取，用 --- 分隔\n"
        "6. 只输出严格 JSON，不要输出 Markdown 代码块，不要解释\n"
        "\n"
        "## 图形关系识别要求\n"
        "\n"
        "当 has_figure=true 时，diagram_description 只描述题目直接给出的信息：\n"
        "- 点、线、线段、射线的位置关系\n"
        "- 已画出的连线\n"
        "- 角标记\n"
        "- 已知垂直、平行、相等、边长、角度等标记\n"
        "- 若题目有图1、图2，分别描述\n"
        '- 不确定的位置关系写"图中未明确标注"\n'        "\n"
        "## 禁止事项\n"
        "\n"
        "- 不要完成证明，不要推导最终答案\n"
        '- 不要写"因此、所以、故、可得、推出"等推导结论\n'
        "- 不要输出角度代数关系、角和、互余、互补等结论，除非题干直接给出\n"
        "\n"
        "如果没有图形，diagram_description 为空字符串。\n"
        "\n"
        "## 学科分类\n"
        "\n"
        "从以下选项中选择：\n"
        "- 小学数学、小学语文、小学英语\n"
        "- 初中数学、初中物理、初中化学、初中英语、初中语文\n"
        "- 高中数学、高中物理、高中化学、高中英语、高中语文、高中生物\n"
        "- 非学科内容\n"
        "\n"
        "## 输出格式（严格 JSON）\n"
        "\n"
        '{"subject": "初中数学",'
        ' "question_text": "题目文本",'
        ' "has_figure": false,'
        ' "diagram_description": "",'
        ' "question_count": 1}'
    )

    messages: list[dict] = [{"role": "system", "content": system_prompt}]

    # 构建用户消息
    if image_base64 and text:
        # 图片+文字组合
        messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": text},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{image_base64}"
                        },
                    },
                ],
            }
        )
    elif image_base64:
        # 仅图片
        messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{image_base64}"
                        },
                    }
                ],
            }
        )
    elif text:
        # 仅文字
        messages.append({"role": "user", "content": text})
    else:
        raise ValueError("必须提供 image_base64 或 text 至少一项")

    return messages


def build_extract_knowledge_messages(
    *,
    question_text: str,
    subject: str,
) -> list[dict]:
    """构建知识点提取 Prompt 的 messages。"""
    system_prompt = (
        "你是一个知识点标注专家。根据题目内容，提取该题目考查的知识点。\n"
        "\n"
        "## 标注规则\n"
        "\n"
        "1. 知识点粒度为二级（学科-具体知识点），必须是教学大纲标准名称\n"
        "2. 一道题可对应多个知识点，按关联度从高到低排列，最多3个\n"
        "3. 难度分为：简单、中等、困难\n"
        "4. 年级信息为可选字段，模型拿不准时不填\n"
        "\n"
        "## 输出格式（严格 JSON）\n"
        "\n"
        '{"subject": "初中数学",'
        ' "knowledge_points": ["知识点1", "知识点2"],'
        ' "difficulty": "简单",'
        ' "grade_level": "八年级"}'
    )

    user_content = f"学科：{subject}\n题目：{question_text}"

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]


# ── 规划层 Prompt ────────────────────────────────────────────────

_PLANNING_SYSTEM_PROMPT = """\
你是一个教学策略规划助手。分析学生的消息，判断题目类型和最佳教学策略。

## 输出字段说明

- question_type：题目类型
  - definition：概念定义类问题
  - logical_calculation：逻辑推理/计算类问题
  - homework_help：作业辅导请求
  - direct_answer_request：学生明确要求直接给答案
  - continue_dialogue：继续当前对话（如"我还是不懂"、"我理解了"等）

- strategy：教学策略
  - socratic_guide：苏格拉底式引导，反问启发，不直接给答案
  - step_breakdown：更细致的分步拆解，逐步引导
  - direct_answer：直接给出完整解答和最终答案
  - summarize_and_similar：总结要点 + 生成相似题
  - knowledge_lookup：知识点查询和讲解

- tool_calls：需要执行的工具列表
  - 新题目或上传图片时：["process_question", "extract_knowledge"]
  - 已有题目上下文时：[]
  - 可选值："process_question"、"extract_knowledge"

- need_deep_reflexion：是否需要深度反思
  - 学生表达不满（如"不对"、"还是错"）时设为 true
  - 其余情况设为 false

## 决策规则

1. 学生明确要求直接答案 → strategy=direct_answer
2. 学生表示不理解 → strategy=step_breakdown
3. 学生表示理解了 → strategy=summarize_and_similar
4. 新题目/上传图片 → tool_calls 包含 process_question 和 extract_knowledge
5. 已有上下文的追问 → tool_calls 为空
6. 学生表达不满 → need_deep_reflexion=true

## 输出格式（严格 JSON）

{"question_type": "logical_calculation", "strategy": "socratic_guide", "tool_calls": ["process_question", "extract_knowledge"], "need_deep_reflexion": false}"""


def build_planning_messages(
    *,
    user_message: str,
    image_summary: str | None = None,
    chat_history: list[dict] | None = None,
    current_question: str | None = None,
    current_knowledge: str | None = None,
    current_diagram: str | None = None,
) -> list[dict]:
    """构建规划层 Prompt 的 messages。

    Args:
        user_message: 用户最新消息
        image_summary: 图片摘要（如"[用户上传了一张包含数学题目的图片，300KB]"）
        chat_history: 对话历史（OpenAI 格式消息列表）
        current_question: 当前题目上下文（如有）
        current_knowledge: 当前知识点上下文（如有）
        current_diagram: 当前图形描述上下文（如有）
    """
    messages: list[dict] = [{"role": "system", "content": _PLANNING_SYSTEM_PROMPT}]

    # 追加对话历史
    if chat_history:
        messages.extend(chat_history)

    # 构建当前用户消息（含图片摘要和上下文提示）
    content_parts: list[str] = []
    if image_summary:
        content_parts.append(image_summary)
    content_parts.append(user_message)

    if current_question:
        content_parts.append(
            f"\n[当前题目上下文]\n题干：{current_question}"
        )
    if current_diagram:
        content_parts.append(f"图形描述：{current_diagram}")
    if current_knowledge:
        # current_knowledge 可能是 dict 或 str
        knowledge_str = (
            str(current_knowledge)
            if not isinstance(current_knowledge, dict)
            else str(current_knowledge)
        )
        content_parts.append(f"知识点：{knowledge_str}")

    messages.append({"role": "user", "content": " ".join(content_parts)})
    return messages


# ── 执行层 Prompt ────────────────────────────────────────────────

_SOLVING_SYSTEM_PROMPT = """\
你是一位耐心、亲和的苏格拉底式导师。你引导中小学生自己发现答案，而不是直接告诉他们。

## 当前教学策略

当前策略：{strategy}

各策略对应的行为：
- socratic_guide：反问启发，不直接给答案，每次只推进一个思考步骤
- step_breakdown：更细致的分步拆解，每步给出具体提示和引导问题
- direct_answer：直接给出完整解题过程和最终答案
- summarize_and_similar：总结本次题目的核心知识点（至少2条要点），然后生成一道相似题（不含答案）
- knowledge_lookup：讲解相关知识点，举例说明

## 内部推理（不展示给用户）

在回答前，先按以下模板完成内部推理：

【思路】用1句话概括本题的核心解法方向
【关键步骤】列出解题的关键步骤（不超过5步），每步不超过15字
【易错点】1-2个学生容易犯错的地方
【自检】最终答案是否出现在上述步骤中？是→删除，否→继续

内部推理完成后，基于推理结果生成给用户的回复。

## 苏格拉底式引导规则（socratic_guide / step_breakdown 专用）

- 每次只推进一个思考步骤，不超过150字
- 用反问启发，不直接给出答案
- 绝不泄露最终答案或关键中间结果

## 直接解答规则（direct_answer 专用）

- 给出完整的解题过程，步骤清晰
- 最后单独列出"最终答案：..."
- 确保推理链前后一致，不出现试错过程

## 几何图形生成

当题目涉及几何图形（含辅助线、角度标注、边长标注等）时，必须生成 Python 绘图代码。

触发条件：当题目的解答过程需要可视化图形辅助理解时（如需要画辅助线、标注角度），则生成绘图代码。

### 绘图规范

1. 使用 matplotlib 绘图
2. 坐标系：隐藏坐标轴（plt.axis('off')）
3. 图形比例：plt.gca().set_aspect('equal')
4. 样式约定：
   - 已知边/线：黑色实线，线宽 1.5
   - 辅助线：红色虚线（linestyle='--', color='red'），线宽 1.5
   - 已知条件标注：蓝色文字（color='blue'）
   - 求解目标标注：绿色文字（color='green'）
   - 顶点字母：黑色粗体
5. 图片尺寸：figsize=(6, 6)，dpi=100
6. 保存：plt.savefig('figure.png', bbox_inches='tight', pad_inches=0.1)

### 代码输出格式

用以下标记包裹 Python 代码：

```python:figure
# 你的绘图代码
```

注意标记为 python:figure，前端据此识别需提交沙箱执行。

### 代码要求

1. 不使用网络请求（requests、urllib 等）
2. 不使用文件读取（open、os 等），只使用 matplotlib 绑图
3. 代码必须在 5 秒内执行完毕
4. 只生成一张图，文件名为 figure.png

## 格式要求

1. Markdown 格式，行内数学公式用 $...$ 包裹，独立公式块用 $$...$$ 包裹
2. 语气亲和、鼓励，像一位耐心的老师
3. 不输出 JSON 或结构化标签"""


def build_solving_messages(
    *,
    strategy: str,
    user_message: str,
    image_summary: str | None = None,
    chat_history: list[dict] | None = None,
    current_question: str | None = None,
    current_knowledge: str | None = None,
    current_diagram: str | None = None,
    tool_results: dict | None = None,
) -> list[dict]:
    """构建执行层 Prompt 的 messages。

    Args:
        strategy: 规划层输出的教学策略
        user_message: 用户最新消息
        image_summary: 图片摘要（如有）
        chat_history: 对话历史
        current_question: 当前题目上下文
        current_knowledge: 当前知识点上下文
        current_diagram: 当前图形描述
        tool_results: 工具执行结果（如 process_question/extract_knowledge 的输出）
    """
    system_content = _SOLVING_SYSTEM_PROMPT.format_map(
        {"strategy": strategy}
    )
    messages: list[dict] = [{"role": "system", "content": system_content}]

    # 追加对话历史
    if chat_history:
        messages.extend(chat_history)

    # 构建当前用户消息
    content_parts: list[str] = []
    if image_summary:
        content_parts.append(image_summary)
    content_parts.append(user_message)

    # 追加工具执行结果和上下文
    context_parts: list[str] = []
    if tool_results:
        for tool_name, result in tool_results.items():
            context_parts.append(f"[工具结果: {tool_name}]\n{result}")
    if current_question:
        context_parts.append(f"[当前题目]\n{current_question}")
    if current_diagram:
        context_parts.append(f"[图形描述]\n{current_diagram}")
    if current_knowledge:
        context_parts.append(f"[知识点]\n{current_knowledge}")

    if context_parts:
        content_parts.append("\n" + "\n".join(context_parts))

    messages.append({"role": "user", "content": " ".join(content_parts)})
    return messages
