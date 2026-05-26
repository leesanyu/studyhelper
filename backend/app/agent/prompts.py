# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

"""Agent Prompt 模板。

每个 Prompt 为一个函数，返回组装好的 messages 列表。
变量插值使用 str.format_map()，语法为 {variable_name}。
"""

import json
from typing import Any


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
        "5. 题目中包含图形时，必须填写 visual_observation 对象；无法确认的数组可为空，但字段不能省略\n"
        "6. 多道题在同一输入中，全部提取，用 --- 分隔\n"
        "7. 只输出严格 JSON，不要输出 Markdown 代码块，不要解释\n"
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
        "## visual_observation 输出要求\n"
        "\n"
        "当 has_figure=true 时，必须输出 visual_observation：\n"
        "- ocr_text：题图中可见文字，不能省略题干条件\n"
        "- points：图中可见点标签数组，每项包含 id、confidence，可选 coordinate\n"
        "- drawn_segments：图中已画线段数组，每项包含 endpoints、confidence\n"
        "- marks：图中直角、等长、平行等标记数组\n"
        "- uncertain：无法确定的点序、遮挡、图文冲突等数组\n"
        "coordinate 若能估计，使用归一化二维坐标 [x, y]，只作绘图布局提示；无法估计时可省略。\n"
        "如果有图1、图2、备用图，优先为与题干当前小问最相关的图输出点和线；无法判断时汇总全部可见点和线。\n"
        "\n"
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
        ' "visual_observation": {"ocr_text": "", "points": [], "drawn_segments": [], "marks": [], "uncertain": []},'
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

## 几何辅助线表达

解题阶段以文字证明为主；绘图由后置 Figure Agent 根据题图和辅助线说明处理，通常不需要输出绘图代码。

如果解题使用辅助线，应在证明前或证明中用自然语言清楚说明构造动作。建议单独输出一行：

【辅助线】延长/连接/作垂线/取点……。

辅助线说明只描述构造动作，不写证明理由；不需要辅助线时，不输出该行。

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
    current_geometry: dict | None = None,
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
        current_geometry: 当前结构化几何上下文
        tool_results: 工具执行结果（如 process_question/extract_knowledge 的输出）
    """
    system_content = _SOLVING_SYSTEM_PROMPT.format_map(
        {"strategy": strategy}
    )
    has_structured_geometry = _has_structured_geometry(
        current_geometry=current_geometry,
        tool_results=tool_results,
    )
    if has_structured_geometry:
        system_content += (
            "\n\n## 结构化几何辅助线规则\n"
            "- 绘图由后置 Figure Agent 根据题图、文字解答和辅助线说明处理。\n"
            "- 如果解题使用辅助线，必须单独输出一行 `【辅助线】...`，便于 Figure Agent 整理绘图目标。\n"
            "- `【辅助线】` 句只描述构造动作，不写证明理由。\n"
            "- 不需要辅助线时，不输出 `【辅助线】`。\n"
            "- 必须优先遵守用户指定年级和知识范围；若用户要求使用全等知识，证明主线必须写成全等三角形的判定与性质。\n"
            "- 用户要求七年级或全等证明时，不得把勾股定理或平方代数作为主证明。\n"
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
    if current_geometry:
        context_parts.append(f"[结构化几何]\n{current_geometry}")
    if current_knowledge:
        context_parts.append(f"[知识点]\n{current_knowledge}")

    if context_parts:
        content_parts.append("\n" + "\n".join(context_parts))

    messages.append({"role": "user", "content": " ".join(content_parts)})
    return messages


def _has_structured_geometry(
    *,
    current_geometry: dict | None,
    tool_results: dict | None,
) -> bool:
    if _is_renderable_geometry(current_geometry):
        return True
    if not tool_results:
        return False
    process_result = tool_results.get("process_question")
    if isinstance(process_result, str):
        try:
            parsed_result = json.loads(process_result)
        except json.JSONDecodeError:
            return False
        if not isinstance(parsed_result, dict):
            return False
        return _is_renderable_geometry(parsed_result.get("geometry_scene_candidate"))
    if isinstance(process_result, dict):
        return _is_renderable_geometry(process_result.get("geometry_scene_candidate"))
    return False


def _is_renderable_geometry(geometry: Any) -> bool:
    if not isinstance(geometry, dict):
        return False
    observations = geometry.get("observations", {})
    if not isinstance(observations, dict):
        return False
    points = observations.get("points", [])
    if isinstance(points, list) and len(points) >= 2:
        return True
    drawn_segments = observations.get("drawn_segments", [])
    return isinstance(drawn_segments, list) and len(drawn_segments) > 0


def build_figure_trigger_messages(
    *,
    question_text: str,
    diagram_description: str,
    solve_content: str,
    existing_python_figure: str | None,
) -> list[dict[str, str]]:
    """构建 Figure Agent 触发判断 Prompt。"""
    system = """你是几何绘图触发判断器。
你只判断是否需要为当前解答补充辅助线图，不重新解题。
如果解答中有几何辅助线、关键构造、点线角关系说明，通常需要绘图。
置信度只用于 warning，不作为是否绘图的硬闸门。

只输出 JSON：
{
  "figure_needed": true,
  "reason": "",
  "auxiliary_intent": "",
  "confidence": 0.0,
  "existing_python_figure": ""
}
"""
    user = (
        f"[题干]\n{question_text or '未提供'}\n\n"
        f"[题图描述]\n{diagram_description or '未提供'}\n\n"
        f"[完整解答]\n{solve_content}\n\n"
        f"[已有 python:figure]\n{existing_python_figure or ''}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def build_figure_goal_messages(
    *,
    question_text: str,
    diagram_description: str,
    visual_observation: dict | None,
    geometry_scene_candidate: dict | None,
    solve_content: str,
    auxiliary_intent: str | None,
    trigger: dict | None,
) -> list[dict[str, str]]:
    """构建 Goal Check Prompt。"""
    system = """你是几何绘图目标整理器。
请根据题目、题图描述、完整解答和辅助线意图，整理一份绘图目标。
不要重新证明题目，不评价辅助线是否最优，不要自己改写证明。

只输出 JSON：
{
  "goal_status": "ready",
  "render_mode": "overlay_on_crop",
  "target_diagram": "",
  "coordinate_space": "crop_pixels",
  "normalized_auxiliary_intent": "",
  "expected_auxiliary": [],
  "original_figure_elements": [],
  "layout_hint": {"directed_rays": []},
  "style_requirements": {},
  "warnings": []
}
"""
    user = (
        f"[题干]\n{question_text or '未提供'}\n\n"
        f"[题图描述]\n{diagram_description or '未提供'}\n\n"
        f"[视觉观察]\n{visual_observation or {}}\n\n"
        f"[结构化几何候选]\n{geometry_scene_candidate or {}}\n\n"
        f"[完整解答]\n{solve_content}\n\n"
        f"[辅助线意图]\n{auxiliary_intent or ''}\n\n"
        f"[触发信息]\n{trigger or {}}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def build_target_crop_messages(
    *,
    image_base64: str,
    image_size: tuple[int, int] | None = None,
    question_text: str,
    diagram_description: str,
    solve_content: str,
    figure_goal: dict,
) -> list[dict]:
    """构建目标几何图裁剪 Prompt。"""
    system = """你是目标几何图裁剪工具的视觉定位器。
请在整页题图中定位当前小问最相关的几何图区域，返回像素裁剪框。
不要解题，不要新增几何关系。若无法判断，返回覆盖所有几何图的最小区域。

裁剪对象必须是目标几何图本身，不要截取题干文字、其他小问文字或空白区域。
如果 Goal Check / 题干指向「图2」，必须优先截取图下方标注为「图2」的中间几何图；
不要截取图1、备用图、B' 所在图或第（1）/第（3）问对应区域。
crop_box 必须包含目标图中的已有点标签和主要线段，例如 original_figure_elements 里的 A/B/C/D/E/H 等点；
可以包含少量边距和图下方「图2」标签，但题干文字不应占主要画面。

只输出 JSON：
{
  "label": "图2",
  "crop_box": [left, top, right, bottom],
  "confidence": 0.0,
  "warnings": []
}
"""
    text = (
        "目标几何图裁剪\n\n"
        f"[原图像素尺寸]\n{_format_image_size(image_size)}\n\n"
        f"[题干]\n{question_text or '未提供'}\n\n"
        f"[题图描述]\n{diagram_description or '未提供'}\n\n"
        f"[完整解答]\n{solve_content}\n\n"
        f"[Goal Check]\n{figure_goal}"
    )
    return [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": text},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{image_base64}"},
                },
            ],
        },
    ]


def _format_image_size(image_size: tuple[int, int] | None) -> str:
    if not image_size:
        return "未知；若无法确认尺寸，也必须返回整张输入图片坐标系中的像素 crop_box。"
    width, height = image_size
    return (
        f"原图像素尺寸：{width} x {height}。"
        "crop_box 必须使用该真实像素坐标系，格式为 [left, top, right, bottom]。"
    )


def build_point_location_messages(
    *,
    image_base64: str,
    image_size: tuple[int, int] | None = None,
    point_labels: list[str],
    question_text: str,
    diagram_description: str,
    solve_content: str,
    figure_goal: dict,
) -> list[dict]:
    """构建裁剪图点位定位 Prompt。"""
    system = """你是几何图点位定位器。当前图片是目标几何图附近的裁剪图。
请返回给定几何点在当前裁剪图中的像素坐标；点标签只用于识别相邻几何点，不是要定位字母文字。
点位应落在线条交汇或端点处，不要落在字母文字本身。
只定位图中已有点，不创造新点；如果某个标签不可见，可以省略并在 warnings 中说明。

只输出 JSON：
{
  "points": {
    "A": {"x": 0, "y": 0, "confidence": 0.0}
  },
  "warnings": []
}
"""
    if image_size:
        size_text = f"裁剪图尺寸：{image_size[0]}x{image_size[1]} 像素。"
    else:
        size_text = "裁剪图尺寸：未知；坐标仍必须使用当前输入图片的像素坐标系。"
    text = (
        "点位定位\n\n"
        f"{size_text}\n"
        f"待定位点：{point_labels}\n"
        f"题目信息：{question_text or '未提供'}\n"
        f"题图描述：{diagram_description or '未提供'}\n\n"
        "坐标必须是当前裁剪图的像素坐标，不是整页原图坐标，也不是归一化坐标。"
        "只返回待定位点中的已有几何点；不要返回 B'、其他图中的点或未请求标签。"
    )
    return [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": text},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{image_base64}"},
                },
            ],
        },
    ]


def build_figure_overlay_draw_messages(
    *,
    question_text: str,
    diagram_description: str,
    solve_content: str,
    figure_goal: dict,
    target_diagram: dict,
    localized_points: dict,
    auxiliary_text: str,
) -> list[dict[str, str]]:
    """构建 overlay plan Draw Prompt。"""
    system = """你是几何辅助线 overlay 绘图规划器。
请根据题目、解答、辅助线原文、Goal Check、目标图裁剪结果和点位定位结果，输出 overlay plan。
不要重新解题，不要修改证明。代码工具会按你的 plan 在裁剪图上绘制。

关键约束：
- 有向 ray 不能混用：ray "AE" 表示从 A 经 E 往 E 外侧延长，ray "EA" 表示从 E 经 A 往 A 外侧延长。
- 新点只能通过 constructions 描述，工具负责坐标计算。
- 只能使用工具支持的 op schema，不要输出 type/segment/name/construction 这种自然语言 schema。
- 支持的 op：
  1. {"op": "point_on_segment_by_distance", "point": "F", "ray": "AE", "from": "A", "distance": "2*AE"}
  2. {"op": "point_on_perpendicular_by_distance", "point": "K", "vertex": "C", "perpendicular_to": "CE", "distance": "CE", "side_reference": "B"}
  3. {"op": "connect_points", "points": ["C", "F"]}
  4. {"op": "highlight_segment", "points": ["A", "F"]}
  5. {"op": "right_angle_marker", "at": "E"}
  6. {"op": "note", "at": "F", "text": "F"}
- 如果无法 overlay，返回 {"plan_type": "fallback_python_figure", "reason": "..."}。

只输出 JSON：
{
  "plan_type": "overlay_on_crop",
  "coordinate_space": "crop_pixels",
  "intent": "",
  "constructions": [
    {"op": "point_on_segment_by_distance", "point": "F", "ray": "AE", "from": "A", "distance": "2*AE"},
    {"op": "connect_points", "points": ["C", "F"]},
    {"op": "connect_points", "points": ["B", "F"]}
  ],
  "warnings": []
}
"""
    user = (
        f"[题干]\n{question_text or '未提供'}\n\n"
        f"[题图描述]\n{diagram_description or '未提供'}\n\n"
        f"[完整解答]\n{solve_content}\n\n"
        f"[辅助线原文]\n{auxiliary_text or ''}\n\n"
        f"[Goal Check]\n{figure_goal}\n\n"
        f"[目标图裁剪]\n{target_diagram}\n\n"
        f"[点位定位]\n{localized_points}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def build_figure_overlay_revision_messages(
    *,
    question_text: str,
    diagram_description: str,
    solve_content: str,
    figure_goal: dict,
    target_diagram: dict,
    localized_points: dict,
    auxiliary_text: str,
    previous_plan: dict,
    observation: dict,
) -> list[dict[str, str]]:
    """构建 overlay plan Revision Prompt。"""
    system = """你是几何辅助线 overlay 绘图修正器。
你不会重新解题，只根据 Observation 修正上一版 overlay plan。
优先保留已正确的构造，修正缺点、缺线、方向错误或不支持的 operation。
只能使用工具支持的 op schema：point_on_segment_by_distance、point_on_perpendicular_by_distance、connect_points、highlight_segment、right_angle_marker、note。
不要输出 type/segment/name/construction 这种自然语言 schema。

只输出 JSON：
{
  "plan_type": "overlay_on_crop",
  "coordinate_space": "crop_pixels",
  "intent": "",
  "constructions": [
    {"op": "point_on_segment_by_distance", "point": "F", "ray": "AE", "from": "A", "distance": "2*AE"},
    {"op": "connect_points", "points": ["C", "F"]},
    {"op": "connect_points", "points": ["B", "F"]}
  ],
  "warnings": []
}
"""
    user = (
        f"[题干]\n{question_text or '未提供'}\n\n"
        f"[题图描述]\n{diagram_description or '未提供'}\n\n"
        f"[完整解答]\n{solve_content}\n\n"
        f"[辅助线原文]\n{auxiliary_text or ''}\n\n"
        f"[Goal Check]\n{figure_goal}\n\n"
        f"[目标图裁剪]\n{target_diagram}\n\n"
        f"[点位定位]\n{localized_points}\n\n"
        f"[上一版 overlay plan]\n{previous_plan}\n\n"
        f"[Observation]\n{observation}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def build_figure_draw_messages(
    *,
    question_text: str,
    diagram_description: str,
    solve_content: str,
    figure_goal: dict,
) -> list[dict[str, str]]:
    """构建 Draw Plan Prompt。"""
    system = """你是几何辅助线绘图 Agent。
请根据题目、解答和 Goal Check 输出生成一张 matplotlib 示意图。
保留原图主要点和已知线，清晰画出 expected_auxiliary 中的辅助线。
辅助线使用红色虚线，原图线段使用黑色实线，标签必须可读。
图是示意图，不要求比例完全等同原题图。
不要读取文件，不要访问网络，不要调用 plt.savefig()。

输出优先使用一个 python:figure 代码块，不解释。
"""
    user = (
        f"[题干]\n{question_text or '未提供'}\n\n"
        f"[题图描述]\n{diagram_description or '未提供'}\n\n"
        f"[完整解答]\n{solve_content}\n\n"
        f"[Goal Check]\n{figure_goal}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def build_figure_revision_messages(
    *,
    question_text: str,
    diagram_description: str,
    solve_content: str,
    figure_goal: dict,
    previous_code: str,
    observation: dict,
) -> list[dict[str, str]]:
    """构建 Revision Prompt。"""
    system = """你是几何绘图修正器。
你不会重新解题，只根据 Observation 修改上一版 matplotlib 代码。
必须保留原图主要点和已正确绘制的部分，修复 sandbox 错误、无输出、空白图或样式问题。
辅助线使用红色虚线，原图线段使用黑色实线，隐藏坐标轴。
不要读取文件，不要访问网络，不要调用 plt.savefig()。

输出：
正常修图时只输出一个 python:figure 代码块，不解释。
若绘图目标缺失、矛盾或无法落图，只输出 {"status": "need_redraw_plan", "reason": "..."}。
"""
    user = (
        f"[题干]\n{question_text or '未提供'}\n\n"
        f"[题图描述]\n{diagram_description or '未提供'}\n\n"
        f"[完整解答]\n{solve_content}\n\n"
        f"[Goal Check]\n{figure_goal}\n\n"
        f"[上一版代码]\n{previous_code}\n\n"
        f"[Observation]\n{observation}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def build_figure_semantic_inspection_messages(
    *,
    question_text: str,
    diagram_description: str,
    solve_content: str,
    figure_goal: dict,
    render_result: dict,
    observation: dict,
) -> list[dict[str, str]]:
    """构建 Figure Agent 语义自检 Prompt。"""
    system = """你是几何辅助线图的语义观察员。
你只根据题目、解答、Goal Check 和渲染结果判断图片是否大体表达了目标辅助线。
不要重新证明题目，不要用代码规则穷举辅助线；你的输出只作为 Revision 的 Observation。
低分或缺失项不代表必须阻断展示，应给出 next_action 供绘图 Agent 修正或接受 best effort。
必须检查有向延长线是否和文字一致，例如 ray "AE" 表示从 A 经 E 往 E 外侧延长，不能画成 ray "EA"。

只输出 JSON：
{
  "keep": [],
  "missing": [],
  "wrong": [],
  "style_issues": [],
  "score": 0,
  "next_action": "accept_best_effort",
  "suggested_fix": ""
}

next_action 只能是 revise_code、redraw_plan、accept_best_effort。
"""
    user = (
        f"[题干]\n{question_text or '未提供'}\n\n"
        f"[题图描述]\n{diagram_description or '未提供'}\n\n"
        f"[完整解答]\n{solve_content}\n\n"
        f"[Goal Check]\n{figure_goal}\n\n"
        f"[渲染结果]\n{render_result}\n\n"
        f"[程序级 Observation]\n{observation}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
