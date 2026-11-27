// NAS 上的 Jenkins 流水线（Linux）：只跑测试，不出包。
//
// 为什么不在 NAS 上打包：PyInstaller 不能跨平台，Windows 的 exe 只能在 Windows 上打。
// NAS 是 Linux x86_64，能验证识别、推荐、资料这些逻辑，出安装包仍然靠
// GitHub Actions 的 windows-latest（.github/workflows/release.yml）。
//
// 作业配置：Pipeline script from SCM → 源码在 NAS 的 GitLab，
// 脚本路径 Jenkinsfile，分支 main。
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
    }

    stages {
        stage('自检') {
            steps {
                sh '''
                    docker --version
                    test -f docker/ci/Dockerfile || { echo "缺 docker/ci/Dockerfile"; exit 1; }
                '''
            }
        }

        stage('构建测试镜像') {
            steps {
                // 依赖都在镜像里，源码改代码不用重建；requirements.txt 没变时这步走缓存，几秒
                sh 'docker build -t "$IMAGE" -f docker/ci/Dockerfile .'
            }
        }

        stage('测试') {
            steps {
                // run-tests.sh 里带了 -u、USER、QT_QPA_PLATFORM=offscreen 这些必要参数
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
            // 失败时把容器环境和镜像信息留下来，省得下次猜
            sh 'docker image inspect "$IMAGE" --format "{{.Id}} {{.Created}}" || true'
        }
    }
}
