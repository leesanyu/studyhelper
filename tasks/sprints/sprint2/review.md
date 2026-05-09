# Sprint 2 Review：业务后端与数据库搭建

## 验收结论

Sprint 2 后端能力已完成 mock 验收，包含 FastAPI 基础工程、数据库模型与 migration、Dify 中转、图片上传资产闭环、会话管理、Docker Python 绘图沙箱和核心答疑回归入口。

Live Dify 回归已用本地 Dify App Service API Key 手动执行通过；默认测试仍不自动执行，需要显式提供有效密钥并开启环境变量。

## 已完成 Story

| Story | 验收结果 |
|-------|----------|
| Story 2.1：初始化 FastAPI 工程 | 通过 |
| Story 2.2：设计并创建 PostgreSQL 数据库表 | 通过 |
| Story 2.3：对接 Dify API 和聊天 SSE | 通过 |
| Story 2.4：图片上传代理和资产记录 | 通过 |
| Story 2.5：会话管理和消息历史 | 通过 |
| Story 2.6：Docker Python 绘图沙箱 | 通过 |
| Story 4.5：核心答疑回归集 | mock 通过，live Dify 手动通过 |

## 验收命令

后端完整 mock 测试：

```bash
PYTHONPATH=/tmp/studyhelper-pydeps:backend python3 -m pytest backend/tests -q
```

最新结果：

```text
37 passed, 2 skipped
```

沙箱 Docker live 测试：

```bash
RUN_DOCKER_SANDBOX_LIVE=1 \
PYTHONPATH=/tmp/studyhelper-pydeps:backend \
python3 -m pytest backend/tests/test_sandbox_live.py -q
```

最新结果：

```text
1 passed
```

Dify live 回归入口：

```bash
RUN_LIVE_DIFY_REGRESSION=1 \
DIFY_API_URL=http://localhost \
DIFY_API_KEY=<service-api-key> \
PYTHONPATH=/tmp/studyhelper-pydeps:backend \
python3 -m pytest backend/tests/test_regression_chatflow_modes.py::test_live_dify_chatflow_regression_entrypoint -q
```

最新结果：

```text
1 passed
```

该命令默认跳过，只有显式设置 `RUN_LIVE_DIFY_REGRESSION=1` 且提供有效 `DIFY_API_KEY` 时执行。当前本地 Dify 通过 nginx 暴露，`DIFY_API_URL` 使用 `http://localhost`。

迁移 SQL 生成检查：

```bash
PYTHONPATH=/tmp/studyhelper-pydeps:backend python3 -m alembic -c backend/alembic.ini upgrade head --sql
```

格式检查：

```bash
git diff --check
```

## 关键验证点

1. 图片只通过上传代理进入 Dify，后端保存 `asset_id`、`dify_file_id` 和预览资产。
2. 聊天请求使用后端 `asset_id` 映射 Dify `upload_file_id`，不要求前端直接传 Dify 文件 ID。
3. `current_question/current_diagram/current_knowledge` 可在新题目时更新到会话，继续追问和直接解答复用上下文。
4. 用户消息、AI 消息、Dify `conversation_id/message_id`、知识点标签和 `user_tags_history` 已持久化。
5. Python 绘图沙箱使用 Docker 一次性容器、只读根文件系统、无网络、资源限制和超时控制；生成 PNG 后写入本地对象目录并记录 `assets`。

## 产品待办同步

已将 `tasks/product_backlog.md` 中 Story 2.1 - 2.6 和 Story 4.5 标记为已完成，保持 Product Backlog、Sprint Planning 和 Sprint Review 三处状态一致。

## 遗留风险

1. Live Dify 回归依赖有效 Service API Key 和本地 Dify 网络配置，仍未纳入默认测试。
2. 当前对象存储实现为本地目录，MinIO 适配边界已保留，但未切换为默认实现。
3. 沙箱安全策略已覆盖高风险 import、超时和输出校验，但仍应在 Sprint 3 联调前补一次人工安全审查。
