#!/bin/sh
# 建镜像 + 跑测试。Jenkins、本机、以后别的 CI 都走这一个脚本，参数只有一份。
#
#   docker/ci/run-tests.sh                 # 跑全部
#   docker/ci/run-tests.sh tests/test_api.py -k foo
#
# 没有用 -v 挂源码，而是把源码 COPY 进镜像（见 Dockerfile 顶部说明）：
# Jenkins 在容器里跑，它的 /var/jenkins_home 在宿主上是另一个路径，挂卷会挂成空目录。
# 报告从容器里 docker cp 出来，写到 build/ci/junit.xml。
#
# 环境变量：
#   IMAGE       镜像名，默认 aramhex-ci:py313
#   APT_MIRROR  apt 源，默认 deb.debian.org；国内建议 mirrors.tuna.tsinghua.edu.cn
#   PIP_INDEX   pip 源，默认 pypi.org；国内建议 https://pypi.tuna.tsinghua.edu.cn/simple
set -eu

IMAGE=${IMAGE:-aramhex-ci:py313}
APT_MIRROR=${APT_MIRROR:-deb.debian.org}
PIP_INDEX=${PIP_INDEX:-https://pypi.org/simple}
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
NAME=aramhex-ci-run
REPORT=build/ci/junit.xml

mkdir -p "$ROOT/build/ci"

echo "== 建镜像 ${IMAGE}（源：${APT_MIRROR} / ${PIP_INDEX}）"
docker build \
    --build-arg "APT_MIRROR=$APT_MIRROR" \
    --build-arg "PIP_INDEX_URL=$PIP_INDEX" \
    -t "$IMAGE" \
    -f "$ROOT/docker/ci/Dockerfile" \
    "$ROOT"

docker rm -f "$NAME" >/dev/null 2>&1 || true

set +e
docker run --name "$NAME" "$IMAGE" python -m pytest -q --junitxml="$REPORT" "$@"
code=$?
set -e

if docker cp "$NAME:/src/$REPORT" "$ROOT/$REPORT" 2>/dev/null; then
    echo "== 测试报告：${REPORT}"
else
    echo "== 没有拿到测试报告（测试可能没跑到收集阶段也可能是启动就失败）"
fi
docker rm -f "$NAME" >/dev/null 2>&1 || true

exit "$code"
