# CI 测试镜像：Linux 上跑 pytest 用，不含打包工具（PyInstaller 打不出 Windows exe）。
# 版本要和 requirements.txt 的 Python 3.13 一致；Windows 官方包仍固定在 3.13.16。
#
# 基础镜像可以换：NAS 直连 registry-1.docker.io 会超时，daemon 里配的加速
# （docker.fnnas.com）对 library 镜像没生效，所以要显式用能匿名访问的镜像源：
#   docker build --build-arg BASE_IMAGE=docker.1panel.live/library/python:3.13-slim ...
ARG BASE_IMAGE=python:3.13-slim
FROM ${BASE_IMAGE}

# fonts-noto-cjk：合成画面测试要中文字体，没有就整批跳过（tests/synth.py 只认出
# Windows msyh 和 Linux Noto 两类路径）。libgl1/libegl1 等是 PySide6 运行库，
# 缺了连 QT_QPA_PLATFORM=offscreen 也起不来。
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
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

# 依赖单独一层：源码用卷挂进来，改代码不用重建镜像
COPY requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

WORKDIR /src

# 自检：镜像能用的话这一步必须过
RUN python -c "import PySide6, cv2, numpy, onnxruntime, rapidocr; print('deps ok')" \
    && python -c "from PIL import ImageFont; ImageFont.truetype('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc', 12); print('cjk ok')"

CMD ["python", "-m", "pytest", "-q"]
