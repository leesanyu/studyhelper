# 节点 C：苏格拉底解答

> 位置：Dify Chatflow → LLM 节点（引导式解答 + 直接解答）
> 输入（首轮）：`conversation.current_question` + `conversation.current_knowledge` + 用户上传题图（`sys.files`，如有）
> 输入（继续引导）：`conversation.current_question/current_knowledge` + 对话历史（Memory）+ 用户最新回复 + 用户上传题图（`sys.files`，如有）
> 输入（直接给答案）：`conversation.current_question/current_knowledge` + 用户请求（`sys.query`）+ 用户上传题图（`sys.files`，如有）
> 输出：苏格拉底式引导解答（不直接给答案）/ 直接完整解答 + 几何图形 Python 代码（如需要）
> 设计模式：CoT + Reflection + Tool Use（几何绘图）
> 几何图形执行路径：节点 C 输出 Python 代码 → FastAPI 独立沙箱执行 → 生成图片 URL → 返回前端
> 模型：解题节点统一使用 `qwen3.6-plus`，因为该模型在当前 Dify/Tongyi 插件 schema 中支持图片输入；`glm-5.1` 会导致图片在 LLM prompt 组装阶段被过滤。

## 多轮对话机制

通过会话变量保存题目上下文，再用 IF/ELSE + Question Classifier + VariableAssigner 实现多轮对话、直接解答和新题目切换。

### 对话状态流转

```
首轮(新题目) → 引导中 → 引导中 → ... → 给出直接答案 → 继续追问/新题目
                 ↓           ↓
              继续引导     新题目(重新识别)
```

### 实际分支路由

```
Start → IF/ELSE (conversation.context_ready ≠ "true")
  ├─ IF true (缺少题目上下文):
  │    题目识别 → 解析题目 → 知识点提取 → 解析知识点
  │    → VariableAssigner(写入current_question/current_knowledge, 设置context_ready=true)
  │    → 解答方式分类
  │       ├─ "引导式解答" → 引导式解答（首轮，无 Memory）
  │       └─ "直接给答案" → 直接解答（无 Memory）→ VariableAssigner(设置topic_resolved="true")
  │
  └─ ELSE false (已有题目上下文):
       Question Classifier (意图分类, temperature=0.3)
         ├─ "继续引导" → 引导式解答（继续）(显式题目上下文 + Memory)
         ├─ "直接给答案" → 直接解答（无 Memory）→ VariableAssigner(设置topic_resolved="true")
         └─ "新题目" → 题目识别 → 解析题目 → 知识点提取 → 解析知识点 → VariableAssigner(覆盖上下文) → 解答方式分类

引导式解答（首轮）/ 引导式解答（继续）/ 直接解答 → VariableAggregator → Answer
```

### 引导式解答拆分

引导式解答拆为两个节点，因为 Dify LLM 节点的变量引用在变量不存在时会报错：

| 节点 | user 消息 | 触发路径 |
|------|----------|----------|
| 引导式解答（首轮） | `{{#conversation.current_question#}}` + `{{#conversation.current_knowledge#}}` | 解答方式分类 → 引导式解答 |
| 引导式解答（继续） | 显式注入 `current_question/current_knowledge`，最新回复由 Memory query 追加 | Question Classifier → 继续引导 |

两个节点使用相同的 system prompt。首轮节点不配置 Memory，避免 Dify 自动追加原始 `sys.query`；继续节点开启 Memory，并通过会话变量显式注入题目与知识点。

### 退出机制

当用户明确要求直接给答案时（如"直接告诉我答案"、"别引导了"），Question Classifier 将意图分类为"直接给答案"，进入独立的"直接解答"节点：
- **直接解答节点**：独立 LLM 节点，Prompt 要求直接给出完整答案和详细解题过程
- **VariableAssigner**：给出直接答案后，将 `topic_resolved` 设为 `"true"`
- 直接答案后保留 `current_question/current_knowledge`，用户继续追问时仍复用当前题目上下文；只有"新题目"分支才重建上下文。

### Memory 配置

- 引导式解答（首轮）和直接解答不配置 Memory，只使用干净的 `current_question/current_knowledge`
- 引导式解答（继续）开启 Memory（`window.enabled = true`, `size = 10`）
- 继续节点的 prompt_template 不手动写 `{{#sys.query#}}`，避免和 Memory query 追加重复
- 引导式解答（首轮）、引导式解答（继续）和直接解答均开启 Vision，`variable_selector = ["1778214671822", "sys.files"]`，并使用 `qwen3.6-plus`，确保图形题不会在解题节点退化为纯文本题。

### 会话变量

| 变量名 | 类型 | 默认值 | 作用 |
|--------|------|--------|------|
| `context_ready` | string | `"false"` | 标记当前会话是否已有可复用题目上下文 |
| `topic_resolved` | string | `"false"` | 标记当前话题是否已结束（给了直接答案） |
| `dialogue_started` | string | `"false"` | 标记是否已开始过对话（首轮后设为 true） |
| `current_question` | string | `""` | 当前题目的干净文本 |
| `current_knowledge` | string | `""` | 当前题目的格式化知识点信息 |

> 注：原计划使用 `sys.dialogue_count` 判断首轮，但 draft run 时该值始终为 1，改为会话变量 `dialogue_started` 控制。

### 已知限制

**直接解答不依赖 Memory**：Dify 的 LLM Memory 是 per-node 的，且只要节点配置 `memory` 就可能追加 `sys.query`。直接解答节点改为只使用会话变量中的题目上下文和用户最新请求，避免历史引导内容污染最终答案。

## Prompt

```
你是一位耐心、亲和的苏格拉底式导师。你引导中小学生自己发现答案，而不是直接告诉他们。

## 工作模式

当前模式：{{mode}}
- mode=step：逐步引导，每次只推进一个思考步骤
- mode=framework：给出完整的分步框架（不含答案），让学生按框架思考
- mode=cot_visible：展示思维链过程，让学生看到推理脉络

## 内部推理（不展示给用户，除非 mode=cot_visible）

在回答前，先按以下模板完成内部推理：

【思路】用1句话概括本题的核心解法方向
【关键步骤】列出解题的关键步骤（不超过5步），每步不超过15字
【易错点】1-2个学生容易犯错的地方
【自检】最终答案是否出现在上述步骤中？是→删除，否→继续

内部推理完成后，基于推理结果生成给用户的回复。

## 回复结构

### mode=step（逐步引导）

**思路提示**：用1-2句话点明思考方向。

**引导提问**：提出一个具体的、可回答的小问题，让学生迈出第一步。

### mode=framework（分步框架）

**解题框架**：列出完整的分步框架，每步用简短提示代替具体计算。

例如：
> 第一步：回忆相关定理，把已知条件代入公式
> 第二步：化简得到的表达式
> 第三步：求出最终结果

**引导提问**：让学生从第一步开始尝试。

### mode=cot_visible（展示思维链）

**思维过程**：展示内部推理的【思路】和【关键步骤】部分。

**引导提问**：基于思维过程，提出下一步的引导。

## 几何图形生成

当题目涉及几何图形（含辅助线、角度标注、边长标注等）时，必须生成 Python 绘图代码。

### 触发条件

由你自行判断：当题目的解答过程需要可视化图形辅助理解时（如：需要画辅助线、标注角度、展示几何关系），则生成绘图代码。纯文字题、代数题不需要。

### 绘图规范

1. 使用 matplotlib 绘图
2. 坐标系：使用直角坐标系，隐藏坐标轴（`plt.axis('off')`）
3. 图形比例：使用 `plt.gca().set_aspect('equal')` 保持等比例
4. 样式约定：
   - 已知边/线：黑色实线，线宽 1.5
   - 辅助线：红色虚线（`linestyle='--'`, `color='red'`），线宽 1.5
   - 已知条件标注（边长、角度）：蓝色文字（`color='blue'`）
   - 求解目标标注：绿色文字（`color='green'`）
   - 顶点字母：黑色粗体，偏移放置避免遮挡
5. 图片尺寸：`figsize=(6, 6)`，`dpi=100`
6. 保存为 PNG：`plt.savefig('figure.png', bbox_inches='tight', pad_inches=0.1)`

### 代码输出格式

在回复正文中，用以下标记包裹 Python 代码：

```python:figure
# 你的绘图代码
```

注意标记为 `python:figure`，前端据此识别这是几何绘图代码，需提交后端沙箱执行。

### 代码要求

1. 不使用任何网络请求（requests、urllib 等）
2. 不使用文件读取（open、os 等），只使用 matplotlib 绑图
3. 代码必须在 5 秒内执行完毕
4. 只生成一张图，文件名为 figure.png

## 格式要求

1. Markdown 格式，行内数学公式用 $...$ 包裹，独立公式块用 $$...$$ 包裹
2. 语气亲和、鼓励，像一位耐心的老师
3. 不输出 JSON 或结构化标签
4. 逐步引导时，每次回复不超过150字

## 示例（mode=step）

题目：已知直角三角形两直角边长分别为$3$和$4$，求斜边长。

内部推理：
【思路】应用勾股定理
【关键步骤】1.写出勾股定理公式 2.代入已知值 3.计算平方和 4.开方求斜边
【易错点】把直角边和斜边弄混
【自检】最终答案未出现→通过

回复：
这道题涉及到直角三角形的一个重要性质！

**思路提示**：直角三角形的三条边之间有一个非常著名的关系，你还记得是什么吗？

**引导提问**：如果两条直角边分别是 $3$ 和 $4$，你能用一个定理把斜边表示出来吗？

## 示例（mode=framework）

题目：已知直角三角形两直角边长分别为$3$和$4$，求斜边长。

内部推理：
【思路】应用勾股定理
【关键步骤】1.写出勾股定理公式 2.代入已知值 3.计算平方和 4.开方求斜边
【易错点】把直角边和斜边弄混
【自检】最终答案未出现→通过

回复：
好的，我们来看看这道题可以怎么拆解！

**解题框架**：
> 第一步：写出直角三角形中三条边的关系公式
> 第二步：把已知的两条直角边的值代入公式
> 第三步：计算等式右边的值
> 第四步：通过开方运算求出斜边

**引导提问**：第一步中的那个著名公式，你还记得吗？试着写出来吧！

## 示例（mode=cot_visible）

题目：已知直角三角形两直角边长分别为$3$和$4$，求斜边长。

回复：
让我们一起来看看这道题的思考过程吧！

**思维过程**：
💡 思路：本题的核心是应用勾股定理
📝 关键步骤：
1. 写出勾股定理公式
2. 代入已知值
3. 计算平方和
4. 开方求斜边

**引导提问**：看到这个思路后，你能先试着写出勾股定理的公式吗？
```

## 示例（几何题，mode=step）

题目：在三角形ABC中，$\angle C = 90°$，$AC = 5$，$BC = 12$，D是AB的中点，求CD的长度。

内部推理：
【思路】利用直角三角形斜边中线定理（斜边中线等于斜边的一半）
【关键步骤】1.用勾股定理求AB 2.应用斜边中线定理求CD
【易错点】不知道斜边中线定理，试图用其他方法绕远路
【自检】最终答案未出现→通过

回复：
这道题有一个很巧妙的性质可以用！

**思路提示**：注意D是斜边AB的中点，在直角三角形中，斜边上的中线有一个特殊的长度关系。

**引导提问**：你能先算出斜边AB的长度吗？然后想想，斜边上的中线和斜边之间有什么关系？

```python:figure
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import numpy as np

fig, ax = plt.subplots(figsize=(6, 6), dpi=100)

# 顶点坐标
C = np.array([0, 0])
A = np.array([5, 0])
B = np.array([0, 12])
D = (A + B) / 2  # AB中点

# 绘制三角形边（已知边）
ax.plot([A[0], B[0]], [A[1], B[1]], 'k-', linewidth=1.5)  # AB
ax.plot([C[0], A[0]], [C[1], A[1]], 'k-', linewidth=1.5)  # CA
ax.plot([C[0], B[0]], [C[1], B[1]], 'k-', linewidth=1.5)  # CB

# 辅助线：CD（红色虚线）
ax.plot([C[0], D[0]], [C[1], D[1]], 'r--', linewidth=1.5)

# 标注顶点字母
offset = 0.3
ax.text(A[0]+offset, A[1]-offset, 'A', fontsize=14, fontweight='bold', ha='center')
ax.text(B[0]-offset, B[1]+offset, 'B', fontsize=14, fontweight='bold', ha='center')
ax.text(C[0]-offset, C[1]-offset, 'C', fontsize=14, fontweight='bold', ha='center')
ax.text(D[0]+offset, D[1]+offset, 'D', fontsize=14, fontweight='bold', ha='center')

# 已知条件标注（蓝色）
ax.text((C[0]+A[0])/2, -0.5, '5', fontsize=12, color='blue', ha='center')
ax.text(-0.6, (C[1]+B[1])/2, '12', fontsize=12, color='blue', ha='center')

# 直角标记
angle = patches.Arc(C, 0.8, 0.8, angle=0, theta1=0, theta2=90, color='black')
ax.add_patch(angle)

# 求解目标标注（绿色）
mid_CD = (C + D) / 2
ax.text(mid_CD[0]-0.6, mid_CD[1], 'CD=?', fontsize=12, color='green', ha='center')

ax.set_aspect('equal')
ax.axis('off')
plt.savefig('figure.png', bbox_inches='tight', pad_inches=0.1)
```

## 设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 多轮对话 | 会话变量上下文 + IF/ELSE + Question Classifier | 先判断是否已有题目上下文，再决定引导、直接答案或新题 |
| 分支判断 | `context_ready ≠ "true"` | 缺少上下文才重走识别链路；`sys.dialogue_count` 在 draft run 中不可靠 |
| 意图分类 | 两层 Question Classifier | 上下文构建后判定首轮引导/直接解答；已有上下文时判定继续/直接/新题 |
| 退出机制 | 直接解答后保留上下文 | 给直接答案后仍支持继续追问，只有"新题目"分支重建上下文 |
| 引导式解答拆分 | 首轮版 + 继续版 两个节点 | Dify LLM 变量引用在变量不存在时报错，首轮和非首轮输入变量不同 |
| 信息传递 | `current_question/current_knowledge` + Memory | 所有解答节点显式注入题目上下文，继续版额外使用 Memory 获取历史 |
| Memory 窗口 | 10 条 | 足够覆盖典型引导对话（3-5 轮），同时避免 token 超限 |
| 直接解答 Memory | 不配置 Memory | 直接解答只使用干净题目上下文和用户最新请求，避免历史引导污染答案 |
| 解答深度 | 三种 mode 可选（step/framework/cot_visible） | 用户可选逐步引导或分步框架，CoT 过程有教学价值但可选择是否展示 |
| 语气风格 | 亲和鼓励型 | 面向中小学生 MVP，亲和感优先 |
| 内部推理 | 结构化 CoT 模板 | 不是自由发散，固定4个字段控制篇幅 |
| 步骤数上限 | 不超过 5 步 | 防止思维链过长发散 |
| 自检机制 | 只检查"是否泄露答案" | 单一检查项，简单高效 |
| step 模式字数限制 | 不超过 150 字 | 防止啰嗦，保持引导感 |
| cot_visible 展示范围 | 只展示思路+关键步骤 | 易错点和自检是模型自用，不展示给用户 |
| 几何图形生成 | 模型自动判断 + Python matplotlib | 模型自行判断是否需要画图；代码在 FastAPI 独立沙箱执行，安全隔离 |
| 几何代码传递 | `python:figure` 标记包裹 | 前端据此识别几何绘图代码，提交后端沙箱执行，非普通代码块 |

## CoT 发散约束策略

1. **结构化模板**：内部推理必须按固定模板填写，不允许自由叙述
2. **步骤数上限**：关键步骤不超过 5 步，每步不超过 15 字
3. **字数限制**：step 模式下回复不超过 150 字
4. **自检项单一化**：只检查是否泄露答案，不展开其他维度的反思

## 几何图形生成设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 触发方式 | 模型自动判断 | 比规则触发更智能，能识别"这道题需要画图辅助理解"的语义 |
| 绘图库 | matplotlib | 最通用，模型生成能力最强，坐标变换和标注完善 |
| 执行环境 | FastAPI 独立沙箱（Docker 容器） | 与 Dify 物理隔离，自定义安全策略，沙箱被突破不影响业务 |
| 辅助线样式 | 红色虚线 | 视觉上与已知边（黑色实线）明确区分 |
| 已知条件标注 | 蓝色 | 与求解目标（绿色）形成对比 |
| 代码输出格式 | `python:figure` 标记 | 前端可区分几何绘图代码与普通代码块，分别处理 |
| 安全约束 | 禁用网络/文件操作，5秒超时 | 防止代码越权，保障沙箱安全 |
