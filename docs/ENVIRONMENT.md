# 开发和 CI 环境

这份文档记录「在哪台机器、用什么版本、怎么跑」，和 `docs/DEVELOPMENT.md`（讲目录和代码原则）互补。
目标平台仍然是 Windows 10/11 64 位；这里的 Mac 和 NAS 是开发和验证环境，不出正式包。

## 1. 本机（Mac）：跑测试

### 1.1 为什么不用系统 Python

- 系统自带 Python 3.9.6，装不了这些依赖。
- Homebrew 的 `/usr/local/bin/python3.13` 是 **x86_64（Rosetta）** 版。`onnxruntime==1.30.0` 没有
  macOS x86_64 的轮子（x86_64 最后一个是 1.23.2），装到一半会报
  `No matching distribution found for onnxruntime==1.30.0`。
- 所以要一个 **arm64 的 Python 3.13**。用 uv 装最省事，不碰 Homebrew 和系统 Python：

```bash
cd ~/project/aramhex
uv venv --python 3.13 .venv        # 得到 CPython 3.13.3 arm64
uv pip install --python .venv/bin/python -r requirements.txt
```

> uv 默认缓存目录 `~/.cache/uv` 里有些文件是 root 属主（以前用 sudo 跑过 uv），
> 会报 `Permission denied`。换一个缓存目录即可：`export UV_CACHE_DIR=$HOME/.cache/uv-wuyupeng`。

### 1.2 跑测试

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
```

2026-11-27 在 macOS 26.6.2（arm64）上的结果：

```
1254 passed, 24 skipped in 103.42s
```

24 个跳过分两类，都不是环境没配好：

| 数量 | 原因 |
|---|---|
| 18 | 只能在 Windows 上跑：`test_patch`（PowerShell 替换脚本）9、`test_review_115_regressions` 5、`test_single_instance`、`test_crashlog`、`test_diag_logs_112`、`test_package`（要 PowerShell 7） |
| 6 | `test_augment_items` 里 `test_destiny_overlay_renders_only_requested_statistics` 依赖微软雅黑的**整数**字体度量，见 1.3 |

### 1.3 两个已经踩过的坑

**合成画面测试会整批跳过。** `tests/synth.py` 原来只找 Windows 的 `msyh.ttc` 和 Linux 的 Noto CJK，
macOS 上一个都找不到，`fonts_available()` 返回 False，8 个真 OCR 的合成测试全跳过（跳过数 36）。
现在补了 macOS 的两个字体路径（`Hiragino Sans GB.ttc`、`Arial Unicode.ttf`），8 个测试都能跑，全过。

**浮窗提示文字会被截断成「胜率 57.0% · +5…」。** `lolhex/ui/overlay.py` 的 `_paint_item_hint` 里
`stat_w = min(fm.horizontalAdvance(stat), text_w)`，而 `_item_hint_rect` 算出来的宽度让 `text_w`
正好等于文字宽度，于是 `elidedText(stat, stat_w)` 在等宽时按「放不下」处理。
Windows 的微软雅黑在 9pt 下是整数度量，`advance == stat_w` 且不大于，所以不截；
macOS/Linux 的回退字体度量带小数，就截了。**这是 Windows 上看不到的潜在问题**：
一旦换字体或改 DPI 让度量变成小数，提示会缺字。修法是给 `stat_w` 留 1~2 px 余量（还没改，属于界面重构那条线）。
在修之前，这个测试加了 `needs_windows_font` 标记，非 Windows 跳过，Windows CI 照常跑。

## 2. NAS：CI（Jenkins + Docker）

### 2.1 机器

| 项 | 值 |
|---|---|
| 地址 | `192.168.31.159`（局域网），SSH 用户 `wuyupeng123`，密钥 `~/.ssh/jenkins_agent` |
| 系统 | 飞牛 fnOS，Debian 12 bookworm，x86_64，16 核 / 27G 内存 / 根分区 63G（已用 16G） |
| Docker | 28.5.2，data-root `/vol1/docker`，镜像加速 `https://docker.fnnas.com` |
| Jenkins | 容器 `jenkins`，`jenkins/jenkins:2.568.3-lts`，端口 8080，JENKINS_HOME 在 `/vol2/@appdata/1Panel/1panel/apps/jenkins/jenkins/data`，挂了 `/var/run/docker.sock` 和宿主 `/usr/bin/docker` |
| GitLab | 容器 `gitlab`，`192.168.31.159:9980`（SSH 2221），用作备份和打包用的源码仓库 |

注意：NAS 上 `wuyupeng123` 不在 docker 组，`docker ps` 要 sudo 而 sudo 要密码。
**用 Docker 的是 Jenkins 容器**（容器内是 root，且有 socket），不是登录用户。

### 2.2 网络：为什么源码不走 GitHub

从 NAS 实测（2026-11-27）：

| 目标 | 结果 |
|---|---|
| `github.com` | 8s 只下来 350KB |
| `codeload.github.com` 仓库 tarball | 120s 只下来 2.1MB，约 17KB/s |
| `pypi.org` / `pypi.tuna.tsinghua.edu.cn` | 正常，2.1s / 1.2s |
| `registry-1.docker.io` | 直连超时，但 daemon 配了 `docker.fnnas.com` 加速，拉基础镜像走这个 |
| NAS 上的 mihomo（`mixed-port: 6000`） | 国内站正常，**GitHub 仍走直连**，等于没代理 |

所以 CI 的源码从**局域网**拿：Mac 推到 NAS 的 GitLab，Jenkins 从 GitLab clone（秒级）。

### 2.3 CI 怎么跑

流水线文件是仓库根目录的 `Jenkinsfile`，实际干活的是两个文件：

- `docker/ci/Dockerfile`：`python:3.13-slim` + `fonts-noto-cjk` + PySide6 需要的运行库 +
  `git`（`test_release_data` 要调 git）+ `requirements.txt`。依赖单独一层，改源码不用重建镜像。
- `docker/ci/run-tests.sh`：`docker run` 的所有参数（挂源码、`-u $(id -u):$(id -g)`、
  `USER=ci`、`QT_QPA_PLATFORM=offscreen`、`--junitxml=build/ci/junit.xml`）都收在这一个文件里，
  Jenkins、本机、以后的 CI 都用它，参数只有一份。

> `USER=ci` 不能省：容器里没有 passwd 记录，`getpass.getuser()` 抛 `OSError: No username set`，
> `test_run_smoke::test_run_starts` 会红。

本机也能跑同一套（验证镜像用）：

```bash
docker build -t aramhex-ci:py313 -f docker/ci/Dockerfile .
docker/ci/run-tests.sh              # 等价于 NAS 上 Jenkins 干的事
```

2026-11-27 在 `linux/amd64` 容器里的结果：`1254 passed, 24 skipped`，和 Mac 一致
（同一批 Windows 测试跳过）。

### 2.4 Jenkins 作业

| 项 | 值 |
|---|---|
| 类型 | Pipeline script from SCM |
| 仓库 | `http://192.168.31.159:9980/<你的命名空间>/aramhex.git`，凭据用现成的 `gitlab-http-creds` |
| 分支 | `main` |
| 脚本路径 | `Jenkinsfile` |
| 触发 | GitLab push（`gitlab-plugin` 已装），或定时轮询 |
| 产物 | `build/ci/junit.xml`（测试报告）、构建日志 |

流水线只做三件事：自检 docker → 构建测试镜像（有 layer 缓存）→ 跑 `docker/ci/run-tests.sh`，
然后把 junit 报告收进 Jenkins。

### 2.5 NAS 出不了 Windows 安装包

`packaging/` 下的脚本用 PyInstaller 和 Inno Setup，只能在 Windows 上跑；
NAS 是 Linux，最多用 Wine 折腾，不值得。正式包仍然走
`.github/workflows/release.yml`（`windows-latest`）。
游戏内效果（三选一识别、浮窗盖在游戏上）也只能在装了国服客户端的 Windows 上验。

## 3. 和 GitHub Actions 的分工

| 环境 | 触发 | 跑什么 | 出什么 |
|---|---|---|---|
| GitHub Actions `ci.yml` | push main / PR | Windows 全量测试（含 18 个 Windows-only） | 无 |
| NAS Jenkins `aramhex` | push 到 GitLab | Linux 全量测试（18 个 Windows-only 跳过） | junit 报告 |
| GitHub Actions `release.yml` | 推 `v*` 标签 | 版本号核对、资料检查、测试 | **没有打包步骤**（1.3.0 起官方包在别处打） |

要自己出安装包，得按 `docs/HANDOFF.md` 第 9 节的顺序来：先补标签，再改 `release.yml`。
