#!/bin/sh
# 把本仓库的 main 和标签推到 NAS 上的 GitLab，做备份 + 给 Jenkins 当源码。
#
#   scripts/sync_gitlab.sh                 # 用默认地址
#   GITLAB_REPO=http://192.168.31.159:9980/wuyupeng/aramhex.git scripts/sync_gitlab.sh
#
# 为什么推到这里：NAS 到 github.com 只有 17KB/s，Jenkins 从 GitHub clone 要几分钟，
# 从局域网 GitLab clone 是秒级。GitHub 仍然是主仓库。
#
# 用户名和令牌走 git 的凭据，不写进这个脚本：
#   首次推送会提示输入，或者
#   git -c credential.helper=store ... （令牌存在 ~/.git-credentials）
set -eu

GITLAB_REPO=${GITLAB_REPO:-http://192.168.31.159:9980/wuyupeng/aramhex.git}

cd "$(dirname "$0")/.."

echo "推到 $GITLAB_REPO"
git push "$GITLAB_REPO" "refs/heads/main:refs/heads/main" "$@"
# 标签一起推：发版检查（scripts/check_release_data.py）要和上一个版本的标签比
git push "$GITLAB_REPO" --tags 2>/dev/null || echo "（没有标签可推，或者已经同步过）"

echo "完成。Jenkins 的 aramhex 作业从 $GITLAB_REPO 拉 main 分支。"
