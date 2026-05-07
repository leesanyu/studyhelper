#!/bin/bash
# ==================================================================
# StudyHelper 本地开发环境一键部署脚本
# 用法：bash scripts/setup.sh
# ==================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
DIFY_DIR="$PROJECT_DIR/dify"
MC_BIN="$PROJECT_DIR/bin/mc"

echo "========================================="
echo " StudyHelper 本地开发环境部署"
echo "========================================="

# ------------------------------------------------------------------
# 1. 检查 Docker 环境
# ------------------------------------------------------------------
echo ""
echo "[1/6] 检查 Docker 环境..."

if ! command -v docker &> /dev/null; then
    echo "错误：未安装 Docker，请先安装 Docker 24+"
    exit 1
fi

if ! docker info &> /dev/null; then
    echo "错误：Docker 未运行，请先启动 Docker"
    exit 1
fi

DOCKER_VERSION=$(docker version --format '{{.Server.Version}}' 2>/dev/null)
echo "  Docker 版本：$DOCKER_VERSION"

if ! command -v docker compose &> /dev/null; then
    echo "错误：未安装 Docker Compose V2，请先安装"
    exit 1
fi

echo "  Docker Compose 已就绪"

if ! command -v curl &> /dev/null; then
    echo "错误：未安装 curl，请先安装"
    exit 1
fi

echo "  curl 已就绪"

# ------------------------------------------------------------------
# 2. 创建共享 Docker 网络（先于 Dify，Dify 需要加入此网络）
# ------------------------------------------------------------------
echo ""
echo "[2/6] 创建共享网络..."

if ! docker network inspect studyhelper_net &> /dev/null; then
    docker network create studyhelper_net
    echo "  已创建 studyhelper_net 网络"
else
    echo "  studyhelper_net 网络已存在"
fi

# ------------------------------------------------------------------
# 3. 克隆并部署 Dify
# ------------------------------------------------------------------
echo ""
echo "[3/6] 部署 Dify..."

if [ -d "$DIFY_DIR" ]; then
    echo "  Dify 目录已存在，跳过克隆"
    cd "$DIFY_DIR/docker"
else
    echo "  正在克隆 Dify 仓库..."
    git clone --depth 1 https://github.com/langgenius/dify.git "$DIFY_DIR"
    cd "$DIFY_DIR/docker"
fi

# 配置 Dify 环境变量
if [ ! -f .env ]; then
    cp .env.example .env
    echo "  已创建 Dify .env 配置文件"
else
    echo "  Dify .env 已存在，跳过"
fi

# 提示用户配置 Dify 网络
echo ""
echo "  ⚠ 重要：Dify 需要加入 studyhelper_net 网络才能与业务后端通信"
echo "  请在 Dify 的 docker/docker-compose.yaml 中做以下修改："
echo ""
echo "  (1) 在文件底部 networks 部分添加："
echo "      studyhelper_net:"
echo "        external: true"
echo ""
echo "  (2) 在 api 和 worker 服务的 networks 中添加 studyhelper_net："
echo "      networks:"
echo "        - default"
echo "        - studyhelper_net"
echo ""
echo "  注意：我们的业务后端服务名是 backend，Dify 的 api 服务保持原名，不会冲突。"
echo ""
echo "  修改完成后按回车继续..."
read -r

# 启动 Dify（兼容 docker-compose.yaml 和 compose.yaml 两种文件名）
echo "  启动 Dify 服务（首次启动较慢，请耐心等待）..."
if [ -f docker-compose.yaml ]; then
    docker compose --project-name dify -f docker-compose.yaml up -d
elif [ -f compose.yaml ]; then
    docker compose --project-name dify -f compose.yaml up -d
else
    echo "  错误：未找到 Dify 的 compose 文件"
    exit 1
fi

# 等待 Dify 就绪（最多 120 秒）
# 检查 Dify nginx 根路径返回 200 或 302（未初始化时重定向到设置页）
echo "  等待 Dify 就绪..."
for i in $(seq 1 24); do
    HTTP_CODE=$(curl -s -o /dev/null -w '%{http_code}' http://localhost/ 2>/dev/null || echo "000")
    if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "302" ]; then
        echo "  Dify 已就绪 (HTTP $HTTP_CODE)"
        break
    fi
    if [ "$i" -eq 24 ]; then
        echo "  ⚠ Dify 未在 120 秒内就绪，请稍后手动检查 http://localhost"
    else
        echo "  等待中... ($i/24, HTTP $HTTP_CODE)"
        sleep 5
    fi
done

echo "  Dify 管理后台：http://localhost"

# ------------------------------------------------------------------
# 4. 启动业务服务
# ------------------------------------------------------------------
echo ""
echo "[4/6] 启动业务服务..."

cd "$PROJECT_DIR/docker"

# 配置业务服务环境变量
if [ ! -f .env ]; then
    cp .env.example .env
    echo "  已创建 .env 配置文件（请根据需要修改密码和 API Key）"
fi

# 构建 sandbox 镜像（不静默错误）
echo "  构建代码沙箱镜像..."
docker compose --project-name studyhelper build code_sandbox

# 启动基础设施（backend/nginx/code_sandbox 通过 profiles 按需启动）
# 使用 --project-name studyhelper 避免与 Dify 的 compose 项目名冲突
docker compose --project-name studyhelper up -d business_db redis minio

echo "  业务服务启动完成"

# ------------------------------------------------------------------
# 5. 初始化 MinIO Bucket
# ------------------------------------------------------------------
echo ""
echo "[5/6] 初始化 MinIO..."

# 等待 MinIO 就绪
sleep 5

# 从 .env 读取 MinIO 凭证
MINIO_USER=$(grep '^MINIO_ACCESS_KEY=' .env 2>/dev/null | cut -d'=' -f2 || echo "minioadmin")
MINIO_PASS=$(grep '^MINIO_SECRET_KEY=' .env 2>/dev/null | cut -d'=' -f2 || echo "minioadmin")
MINIO_PORT=$(grep '^MINIO_API_PORT=' .env 2>/dev/null | cut -d'=' -f2 || echo "9100")

# 检测系统架构，下载对应版本的 mc
ARCH=$(uname -m)
case $ARCH in
    x86_64|amd64)  MC_ARCH="linux-amd64" ;;
    aarch64|arm64) MC_ARCH="linux-arm64" ;;
    *)             MC_ARCH="linux-amd64" ;;
esac

if [ ! -x "$MC_BIN" ]; then
    echo "  安装 MinIO Client (mc, $MC_ARCH)..."
    mkdir -p "$(dirname "$MC_BIN")"
    if curl -sL "https://dl.min.io/client/mc/release/${MC_ARCH}/mc" -o "$MC_BIN" 2>/dev/null && chmod +x "$MC_BIN"; then
        echo "  mc 安装成功"
    else
        echo "  ⚠ mc 安装失败，请手动创建 MinIO bucket 'studyhelper'"
        MC_BIN=""
    fi
fi

# 创建 bucket
if [ -x "$MC_BIN" ]; then
    if "$MC_BIN" alias set local "http://localhost:${MINIO_PORT}" "$MINIO_USER" "$MINIO_PASS" 2>/dev/null; then
        if "$MC_BIN" ls local/studyhelper >/dev/null 2>&1; then
            echo "  studyhelper bucket 已存在"
        else
            if "$MC_BIN" mb local/studyhelper 2>/dev/null; then
                echo "  已创建 studyhelper bucket"
            else
                echo "  ⚠ bucket 创建失败，请手动创建"
            fi
        fi
    else
        echo "  ⚠ 无法连接 MinIO，请稍后手动创建 bucket"
    fi
fi

# ------------------------------------------------------------------
# 6. 验证 Dify API 连通性
# ------------------------------------------------------------------
echo ""
echo "[6/6] 验证 Dify API 连通性..."

# 查找 Dify compose 文件
DIFY_COMPOSE_FILE=""
if [ -f "$DIFY_DIR/docker/docker-compose.yaml" ]; then
    DIFY_COMPOSE_FILE="$DIFY_DIR/docker/docker-compose.yaml"
elif [ -f "$DIFY_DIR/docker/compose.yaml" ]; then
    DIFY_COMPOSE_FILE="$DIFY_DIR/docker/compose.yaml"
fi

if [ -n "$DIFY_COMPOSE_FILE" ]; then
    API_CONTAINER=$(docker compose --project-name dify -f "$DIFY_COMPOSE_FILE" ps -q api 2>/dev/null || true)
    if [ -n "$API_CONTAINER" ]; then
        # 检查 Dify api 是否已在 studyhelper_net 上
        if docker network inspect studyhelper_net --format '{{range .Containers}}{{.Name}} {{end}}' 2>/dev/null | grep -q "api"; then
            echo "  ✓ Dify API 已在 studyhelper_net 中，后端可通过 http://api:5001 访问"
        else
            echo "  ⚠ Dify API 不在 studyhelper_net 中"
            echo "  请确认已在 Dify 的 docker-compose.yaml 中添加了 studyhelper_net 网络"
            echo "  修改后运行：cd dify/docker && docker compose --project-name dify up -d"
        fi
    else
        echo "  ⚠ Dify API 容器未找到"
        echo "  请确认 Dify 已正常启动：cd dify/docker && docker compose --project-name dify up -d"
    fi
else
    echo "  ⚠ 未找到 Dify compose 文件，跳过验证"
fi

# ------------------------------------------------------------------
# 完成
# ------------------------------------------------------------------
echo ""
echo "========================================="
echo " 部署完成！"
echo "========================================="
echo ""
echo "服务地址："
echo "  Dify 管理后台：  http://localhost"
echo "  MinIO 控制台：   http://localhost:9101"
echo "  业务数据库：     localhost:5433"
echo "  Redis：          localhost:6380"
echo ""
echo "按阶段启动服务："
echo "  基础设施：     docker compose --project-name studyhelper up -d                                    (当前已启动)"
echo "  后端服务：     docker compose --project-name studyhelper --profile backend up -d                  (Sprint 2 后)"
echo "  前端+Nginx：   docker compose --project-name studyhelper --profile frontend up -d                 (Sprint 3 后)"
echo "  全部启动：     docker compose --project-name studyhelper --profile backend --profile frontend up -d"
echo ""
echo "下一步："
echo "  1. 访问 http://localhost 初始化 Dify 管理员账号"
echo "  2. 在 Dify 中配置大模型 API Key"
echo "  3. 在 Dify 中创建 Chatflow 并编写 Prompt"
echo ""
