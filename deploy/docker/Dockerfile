FROM python:3.13-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt .

# 安装Python依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY src/ ./src/
COPY skills/ ./skills/

# 暴露端口
EXPOSE 8000

# 启动命令
CMD ["uvicorn", "src.runtime.api.app:create_app", "--host", "0.0.0.0", "--port", "8000", "--factory"]
