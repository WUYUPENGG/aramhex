#!/bin/sh
# 在 CI 镜像里跑测试。Jenkins、本机、以后别的 CI 都走这一个脚本，参数只有一份。
#
#   docker/ci/run-tests.sh                 # 跑全部
#   docker/ci/run-tests.sh tests/test_api.py -k foo
#
# 需要先建镜像：docker build -t aramhex-ci:py313 -f docker/ci/Dockerfile .
#
# 说明：
# - 源码用卷挂进去，不在镜像里 copy，改代码不用重建镜像。
# - 容器里没有 passwd 记录，getpass.getuser() 会抛 OSError，所以要给 USER。
# - 报告写到 build/ci/junit.xml，Jenkins 的 junit 步骤收这个文件。
set -eu

IMAGE=${IMAGE:-aramhex-ci:py313}
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
UID_GID=$(id -u):$(id -g)

mkdir -p "$ROOT/build/ci"

# 容器里以调用者身份跑，免得出 root 属主的文件留在 workspace 里
exec docker run --rm \
    -v "$ROOT":/src \
    -w /src \
    -u "$UID_GID" \
    -e HOME=/tmp \
    -e USER=ci \
    -e LOGNAME=ci \
    -e PYTHONUTF8=1 \
    -e PYTHONIOENCODING=utf-8 \
    -e QT_QPA_PLATFORM=offscreen \
    "$IMAGE" \
    python -m pytest -q --junitxml=build/ci/junit.xml "$@"
