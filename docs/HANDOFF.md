# 海克斯大乱斗推荐插件：交接文档

日期：2026-11-27

## 1. 目标和已定范围

做一个《英雄联盟》海克斯大乱斗的辅助工具：三选一出现时，按当前英雄推荐胜率最高的海克斯。

已确定的决定：

- 只做国服。
- 公开发布，禁止商用。不加广告和付费功能。
- 基于开源项目 czgreat/aramhex（MIT 许可证）修改，不从零写。
- 后续要重构它的 APP 界面。
- 不连接游戏客户端（LCU、2999 端口），不读内存，不注入，不模拟按键。只截屏识别和显示。

## 2. 调研结论

**数据来源**

- Riot 公开对局接口 match-v5 对海克斯大乱斗对局故意返回 403，官方接口拿不到数据。
- 采用 [aramhex-data](https://github.com/czgreat/aramhex-data)：国服各区合并样本，按"英雄 → 海克斯"给出局数、胜场、胜率和小样本标记。16.23 版本有效对局约 840 万。许可证 CC BY-NC 4.0，需署名，禁止商用。
- 备用来源是 OP.GG，每个英雄有页面 `/lol/modes/aram-mayhem/{英雄}/build`，没有公开 API，只能抓页面。

**识别三选一**

- 没找到官方本地接口能直接给出三个选项。现有开源工具都用截屏 OCR。
- Overwolf 平台有 `augments` 事件能给出选项，但必须在 Overwolf 上开发，国服能否使用没有验证。

**游戏内展示**

- 透明、置顶、鼠标穿透的窗口盖在游戏上方。
- 游戏必须设为无边框或窗口化，独占全屏下盖不上去。

**国服风险**

- LeagueAkari 的 README 写明不支持腾讯服。国服连 LCU 是否安全没有查到依据。
- 这类工具都没有官方认可，封号风险无法排除。截屏加置顶窗口是侵入性最低的做法。

## 3. 目前做了什么

- 完成上面的可行性调研。
- 用户把原仓库 fork 到 https://github.com/WUYUPENGG/aramhex 。
- 把 fork 克隆到 `/Users/mac/ComateProjects/chats/2026-11-27/chat1/aramhex`，版本 1.3.0，提交 `ffb784a`，分支 `main`。
- 读了代码结构、依赖、联网行为和平台相关代码（结论见第 4 节）。
- 把本文档提交到仓库的 `docs/HANDOFF.md`，分支 `docs/handoff`。只提交到本地，没有推送。

还没做的：

- 没有改任何代码。
- 没有运行过程序，也没有跑过测试。
- 没有把原仓库 czgreat/aramhex 加为上游。
- fork 只有 `main` 分支，没有任何标签。原仓库的 25 个标签没有带过来，这会让正式包的发版检查失败（见第 9.2 节）。

## 4. 代码现状

技术栈：Python 3.13、PySide6（Qt Widgets）、RapidOCR、onnxruntime、OpenCV、mss。

| 部分 | 位置 | 说明 |
|---|---|---|
| 入口 | `lolhex/__main__.py` | `python -m lolhex`，支持 `--scan-image 截图 --hero 英雄` 离线测识别 |
| 调度 | `lolhex/engine.py` | 后台线程做识别和推荐 |
| 识别 | `lolhex/vision/` | 截屏、选人界面、三选一、OCR |
| 推荐 | `lolhex/recommend.py` | 三选一评分 |
| 统计数据 | `lolhex/data/public.py` | 内置一份，启动时从数据仓库更新并校验 SHA-256 |
| 主窗口和托盘 | `lolhex/ui/mainwindow.py` | 1400 行 |
| 游戏内浮窗 | `lolhex/ui/overlay.py` | 1449 行 |
| 外观 | `lolhex/ui/theme.py` | 159 行，Fusion 样式加样式表，浅色 |
| 开发说明 | `docs/DEVELOPMENT.md` | 目录、原则、测试、打包、发版流程 |

**界面和逻辑的关系**

- 引擎不回调界面。界面定时读 `engine.snapshot()`，通过 `set_hero`、`rescan`、`set_band` 等方法操作引擎。重构界面不需要动识别和推荐。
- `mainwindow.py` 里混着非界面逻辑：检查更新、增量更新、云控、查分、日志上传。
- 106 个测试文件里，16 个依赖主窗口，27 个依赖浮窗。改界面要连带改测试。

**源码版和官方安装包的差别**

- 源码不带官方模块（`lolhex/official.py`），所以查分、云控、日志上传、自动更新全部关闭，不会连原作者的服务器。
- 统计数据的唯一下载地址是 `raw.githubusercontent.com`（`lolhex/data/public.py:52`）。国内连不上时退回内置数据。
- 非官方包不检查更新（`lolhex/update.py:211`）。

**平台**

- 依赖包都是跨平台的。
- 5 个文件调用 Windows 系统接口，关键的是 `lolhex/vision/window.py`（找游戏窗口、摆放浮窗）。非 Windows 下有判断，不会崩，但找不到窗口，识别和浮窗不工作。
- 只有 5 个测试标了仅限 Windows。项目 CI 只在 Windows 上跑。

## 5. 后续工作

按先后顺序，前面的项是后面的前提。

| 顺序 | 工作 | 内容 | 在哪做 |
|---|---|---|---|
| 0 | Mac 环境（已完成） | 已用 uv 建 arm64 Python 3.13 虚拟环境，测试 1254 通过 / 24 跳过。步骤和踩过的坑见 `docs/ENVIRONMENT.md` | Mac |
| 0.5 | NAS CI（已完成） | 飞牛 NAS 上的 Jenkins + Docker 跑 Linux 测试，`Jenkinsfile` + `docker/ci/`。只跑测试，不出包，见 `docs/ENVIRONMENT.md` 第 2 节 | NAS |
| 1 | 仓库准备 | 把 czgreat/aramhex 加为上游，新建开发分支，不直接改 main | Mac |
| 2 | Windows 环境 | 装 Python 3.13 和依赖，从源码运行，跑测试，进一局游戏确认识别和浮窗正常 | Windows |
| 3 | 改名换图标 | 见下方清单 | Mac 改，Windows 验证 |
| 4 | 许可证和文档 | 保留原 `LICENSE` 里 czgreat 的 MIT 声明，新增部分加非商用许可证（建议 PolyForm Noncommercial 1.0.0）。重写 `README.md` 和 `PRIVACY.md` | Mac |
| 5 | 数据镜像 | 定时把 aramhex-data 同步到国内可访问的地址，在 `lolhex/data/public.py` 的 `DATA_SOURCES` 里加上 | Mac |
| 6 | 更新提示 | 让 `lolhex/update.py` 检查自己仓库的 Releases | Mac 改，Windows 验证 |
| 7 | 界面重构 | 见下方步骤 | Mac 改，Windows 验证 |
| 8 | 打包发布 | 改 `packaging/` 下的脚本和 `.github/workflows/release.yml`，出安装版和便携版。环境、现状和 CI 草稿见第 9 节 | Windows 或 GitHub Actions |

第 3 到 6 项互相独立。第 7 项放在第 3 项之后，避免改名和界面改动混在同一批提交里。

**第 3 项改名清单**

- 品牌字样分布在 18 个文件里，最多的是 `packaging/LolHex.iss`（26 处）。
- 仓库地址：`lolhex/__init__.py` 的 `GITHUB_REPO`。
- 数据目录名：`lolhex/config.py:50` 的 `APP_DIR_NAME`。必须改，否则和官方版共用同一份配置。
- 安装包文件名规则：`lolhex/update.py` 的 `FILE_RE`。
- 图标：`lolhex/ui/icon.png`、`packaging/lolhex.ico`。
- 原作者要求改版发布时换名字和图标。

**第 7 项界面重构步骤**

继续用 PySide6 Widgets，不换框架。换框架等于重写，也会让上游的识别修复合并不进来。

1. 先改 `theme.py` 的颜色、圆角、间距，风险最低。
2. 再把 `mainwindow.py` 按页面拆成多个文件，把更新、查分等流程移出界面类。
3. `overlay.py` 只改样式。它的定位和焦点处理有大量针对具体问题的修补，布局逻辑不要动。

## 6. 等用户决定

1. 新名字和图标（第 3 项需要）。图标自己准备，还是先用占位图。
2. 数据镜像放哪（第 5 项需要）。Gitee 仓库最简单，对象存储更稳定但要花钱。
3. 界面方向（第 7 项需要）。深色还是浅色，布局怎么改，有没有参考的软件。
4. 有没有 Windows 机器，什么时候能用。
5. 是否先在 Mac 上搭环境跑测试（第 0 项）。已经提议，用户还没答复。
6. 是否把原仓库的 25 个标签推到 fork（第 9.6 节第 1 步）。已经提议，用户还没答复。

## 7. 环境和注意事项

- 开发机是 Mac（arm64），只有系统自带的 Python 3.9.6，已装 Homebrew。目标平台是 Windows 10/11 64 位。
- 这台 Mac 直连 github.com 超时，gitee.com 能连通。用户授权超时时走本地代理 `127.0.0.1:7897`。代理没有写进 git 配置，每次要带上：

  ```bash
  git -c http.proxy=http://127.0.0.1:7897 -c https.proxy=http://127.0.0.1:7897 pull
  ```

- 测试命令（来自 `docs/DEVELOPMENT.md`，Windows PowerShell）：

  ```powershell
  $env:QT_QPA_PLATFORM = 'offscreen'
  .venv\Scripts\python -m pytest
  ```

- CI 把 Python 固定在 3.13.16，注释说明 Python 版本一变，老用户就没法增量更新。
- 软件里要署名数据来源：`海克斯大乱斗统计数据（github.com/czgreat/aramhex-data），CC BY-NC 4.0`。
- 第三方组件和各自的协议列在 `NOTICE.md`，改版后要保留。

## 8. 没有验证的事

- 测试能否在 Mac 上运行，锁定版本的依赖能否在 arm64 上全部装上。
- 程序在真实对局里的识别效果。没有运行过。
- aramhex-data 原始对局的采集方式，仓库没有说明。它由个人维护，是唯一的数据上游。
- aramhex-data 给程序看的读取说明 `AGENTS.md`，抓取时返回 503，没读到。数据格式以 `lolhex/data/public.py` 顶部的说明为准。
- OP.GG 英雄页里的海克斯字段，只确认了总览页。
- Riot 和腾讯对第三方工具的政策条款，没有查原文。mayhem-advisor 称因 Riot 政策只显示评分不显示胜率。

## 9. 打包和 CI

以下内容来自读打包脚本和工作流文件，没有实际跑过。

### 9.1 打包环境

打包只能在 Windows 上做。PyInstaller 不能跨平台打包，Mac 上打不出 exe。不一定要自己的 Windows 电脑，GitHub Actions 的 `windows-latest` 构建机可以完成。

| 需要 | 说明 |
|---|---|
| Windows 10/11 64 位 | 本机或 GitHub Actions 构建机 |
| Python 3.13 | CI 固定在 3.13.16 |
| PowerShell 7 | 打包脚本用 `pwsh` 运行 |
| Inno Setup 6 | 只有安装版需要。只出便携版（`-PortableOnly`）可以不装。安装命令：`winget install --id JRSoftware.InnoSetup -e` |
| 带标签的 git 仓库 | 正式包的发版检查要和上一个版本的标签对比 |
| `requirements-build.txt` | 运行依赖加 PyInstaller 6.22.3，版本由 `packaging/constraints.txt` 全部锁定 |

本机打包命令：

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements-build.txt
pwsh -NoProfile -File packaging\build.ps1
```

`packaging/build.ps1` 依次做三件事：

1. 用 `packaging/lolhex.spec` 让 PyInstaller 生成程序目录 `build/dist/AramHex`。
2. 启动打好的 exe 跑自检（`--self-test-gui`），确认界面和文字识别能用。自检不过不出包。
3. 调用 `packaging/package.ps1` 出安装版、便携版 zip 和 `SHA256SUMS.txt`，输出在 `build/release/`。

常用参数：

- `-TestTag test.1`：打测试包，版本号变成 `1.3.0-test.1`，跳过发版检查，自动开启调试模式。
- `-PortableOnly`：只出便携版，不需要 Inno Setup。
- `-Official`：官方包专用，需要不公开的官方模块，fork 用不到。

### 9.2 fork 现在打不了正式包的原因

- **fork 没有标签**。原仓库有 25 个标签（`v1.0.0` 到 `v1.3.0`，以及 `updates-v*`），fork 只有 `main` 分支。`scripts/check_release_data.py` 找不到上一个正式版标签会直接报错。需要从原仓库取标签再推到 fork。测试包不受影响。
- **产物名写死成 AramHex**。分布在 `packaging/build.ps1`、`packaging/package.ps1`、`packaging/lolhex.spec`、`packaging/LolHex.iss`，改名时要一起改。`package.ps1` 生成的便携版说明里还带着原仓库的下载链接。
- **安装包的 AppId 必须换**。`packaging/LolHex.iss:14` 的 GUID 不换的话，Windows 会把新安装包当成官方版的升级，覆盖用户已装的官方版。同一文件里的 `AppPublisher` 和 `AppPublisherURL` 也要换。
- **没有代码签名**。用户安装时会看到 SmartScreen 警告，原项目也是这样。

### 9.3 现有的 CI

仓库里有两个工作流，都跑在 `windows-latest` 上：

| 文件 | 触发条件 | 做什么 |
|---|---|---|
| `.github/workflows/ci.yml` | 推送到 `main`，或提 PR | 装 `requirements.txt`，跑全部测试。不用改 |
| `.github/workflows/release.yml` | 推送 `v*` 标签 | 只做检查：核对版本号、检查内置资料、跑测试。不打包 |

`release.yml` 不打包的原因：原作者从 1.3.0 起在别处打官方包（要加不公开的官方模块），所以把打包和发布步骤删了。带打包步骤的旧版本在提交 `2fc4cfd` 里，查看命令：

```bash
git show 2fc4cfd:.github/workflows/release.yml
```

### 9.4 CI 要做的改动

1. 在 fork 的 Actions 页面启用工作流。fork 默认是关闭的。
2. 把 `release.yml` 改回"打包并发布"。照旧版本恢复，去掉"增量更新文件（updates 分支）"那一步，它只给官方包用。
3. 可选：加一个手动触发的工作流，用 `-TestTag test.1 -PortableOnly` 打测试包并作为构建产物下载。这样没有 Windows 开发机也能拿到可运行的包。

发版流程：改 `lolhex/__init__.py` 里的 `__version__`，提交，打 `v<版本>` 标签并推送，CI 自动出包并建 Release。标签必须和 `__version__` 一致，否则 CI 报错。

改完的 `release.yml` 草稿见 9.5。草稿没有运行过，`windows-latest` 上是否已预装 Inno Setup 没有确认，所以保留了旧版本里的安装步骤。

### 9.5 release.yml 草稿

```yaml
name: 发布
on:
  push:
    tags: ["v*"]
permissions:
  contents: write
env:
  PYTHONUTF8: "1"
  PYTHONIOENCODING: utf-8
jobs:
  release:
    runs-on: windows-latest
    defaults:
      run:
        shell: pwsh
    steps:
      - uses: actions/checkout@v5
        with:
          fetch-depth: 0   # 发版检查要读以前的标签
      - uses: actions/setup-python@v6
        with:
          python-version: "3.13.16"
          cache: pip
      - name: 安装依赖
        run: python -m pip install -r requirements-build.txt
      - name: 核对版本号
        run: |
          $version = (python -c "import lolhex; print(lolhex.__version__)").Trim()
          if ("v$version" -ne "${{ github.ref_name }}") { throw "tag 和 __version__ 不一致" }
      - name: 测试
        env:
          QT_QPA_PLATFORM: offscreen
        run: python -m pytest -q
      - name: 安装 Inno Setup
        run: choco install innosetup --no-progress -y
      - name: 打包
        run: pwsh -NoProfile -File packaging/build.ps1 -PythonExe python
      - name: 建 Release
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          $files = Get-ChildItem build/release | ForEach-Object { $_.FullName }
          gh release create "${{ github.ref_name }}" @files --title "${{ github.ref_name }}" --generate-notes
```

说明：

- `build.ps1` 打正式包时自己会跑 `scripts/check_release_data.py`，所以草稿里没有单独的检查步骤。
- 旧版本用 `scripts/release_notes.py` 生成发布说明。这个脚本没读过，草稿里先用 GitHub 自动生成的说明。

### 9.6 建议的顺序

1. 取上游标签并推到 fork，启用 Actions，确认 `ci.yml` 能跑通。这一步同时能确认测试在干净的 Windows 环境里能否通过。
2. 加手动触发的测试包工作流，拿到一个可运行的便携版。
3. 改名之后再改 `release.yml` 发正式版。

第 1 步的命令（在仓库目录下，走代理）：

```bash
git remote add upstream https://github.com/czgreat/aramhex.git
git -c http.proxy=http://127.0.0.1:7897 -c https.proxy=http://127.0.0.1:7897 fetch upstream --tags
git -c http.proxy=http://127.0.0.1:7897 -c https.proxy=http://127.0.0.1:7897 push origin --tags
```

这会向 fork 推送 25 个标签，执行前要用户确认。

CI 代替不了的事：游戏内的实际效果仍然需要一台装了国服客户端的 Windows 电脑来验证。

## 参考链接

- 用户的 fork：https://github.com/WUYUPENGG/aramhex
- 原仓库：https://github.com/czgreat/aramhex
- 数据仓库：https://github.com/czgreat/aramhex-data
- 同类项目（OCR 加 OP.GG 数据）：https://github.com/Nyx0ra/lol-aram-mayhem-hextech-helper
- 同类项目（外服，Electron 浮窗）：https://github.com/ItzStorDz/mayhem-advisor
- match-v5 对该模式返回 403 的说明：https://github.com/RiotGames/developer-relations/issues/1109
- Overwolf 事件文档：https://dev.overwolf.com/ow-native/live-game-data-gep/supported-games/league-of-legends/
- OP.GG 海克斯大乱斗：https://op.gg/zh-cn/lol/modes/aram-mayhem
