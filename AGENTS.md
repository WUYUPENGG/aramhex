# AramHex 项目约定（给所有 AI/人读的第一份文件）

改代码前先读这份。它只写**规则和事实**，原理和细节在 `docs/` 里。

## 1. 仓库拓扑：GitHub 是主，GitLab 是镜像

| 角色 | 地址 | 谁在写 |
|---|---|---|
| **主仓库** | `github.com/WUYUPENGG/aramhex`（`origin`） | 人、AI、所有 CI |
| **镜像仓库** | `http://192.168.31.159:9980/wuyupeng/aramhex.git`（NAS GitLab） | **只有** `.github/workflows/mirror.yml` 自动写 |
| 上游 | `github.com/czgreat/aramhex`（`upstream`，只 fetch 不 push） | 只用来取标签/合并上游修复 |

### 硬规则

1. **只推 GitHub。** 不要手动 `git push` 到 GitLab，也不要给别人 GitLab 的写权限。
   GitHub 上的任何 push（分支或标签）都会由 `mirror.yml` 在几十秒内搬到 GitLab。
2. **分支和标签都要推**：`git push origin main`、`git push origin <tag>`。
   只推分支不推标签，Jenkins 拿不到测试包的触发标签。
3. **不要直接改 main**：开分支 → 推 GitHub → 合并。main 是发布线。
4. 镜像失败时（`镜像到 NAS GitLab` 这个 workflow 红），先看 NAS 是否开机；
   实在要补，用 `scripts/sync_gitlab.sh` 手工补一次，别改 workflow 绕过去。
5. 为什么要有镜像：Jenkins 在 NAS 内网，拉 GitHub 只有 17KB/s；拉 GitLab 是秒级。
   同时它也是 GitHub 之外的第二份备份。

## 2. CI 拓扑

| 位置 | 触发 | 干什么 | 出什么 |
|---|---|---|---|
| GitHub Actions `测试`（`ci.yml`） | push main / PR | Windows 全量测试 | 无 |
| GitHub Actions `镜像到 NAS GitLab`（`mirror.yml`） | 任何 push | 把提交/标签搬到 GitLab | 无 |
| NAS Jenkins `aramhex` | GitLab push（webhook）+ 5 分钟轮询 | Linux 全量测试（Docker） | junit 报告 |
| GitHub Actions `打测试包`（`package.yml`） | 推 `test.<数字>` 标签 / 手动 | 测试 → PyInstaller → 便携版 zip → prerelease | 安装包 |
| GitHub Actions `发版检查`（`release.yml`） | 推 `v*` 标签 | 版本号、内置资料、测试 | 无（1.3.0 起不在这里打包） |

### 硬规则

6. **Windows 包只能在 GitHub Actions 的 `windows-latest` 上打**。NAS 是 Linux，
   PyInstaller 打不出 exe；也不要用 Wine 折腾。
7. **出测试包就推标签**，不要手动跑脚本：

   ```bash
   git tag test.4 && git push origin test.4      # 版本号变成 1.3.0-test.4
   ```

   产物在 `https://github.com/WUYUPENGG/aramhex/releases/tag/test.4`，
   不用登录就能下。`test.1`/`test.2`/`test.3` 已经用掉了，**不要复用测试号**。
8. 测试包**默认只出便携版**：安装包的 AppId 和官方版相同（`packaging/LolHex.iss:14`），
   装上去会被当成官方版升级。要验安装流程才用 Run workflow 取消勾选。
9. 测试完整跑法（本机）：`QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q`，
   期望 `1254 passed, 24 skipped`（24 = 18 个 Windows-only + 6 个字体度量）。

## 3. 环境事实（别踩）

10. **这台 Mac 用 arm64 的 Python 3.13**：`/usr/local/bin/python3.13` 是 x86_64（Rosetta），
    `onnxruntime==1.30.0` 没有 x86_64 macOS 轮子，装不上。用 `uv venv --python 3.13 .venv`。
11. **NAS 上 `wuyupeng123` 没有 docker 权限**（`sudo` 要密码）。用 docker 的是 Jenkins 容器
    （root + 挂了 socket）。要给 NAS 加镜像，只能 `docker load` 一个 tar。
12. **Jenkins 里别用 `docker run -v <源码目录>`**：Jenkins 在容器里，`/var/jenkins_home`
    在宿主是别的路径，会挂成空目录，pytest 报 `no tests ran`。源码要 COPY 进镜像。
13. **NAS 上 apt/pip 用清华源**，docker 基础镜像已经离线 load 过（`python:3.13-slim`）。
    换源参数不同会让缓存失效，重建约 2 分钟。
14. Jenkins 作业必须钉 `agent { label 'built-in' }`：这个 Jenkins 还挂了一个 `mac-agent`
    节点（就是开发用的 Mac），`agent any` 会把构建派到 Mac 上去。

## 4. 不能做的事

15. **不碰游戏客户端**：不连 LCU、不走 2999 端口、不读内存、不注入、不模拟按键。
    只截屏识别 + 显示。理由见 `docs/HANDOFF.md` 第 1 节。
16. **不把凭据写进仓库**：GitLab token 放 GitHub Secrets（`GITLAB_TOKEN`）；
    密码/token 不进代码、不进 `git config`、不进 CI 日志。
17. **不加广告、不做商用功能**：许可证要求非商用，数据源是 CC BY-NC 4.0，
    界面上要保留署名 `海克斯大乱斗统计数据（github.com/czgreat/aramhex-data），CC BY-NC 4.0`。

## 5. 待办（按顺序）

| 事 | 卡在谁 |
|---|---|
| 改名、换图标、安装包 AppId | 等用户定名字和图标 |
| 界面重构（深浅色、布局） | 等用户给方向；顺便修 `overlay.py` 那个 1px 截断 |
| 数据镜像（`lolhex/data/public.py` 的 `DATA_SOURCES`） | 等用户定放哪（NAS 合适） |
| `release.yml` 恢复「打包并发布」 | 改名之后 |

## 6. 文档索引

| 文件 | 讲什么 |
|---|---|
| `docs/HANDOFF.md` | 项目来龙去脉、调研结论、后续 8 项工作、打包的坑 |
| `docs/ENVIRONMENT.md` | 两套环境怎么搭、CI 怎么跑、踩过的坑、出包和下载 |
| `docs/DEVELOPMENT.md` | 目录结构、代码原则、测试、打包、发版流程 |
| `CHANGELOG.md` | 每个版本改了什么 |
