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
| `registry-1.docker.io` | 直连超时；daemon 配的 `docker.fnnas.com` 也没跑通，基础镜像只能离线搬（见 2.4 ③） |
| NAS 上的 mihomo（`mixed-port: 6000`） | 国内站正常，**GitHub 仍走直连**，等于没代理 |

所以 CI 的源码从**局域网**拿：Mac 推到 NAS 的 GitLab，Jenkins 从 GitLab clone（秒级）。

### 2.3 CI 怎么跑

流水线文件是仓库根目录的 `Jenkinsfile`，实际干活的是两个文件：

- `docker/ci/Dockerfile`：`python:3.13-slim` + `fonts-noto-cjk` + PySide6 运行库 +
  `git`（`test_release_data` 要调 git）+ `requirements.txt`，最后把源码 `COPY` 进去。
- `docker/ci/run-tests.sh`：建镜像、跑测试、把 `build/ci/junit.xml` 从容器里 `docker cp` 出来。
  Jenkins、本机、以后的 CI 都用它，参数只有一份。

本机也能跑同一套：

```bash
docker/ci/run-tests.sh                          # 和 NAS 上 Jenkins 干的事一样
APT_MIRROR=mirrors.tuna.tsinghua.edu.cn \
PIP_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple docker/ci/run-tests.sh   # 国内网络
```

实测：`1254 passed, 24 skipped`，和 Mac 上一模一样（同一批 Windows 测试跳过）。

### 2.4 踩过的四个坑（都已解决，改之前先看这里）

**① `agent any` 会被派到 Mac 上。** NAS 的 Jenkins 挂了一个 `mac-agent` 节点（就是这台 Mac，
SSH 到 192.168.31.43），`agent any` 会挑它。`Jenkinsfile` 里必须写 `agent { label 'built-in' }`。

**② `docker run -v 源码目录` 会挂成空目录。** Jenkins 跑在容器里，它的 `/var/jenkins_home`
在宿主上是 `/vol2/@appdata/1Panel/1panel/apps/jenkins/jenkins/data`。docker 客户端把
`/var/jenkins_home/workspace/...` 交给宿主的 daemon，宿主管这个路径叫别的名字，于是挂了个空目录，
pytest 报 `no tests ran in 0.00s`（exit code 5）。所以源码改成 `COPY` 进镜像，
测试报告用 `docker cp` 取出来。**不要退回挂卷的做法。**

**③ NAS 拉不到 Docker Hub。** `registry-1.docker.io` 直连超时；daemon 里配的加速
`docker.fnnas.com` 需要 token 握手，`docker build` 试完就回落到官方源并失败。
Docker Hub 的中转站（`docker.1panel.live`）能匿名拿 manifest，但层下载实测 8MB 要 2 分钟以上。
**结论：基础镜像离线搬过去，搬一次就够了。**

```bash
# 在 Mac 上（arm 机器要显式拉 amd64）
docker pull --platform linux/amd64 python:3.13-slim
docker save python:3.13-slim | gzip -1 > python-313-slim-amd64.tar.gz
scp python-313-slim-amd64.tar.gz wuyupeng123@192.168.31.159:/vol2/@appdata/1Panel/1panel/apps/jenkins/jenkins/data/ci-src/
# 在 NAS 上（docker 要 root，所以借 Jenkins 跑一次，或者 sudo）
docker load -i <jenkins_home>/ci-src/python-313-slim-amd64.tar.gz
```

镜像已经在 NAS 上了（`python:3.13-slim`，amd64，118MB）。tar 包留在 Jenkins 的
`ci-src/` 目录里，`docker image prune` 清掉了可以再 `docker load` 一次。
`Jenkinsfile` 的自检阶段会检查这个镜像在不在，不在就直接报错并指向这一节。

**④ 源站速度差别巨大。** 同一时刻：`deb.debian.org` 21KB/s（`apt-get update` 会卡死），
清华 20MB/s；`pypi.org` 的索引还会被截断，清华 12MB/s。所以 `run-tests.sh` 把
apt/pip 源做成了 build-arg，Jenkins 里传清华源。**注意**：换源参数不同会让 apt/pip 那两层
缓存失效，重建一次大约 2 分钟。

### 2.5 Jenkins 作业

| 项 | 值 |
|---|---|
| 名称 | `aramhex`，`http://192.168.31.159:8080/job/aramhex/` |
| 类型 | Pipeline script from SCM |
| 仓库 | `http://192.168.31.159:9980/wuyupeng/aramhex.git`，凭据 `gitlab-http-creds`（FNOS GitLab oauth2 PAT，已能用） |
| 分支 | `main` |
| 脚本路径 | `Jenkinsfile` |
| 触发 | GitLab webhook（push 即建）+ `pollSCM` 5 分钟兜底 |
| 产物 | `build/ci/junit.xml`（Jenkins 里看测试报告） |

流水线只做两件事：自检（docker、基础镜像在不在）→ 跑 `docker/ci/run-tests.sh`。
实测一次构建 142 秒，其中测试 101 秒。

**webhook**：GitLab 项目 → Settings → Webhooks 里有一条
`http://192.168.31.159:8080/project/aramhex`，push 事件，Secret token 和 Jenkins 作业里
`GitLabPushTrigger` 的 `<secretToken>` 是同一个值（Jenkins 侧已加密存储）。
加 webhook 用的是 GitLab 的 API：

```bash
curl -X POST "http://192.168.31.159:9980/api/v4/projects/4/hooks" \
  -H "X-CSRF-Token: <网页会话的 csrf-token>" -b <cookie jar> \
  --data-urlencode "url=http://192.168.31.159:8080/project/aramhex" \
  --data-urlencode "token=<和 Jenkins 里一致>" \
  --data-urlencode "push_events=true"
```

`pollSCM` 留着当兜底：webhook 丢了也会在 5 分钟内自己跑起来。

### 2.6 源码怎么进 NAS：推一份到 GitLab

`scripts/sync_gitlab.sh` 把本仓库的分支和标签推到 NAS 的 GitLab
（`http://192.168.31.159:9980/wuyupeng/aramhex.git`，public，备份 + 给 Jenkins 取源码）。
GitHub 仍然是主仓库。

```bash
GITLAB_REPO=http://192.168.31.159:9980/wuyupeng/aramhex.git scripts/sync_gitlab.sh
```

脚本不存密码，凭据走 git 自己的凭据机制。

### 2.7 NAS 出不了 Windows 安装包

`packaging/` 下的脚本用 PyInstaller 和 Inno Setup，只能在 Windows 上跑；
NAS 是 Linux，用 Wine 折腾不值得。正式包仍然走
`.github/workflows/release.yml`（`windows-latest`）。
游戏内效果（三选一识别、浮窗盖在游戏上）也只能在装了国服客户端的 Windows 上验。

### 2.8 能不能在 NAS 上打 Windows 包：不能

PyInstaller 不是交叉编译器，它把**当前这台机器的**解释器和平台二进制打进包里
（`python313.dll`、PySide6 的 Qt 插件、`onnxruntime` 的 `.dll`），在 Linux 上跑只能产出
Linux 包；Windows 容器在 Linux 内核上起不来；`packaging/build.ps1` 打完还要启动 exe 跑
`--self-test-gui`，`packaging/package.ps1` 再调 Inno Setup（只有 Windows 版）。

用 Wine 装 Windows 版 Python 再跑 PyInstaller 是唯一不换机器的路子，但 PySide6 的 Qt 插件
和 MSVC 运行库在 Wine 下很容易崩，自检那步还要 Windows GUI，出问题的概率远高于省下的时间。

三条可选的路：

| 方案 | 代价 | 适合 |
|---|---|---|
| GitHub Actions `windows-latest` | 免费，fork 里 Actions 默认是关的，要去 Settings → Actions 打开 | 偶尔出包，推荐 |
| 一台 Windows 机器做 Jenkins agent | 要有机器，但能顺便做真机验证（国服客户端 + 浮窗） | 经常出包、要验游戏内效果 |
| Wine | 高失败率 | 不建议 |

游戏内效果（三选一识别、浮窗盖在游戏上）**只能**在装了国服客户端的 Windows 上验，
CI 替代不了这一条。

### 2.9 出测试包（GitHub Actions）

打 Windows 包的唯一路子是 GitHub Actions 的 `windows-latest`，工作流是
`.github/workflows/package.yml`（名字「打测试包」）。两种触发：

```bash
# 1) 推标签：版本号变成 1.3.0-<标签里的 test.N>
git tag test.2 && git push origin test.2
# 2) Actions 页面 → 打测试包 → Run workflow，可以改测试号、取消勾选「只出便携版」
```

产物在运行页面的 Artifacts 里：

| 产物 | 内容 |
|---|---|
| `AramHex-test.N` | 便携版 zip（默认）或安装版 exe + SHA256SUMS.txt |
| `自检结果-test.N` | `build/gui-smoke.json`：Qt 版本、OCR 识别到的字、版本号、是否官方包 |

**默认只出便携版**，因为测试包沿用官方的安装包 AppId（`packaging/LolHex.iss:14`），
装上去会被 Windows 当成官方版的升级。要验证安装/升级流程，用 Run workflow 取消勾选。

`build.ps1` 在出包前会启动打好的 exe 跑 `--self-test-gui`：Qt 的 Core/Gui/Widgets/Network、
OpenCV、文字识别都要过，不过就不出包。所以「能出包」本身已经说明界面和 OCR 在 Windows 上能跑。
测试包还会带一个空 `debug.txt`，解压运行即开启详细日志和自动截图（见 `packaging/build.ps1` 开头）。

2026-11-28 首次出包：`test.1`，产物 127MB，两个工作流（`测试`、`打测试包`）都是 passing。

## 3. 和 GitHub Actions 的分工

| 环境 | 触发 | 跑什么 | 出什么 |
|---|---|---|---|
| GitHub Actions `ci.yml` | push main / PR | Windows 全量测试（含 18 个 Windows-only） | 无 |
| NAS Jenkins `aramhex` | 每 5 分钟轮询 GitLab | Linux 全量测试（18 个 Windows-only 跳过） | junit 报告 |
| GitHub Actions `release.yml` | 推 `v*` 标签 | 版本号核对、资料检查、测试 | **没有打包步骤**（1.3.0 起官方包在别处打） |

要自己出安装包，得按 `docs/HANDOFF.md` 第 9 节的顺序来：先补标签，再改 `release.yml`。
