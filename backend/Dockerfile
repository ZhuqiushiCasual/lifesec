FROM python:3.12-slim

WORKDIR /app

# 先装依赖，利用 Docker 层缓存（asyncmy 有 cp312 manylinux wheel，无需编译）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# startup.py：等待 DB 就绪（重试）→ 自动建表 → 启动 uvicorn
# DEBUG=0（compose 已设置）时不带热重载
CMD ["python", "startup.py"]
