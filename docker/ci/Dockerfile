# CI 测试镜像：Linux 上跑 pytest 用，不含打包工具（PyInstaller 打不出 Windows exe）。
# 版本要和 requirements.txt 的 Python 3.13 一致；Windows 官方包仍固定在 3.13.16。
#
# 源码是 COPY 进来的，不是运行时挂卷。原因：Jenkins 跑在容器里，
# 它的 /var/jenkins_home 在宿主上是另一个路径，`docker run -v /var/jenkins_home/...`
# 到宿主会变成空目录（踩过：pytest「no tests ran」）。COPY 进来就没这个问题。
# 依赖层在源码层之前，改代码只重建最后那层。
ARG BASE_IMAGE=python:3.13-slim
FROM ${BASE_IMAGE}

# 基础镜像可以换：NAS 直连 registry-1.docker.io 会超时，daemon 里配的加速
# （docker.fnnas.com）对 library 镜像没生效。离线做法是把基础镜像 save 成 tar 再 load：
#   docker load -i python-313-slim-amd64.tar.gz
ARG APT_MIRROR=deb.debian.org
ARG PIP_INDEX_URL=https://pypi.org/simple

# fonts-noto-cjk：合成画面测试要中文字体，没有就整批跳过（tests/synth.py 只认出
# Windows msyh 和 Linux Noto 两类路径）。libgl1/libegl1 等是 PySide6 运行库，
# 缺了连 QT_QPA_PLATFORM=offscreen 也起不来。git 是 test_release_data 要用的。
RUN set -eux; \
    for f in /etc/apt/sources.list /etc/apt/sources.list.d/debian.sources; do \
        [ -f "$f" ] && sed -i "s|deb.debian.org|${APT_MIRROR}|g" "$f" || true; \
    done; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        fonts-noto-cjk \
        git \
        libdbus-1-3 \
        libegl1 \
        libfontconfig1 \
        libgl1 \
        libglib2.0-0 \
        libgssapi-krb5-2 \
        libxkbcommon0 \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUTF8=1 \
    PYTHONIOENCODING=utf-8 \
    QT_QPA_PLATFORM=offscreen \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# 依赖单独一层：requirements.txt 没变就不重装
COPY requirements.txt /tmp/requirements.txt
RUN pip install --index-url "${PIP_INDEX_URL}" -r /tmp/requirements.txt

# 自检：镜像能用的话这一步必须过
RUN python -c "import PySide6, cv2, numpy, onnxruntime, rapidocr; print('deps ok')" \
    && python -c "from PIL import ImageFont; ImageFont.truetype('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc', 12); print('cjk ok')"

WORKDIR /src
COPY . /src

CMD ["python", "-m", "pytest", "-q", "--junitxml=build/ci/junit.xml"]
