# StudyHelper 后端本地启动

## 环境前置

1. 安装 Docker，并确保本机可以访问 Docker socket。
2. 创建共享网络：

   ```bash
   docker network create studyhelper_net
   ```

   如果网络已存在，Docker 会提示重复创建，可以忽略。

3. 确认 `docker/.env` 中的 `DIFY_API_KEY` 已替换为 Sprint 1 Dify App 的 Service API Key。默认值只适合 mock 测试。

## 启动业务依赖

在仓库根目录执行：

```bash
docker compose -f docker/docker-compose.yml --profile backend up -d business_db redis minio
```

业务依赖默认端口：

| 服务 | 本地端口 | 用途 |
|------|----------|------|
| PostgreSQL | `5433` | 业务表 |
| Redis | `6380` | 缓存和后续 SSE 状态 |
| MinIO | `9100` / `9101` | 图片和沙箱产物 |

## 数据库迁移

在 `backend` 目录安装依赖后执行：

```bash
alembic -c alembic.ini upgrade head
```

如果只想检查迁移 SQL，不连接数据库：

```bash
alembic -c alembic.ini upgrade head --sql
```

## 启动 API

在 `backend` 目录执行：

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

健康检查：

```bash
curl http://localhost:8000/health
curl http://localhost:8000/api/v1/health
```

## 沙箱镜像

构建 Python 绘图沙箱镜像：

```bash
docker build -t studyhelper-code-sandbox:latest docker/sandbox
```

单元测试默认使用内存沙箱服务，不依赖 Docker。接入真实 Docker 执行器时，后端容器需要挂载 `/var/run/docker.sock`，并通过 `SANDBOX_IMAGE` 指定镜像名。

## 测试

本地测试命令：

```bash
PYTHONPATH=backend pytest backend/tests -q
```

当前测试集覆盖健康检查、数据库模型、Dify mock 客户端、聊天 SSE、文件上传、会话接口、沙箱接口和题图回归索引。
