# 第一阶段：构建依赖
FROM python:3.11-alpine AS builder

# 创建非root用户并设置目录权限
RUN addgroup -S appuser && adduser -S appuser -G appuser \
    && mkdir -p /home/appuser/.local \
    && chown -R appuser:appuser /home/appuser
    
# 切换到非特权用户（避免root用户运行容器）
USER appuser
WORKDIR /app
COPY requirements.lock .

# 安装Python依赖到用户目录
RUN pip install --user --no-cache-dir -r requirements.lock \
    -i https://pypi.tuna.tsinghua.edu.cn/simple

# 第二阶段：运行时
FROM python:3.11-alpine

RUN addgroup -S appuser && adduser -S appuser -G appuser \
    && mkdir -p /home/appuser/.local \
    && chown -R appuser:appuser /home/appuser

# 配置阿里云镜像源
RUN sed -i 's/dl-cdn.alpinelinux.org/mirrors.aliyun.com/g' /etc/apk/repositories \
    && apk update \
    && apk add --no-cache curl \
    && rm -rf /var/cache/apk/*

WORKDIR /app

# 复制依赖（确保路径一致）
COPY --from=builder --chown=appuser:appuser /home/appuser/.local /home/appuser/.local
COPY --chown=appuser:appuser . .

ENV PATH="/home/appuser/.local/bin:$PATH" \
    PYTHONPATH="/app" \
    GUNICORN_WORKERS=4

USER appuser
EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=10s \
  CMD curl -fs http://localhost:5000/health || exit 1

CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:5000", "wsgi:app"]