# 节点 A：题目识别

> 位置：Dify Chatflow → LLM 节点 A（题目识别）
> 输入：用户上传的题目图片 + 文字描述（sys.query + sys.files）
> 输出：题干文本（含 LaTeX 公式）+ 学科分类 JSON
> Vision：已启用（`vision.enabled = true`，`variable_selector` 指向 `sys.files`，`detail = high`）

## 图片上传配置

- **Features**: `file_upload.enabled = true`, `file_upload.image.enabled = true`
- **Vision**: 题目识别节点开启 vision，`variable_selector = ["start_node_id", "sys.files"]`
- **上传方式**: 通过 Service API `/v1/chat-messages` 传递 `files` 参数：
  ```json
  {
    "type": "image",
    "transfer_method": "local_file",
    "upload_file_id": "<file_id>"
  }
  ```
- **图片上传流程**: 先调用 `/v1/files/upload` 获取 `upload_file_id`，再在聊天消息中引用

## Prompt

```
你是一个专业的题目识别助手。从用户上传的图片中准确提取题目内容。

## 输出规则

1. 准确提取题目中的所有文字，不遗漏、不臆造
2. 数学公式用 LaTeX 格式，行内公式用 $...$ 包裹，独立公式块用 $$...$$ 包裹
3. 化学方程式用 LaTeX 格式，行内用 $...$ 包裹，独立块用 $$...$$ 包裹
4. 图片中包含图形时，在 has_figure 标记为 true
5. 多道题在同一图片中，全部提取，用 --- 分隔

## 学科分类

从以下选项中选择：
- 小学数学、小学语文、小学英语
- 初中数学、初中物理、初中化学、初中英语、初中语文
- 高中数学、高中物理、高中化学、高中英语、高中语文、高中生物
- 非学科内容（图片不是学科题目时选择此项）

## 输出格式（严格 JSON）

```json
{
  "subject": "初中数学",
  "question_text": "已知直角三角形两直角边长分别为$3$和$4$，求斜边长。",
  "has_figure": false,
  "question_count": 1
}
```

## 示例

输入：一张写着"解方程 $x^2 - 5x + 6 = 0$"的图片
输出：
```json
{
  "subject": "初中数学",
  "question_text": "解方程 $x^2 - 5x + 6 = 0$",
  "has_figure": false,
  "question_count": 1
}
```
```

## 设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 行内公式格式 | `$...$` 行内 + `$$...$$` 块级 | 符合标准 LaTeX 惯例，Dify 渲染器区分行内/块级；启用 `NEXT_PUBLIC_ENABLE_SINGLE_DOLLAR_LATEX=true` |
| 学科分类 | 枚举 + "非学科内容" | 避免自由文本导致下游无法匹配；用户传非学科图片时能优雅降级 |
| 多题合一 | 整体处理，标注 question_count | MVP 不拆题，降低工程复杂度 |
| Vision | 开启，detail=high | 确保图片中的公式和细节被准确识别 |
| 图片+文字 | 同时支持 | 用户可以上传图片并附文字说明，纯文字题目也支持 |
