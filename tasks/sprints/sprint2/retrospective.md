# Sprint 2 Retrospective: 业务后端与数据库搭建

## Keep

- 后端作为唯一集成边界，统一承接 Dify API、文件上传、会话 ID、消息持久化和沙箱产物，降低前端对 Dify 内部字段的耦合。
- 用 `asset_id` 映射 Dify `upload_file_id`，同时保留本地预览资产，为聊天、历史记录和后续 MinIO 切换留下稳定契约。
- Docker 沙箱按一次性容器执行，配合无网络、只读根文件系统、资源限制和超时控制，比在 Dify 内部执行 Python 更符合安全边界。
- 把真实题图索引纳入后端回归入口，继续沿用 Sprint 1 的「真实样例验证」习惯。

## Problem

- 沙箱最初依赖向只读容器写入 `run.py` 和退出后 `get_archive` 读取 tmpfs，真实 Docker live 验证才暴露执行路径不稳定。
- Product Backlog、Sprint Planning、Sprint Review 的状态需要同步更新，否则 Sprint 交付状态容易出现多处不一致。
- Live Dify 回归仍依赖有效 Service API Key 和本地网络配置，默认测试只能覆盖 mock 合同，不能证明当前 Dify App 的线上编排质量。

## Try

- Sprint 3 前端联调前，补一次后端接口契约清单，明确聊天 SSE、上传、会话、沙箱四类接口的字段和错误码。
- 对沙箱安全策略补人工审查清单，重点检查可逃逸的 import、反射、文件写入和资源耗尽路径。
- 在具备稳定 Dify API Key 后，把 live Dify 回归命令纳入手动验收步骤，至少覆盖一张几何题图的直接解答和引导式解答。

## Action Items

| 行动项 | 归属 | 状态 |
|--------|------|------|
| 前端聊天页对接 `/api/v1/chat/completions` SSE 流 | Story 3.2 / 3.3 | 待办 |
| 前端上传题图并使用后端返回的 `asset_id` 发起答疑 | Story 3.5 / 3.6 | 待办 |
| 前端识别 `python:figure` 代码块并调用后端沙箱展示图片 | Story 3.7 / 4.4 | 待办 |
| 使用有效 Dify Service API Key 执行 live 回归验收 | Story 4.5 | 待办 |
| Sprint 3 联调前复核沙箱安全策略 | Story 2.6 后续加固 | 待办 |
