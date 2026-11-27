# AramHex 项目约定（给所有 AI/人读的第一份文件）

改代码前先读这份。它只写**规则和事实**，原理和细节在 `docs/` 里。

## 1. 两个远端，一条 push 推两边

| 角色 | 地址 | 用途 |
|---|---|---|
| **主仓库** | `github.com/WUYUPENGG/aramhex` | 公开仓库、GitHub Actions、Release 下载 |
| **CI 源码** | `http://192.168.31.159:9980/wuyupeng/aramhex.git`（NAS GitLab） | Jenkins 从这里拉代码、GitLab 备份 |
| 上游 | `github.com/czgreat/aramhex`（`upstream`，只 fetch 不 push） | 取标签、合并上游修复 |

**为什么 GitLab 必须有一份**：Jenkins 在 NAS 内网，拉 `github.com` 实测 17KB/s
（11MB 仓库要 10 分钟，常超时），拉同局域网 GitLab 是秒级。没有 GitLab 那份，CI 就跑不动。

### 这台 Mac 已经配好「双推」

`origin` 挂了两个 pushurl，所以**一条命令推两边**：

```bash
git push origin main          # 同时更新 GitHub 和 NAS GitLab
git push origin test.4        # 标签同理
```

GitLab 的凭据在 macOS 钥匙串里（`oauth2` + project access token，到期 2027-11-01），
不用每次输密码。校验两边是否一致：

```bash
git ls-remote origin refs/heads/main | cut -c1-7
git ls-remote http://192.168.31.159:9980/wuyupeng/aramhex.git refs/heads/main | cut -c1-7
```

### 硬规则

1. **用 `git push origin <branch|tag>` 推**，一条命令就够（双推已配好）。
   **不要**用 `git push gitlab ...` 这种写法，也不要只推 GitHub——Jenkins 收不到。
2. **换机器 clone 之后必须先配双推**，否则那边推的东西永远到不了 CI：

   ```bash
   git remote set-url --add --push origin https://github.com/WUYUPENGG/aramhex.git
   git remote set-url --add --push origin http://oauth2@192.168.31.159:9980/wuyupeng/aramhex.git
   ```

3. **不要直接改 main**：开分支 → 推 → 合并。main 是发布线。
4. **不要给 GitLab 加人的写权限**：只有这台 Mac 的钥匙串和一个 project access token 能写。
5. push 完想确认 CI 动没动：Jenkins `http://192.168.31.159:8080/job/aramhex/`，
   正常几十秒内会出现一条 `Started by GitLab push`。
6. GitHub Actions 只是测试和出包，**不负责同步代码**（早期试过自动镜像，为了少一个
   token 和一个 workflow 又撤了，见提交 c92341d 的历史）。

## 2. CI 拓扑

| 位置 | 触发 | 干什么 | 出什么 |
|---|---|---|---|
| GitHub Actions `测试`（`ci.yml`） | push main / PR | Windows 全量测试 | 无 |
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
15. **本机访问 GitHub 走代理 `127.0.0.1:7897`**，已经写进全局 git 配置：

    ```bash
    git config --global http.https://github.com/.proxy http://127.0.0.1:7897
    ```

    所以 `git pull` / `git fetch` / `git push origin` 不用再带 `-c http.proxy=...` 参数，
    实测 1.3 秒拉完。**代理没开时 pull 会卡到超时**，先确认 Clash（7897 端口）在跑。
    只对 github.com 生效，局域网 GitLab 直连，不绕代理。

## 4. 不能做的事

16. **不碰游戏客户端**：不连 LCU、不走 2999 端口、不读内存、不注入、不模拟按键。
    只截屏识别 + 显示。理由见 `docs/HANDOFF.md` 第 1 节。
17. **不把凭据写进仓库**：GitLab 的推送凭据放 macOS 钥匙串，GitHub 的放 GitHub Secrets；
    密码/token 不进代码、不进 `git config` 明文、不进 CI 日志。
18. **不加广告、不做商用功能**：许可证要求非商用，数据源是 CC BY-NC 4.0，
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
