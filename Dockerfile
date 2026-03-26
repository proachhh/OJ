FROM python:3.12-alpine
#支持多架构（x86_64, arm64 等）。
ARG TARGETARCH
ARG TARGETVARIANT

# 设置 Django 环境为生产模式
ENV OJ_ENV production

# 设置 Django 环境为生产模式
WORKDIR /app

COPY ./deploy/requirements.txt /app/deploy/
# BuildKit 的缓存挂载特性，可以在构建过程中复用缓存，加速重复构建（尤其是 apk 和 pip 的缓存）。
# apk add 安装一系列系统依赖（编译器、PostgreSQL 客户端库、图像处理库、supervisor、nginx、curl 等）
# apk del 删除编译工具，释放空间（最终镜像不包含这些编译工具）
RUN --mount=type=cache,target=/etc/apk/cache,id=apk-cahce-$TARGETARCH$TARGETVARIANT-final \
    --mount=type=cache,target=/root/.cache/pip,id=pip-cahce-$TARGETARCH$TARGETVARIANT-final \
    <<EOS
set -ex
apk add gcc libc-dev python3-dev libpq libpq-dev libjpeg-turbo libjpeg-turbo-dev zlib zlib-dev freetype freetype-dev supervisor openssl nginx curl unzip
pip install -r /app/deploy/requirements.txt
apk del gcc libc-dev python3-dev libpq-dev libjpeg-turbo-dev zlib-dev freetype-dev
EOS

# COPY ./ /app/：将构建上下文（即后端项目目录）的所有内容复制到 /app。
COPY ./ /app/
# 复制本目录下的dist文件
COPY ./dist /app/dist
# RUN chmod：设置文件和目录权限，并确保 entrypoint.sh 可执行。
RUN chmod -R u=rwX,go=rX ./ && chmod +x ./deploy/entrypoint.sh

HEALTHCHECK --interval=5s CMD [ "/usr/local/bin/python3", "/app/deploy/health_check.py" ]
EXPOSE 8000
# ENTRYPOINT ["/app/deploy/entrypoint.sh"]：容器启动时运行该脚本，它会启动 supervisor，进而启动 nginx、gunicorn、dramatiq 等进程。
ENTRYPOINT [ "/app/deploy/entrypoint.sh" ]