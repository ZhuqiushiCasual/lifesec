FROM python:3.12-slim

WORKDIR /app

# pip 源：默认走阿里云镜像（pypi.org 在本机和这台服务器上都很慢/会超时）。
# 要换源不用改本文件，构建时覆盖即可：docker build --build-arg PIP_INDEX_URL=...
# （compose 里传了 build.args.PIP_INDEX_URL 的话以它为准）
ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple

# 先装依赖，利用 Docker 层缓存（asyncmy 有 cp312 manylinux wheel，无需编译）
COPY requirements.txt .
RUN pip install --no-cache-dir -i "${PIP_INDEX_URL}" -r requirements.txt

COPY . .

EXPOSE 8000

# startup.py：等待 DB 就绪（重试）→ 自动建表 → 启动 uvicorn
# DEBUG=0（compose 已设置）时不带热重载
CMD ["python", "startup.py"]
