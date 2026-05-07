# StudyHelper 代码沙箱
# 用于安全执行 AI 生成的 Python 绘图代码（matplotlib 几何图形）
# 安全策略：无网络、只读根文件系统、资源限制、执行超时

FROM python:3.11-slim

# 安装 matplotlib 运行所需的系统库
# python:3.11-slim 不包含这些库，缺少会导致 import matplotlib 报错
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    libfreetype6 \
    libpng16-16 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
RUN pip install --no-cache-dir matplotlib numpy

# 创建非 root 用户运行代码
RUN useradd -m -s /bin/bash sandbox

WORKDIR /tmp/sandbox

USER sandbox
