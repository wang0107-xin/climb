# Python 3.9：与项目 .pyc 字节码版本（cpython-39）保持一致
FROM 192.168.234.120:80/library/python:3.9-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 依赖单独一层：只改代码时不会重新安装依赖，构建更快
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
        -i https://pypi.tuna.tsinghua.edu.cn/simple

# 再拷贝项目代码（.dockerignore 已排除 .env / .venv / instance 等）
COPY . .

# Flask 的 instance_path 默认为 <项目根>/instance，SQLite 相对路径会落在这里
RUN mkdir -p /app/instance

EXPOSE 5000

# 生产用 gunicorn，不要用 wsgi.py 里的 app.run(debug=True)
# wsgi.py 中变量名是 app，所以是 wsgi:app
CMD ["gunicorn", \
     "--bind", "0.0.0.0:5000", \
     "--workers", "2", \
     "--timeout", "60", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "wsgi:app"]
