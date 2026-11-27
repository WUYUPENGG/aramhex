// NAS 上的 Jenkins 流水线（Linux）：只跑测试，不出包。
//
// 为什么不在 NAS 上打包：PyInstaller 不能跨平台，Windows 的 exe 只能在 Windows 上打。
// NAS 是 Linux x86_64，能验证识别、推荐、资料这些逻辑；出安装包仍然靠
// GitHub Actions 的 windows-latest（.github/workflows/release.yml）。
//
// 作业配置：Pipeline script from SCM → 源码在 NAS 的 GitLab
// （http://192.168.31.159:9980/wuyupeng/aramhex.git），脚本路径 Jenkinsfile。
pipeline {
    // 必须钉在 built-in（NAS 上的 Jenkins 容器）上。NAS 的 Jenkins 还挂了一个
    // mac-agent 节点（就是开发用的 Mac），用 agent any 会被派到 Mac 上去，
    // 那就不是「在 NAS 上跑」了。
    agent { label 'built-in' }

    options {
        timestamps()
        timeout(time: 45, unit: 'MINUTES')
        buildDiscarder(logRotator(numToKeepStr: '30'))
        disableConcurrentBuilds()
    }

    environment {
        IMAGE = 'aramhex-ci:py313'
        // NAS 到 deb.debian.org / pypi.org 都不稳，走清华源（实测 20MB/s / 12MB/s）
        APT_MIRROR = 'mirrors.tuna.tsinghua.edu.cn'
        PIP_INDEX = 'https://pypi.tuna.tsinghua.edu.cn/simple'
    }

    stages {
        stage('自检') {
            steps {
                sh '''
                    docker --version
                    docker image inspect python:3.13-slim --format '{{.Id}}' \
                        || { echo "缺基础镜像 python:3.13-slim，见 docs/ENVIRONMENT.md 第 2.3 节"; exit 1; }
                '''
            }
        }

        stage('测试') {
            steps {
                // 建镜像（依赖层有缓存）+ 跑全部测试；报告写到 build/ci/junit.xml
                sh 'docker/ci/run-tests.sh'
            }
        }
    }

    post {
        always {
            junit allowEmptyResults: true, testResults: 'build/ci/junit.xml'
            archiveArtifacts artifacts: 'build/ci/junit.xml', allowEmptyArchive: true
        }
        unsuccessful {
            sh 'docker image inspect "$IMAGE" --format "{{.Id}} {{.Created}}" || true'
            sh 'docker ps -a --filter "name=aramhex-ci-run" || true'
        }
    }
}
