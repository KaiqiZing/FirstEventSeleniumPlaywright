def runCrossPlatform(String cmd) {
    if (isUnix()) {
        sh """
            set -e
            if [ -f /.dockerenv ]; then
                export ACCEPTANCE_FRONTEND_URL="\$(echo "\$ACCEPTANCE_FRONTEND_URL" | sed 's|://localhost|://host.docker.internal|g; s|://127.0.0.1|://host.docker.internal|g')"
                export ACCEPTANCE_API_URL="\$(echo "\$ACCEPTANCE_API_URL" | sed 's|://localhost|://host.docker.internal|g; s|://127.0.0.1|://host.docker.internal|g')"
            fi
            if [ -n "\${CUSTOM_PW_BROWSERS_PATH:-}" ]; then
                export PLAYWRIGHT_BROWSERS_PATH="\$CUSTOM_PW_BROWSERS_PATH"
            fi
            if [ -n "\${CUSTOM_PW_DEBUG:-}" ]; then
                export DEBUG="\$CUSTOM_PW_DEBUG"
            fi
            ${cmd}
        """
    } else {
        bat """
            chcp 65001 > nul
            if not "%CUSTOM_PW_BROWSERS_PATH%"=="" (
                set "PLAYWRIGHT_BROWSERS_PATH=%CUSTOM_PW_BROWSERS_PATH%"
            ) else if "%PLAYWRIGHT_BROWSERS_PATH%"=="" (
                set "PLAYWRIGHT_BROWSERS_PATH=C:/Users/Administrator/AppData/Local/ms-playwright"
            )
            if not "%CUSTOM_PW_DEBUG%"=="" (
                set "DEBUG=%CUSTOM_PW_DEBUG%"
            )
            ${cmd}
        """
    }
}

pipeline {
    agent any

    options {
        timestamps()
        timeout(time: 20, unit: 'MINUTES')
        buildDiscarder(logRotator(numToKeepStr: '20', artifactNumToKeepStr: '10'))
        disableConcurrentBuilds()
    }

    parameters {
        choice(
            name: 'RUN_MODE',
            choices: ['smoke', 'ui-menu', 'acceptance-smoke', 'regression', 'full'],
            description: '执行模式：smoke(冒烟3例 ~20s) / ui-menu(37页菜单颜色 ~15s) / acceptance-smoke(标准化验收Skill ~45s) / regression(回归) / full(全量37场景 ~4m)'
        )
        choice(
            name: 'BROWSER',
            choices: ['chromium', 'chrome', 'edge', 'firefox', 'webkit'],
            description: '目标浏览器内核（chromium 缺失内置版本时自动回退系统 Chrome/Edge）'
        )
        choice(
            name: 'TRACE_MODE',
            choices: ['retain-on-failure', 'on', 'off'],
            description: 'Playwright Trace 录制策略（retain-on-failure 仅失败落盘）'
        )
        string(
            name: 'FRONTEND_URL',
            defaultValue: 'http://localhost:5173',
            description: '被测前端测试地址（Docker 容器内会自动将 localhost 映射为 host.docker.internal）'
        )
        string(
            name: 'API_URL',
            defaultValue: 'http://127.0.0.1:5050',
            description: '被测后端接口地址（Docker 容器内会自动将 127.0.0.1 映射为 host.docker.internal）'
        )
        string(
            name: 'PLAYWRIGHT_BROWSERS_PATH',
            defaultValue: '',
            description: '可选：覆盖 Playwright 浏览器缓存目录（Linux Docker 留空使用镜像内置 /ms-playwright；Windows 留空默认使用 Administrator 缓存）'
        )
        string(
            name: 'PW_DEBUG',
            defaultValue: '',
            description: '可选：Playwright 底层调试日志开关（如 pw:browser*；留空关闭）'
        )
    }

    environment {
        PYTHONUTF8 = '1'
        PYTHONIOENCODING = 'utf-8'
        CUSTOM_PW_BROWSERS_PATH = "${params.PLAYWRIGHT_BROWSERS_PATH ?: ''}"
        CUSTOM_PW_DEBUG = "${params.PW_DEBUG ?: ''}"
        ACCEPTANCE_FRONTEND_URL = "${params.FRONTEND_URL ?: 'http://localhost:5173'}"
        ACCEPTANCE_API_URL = "${params.API_URL ?: 'http://127.0.0.1:5050'}"
        ACCEPTANCE_BROWSER = "${params.BROWSER ?: 'chromium'}"
        ACCEPTANCE_TRACE_MODE = "${params.TRACE_MODE ?: 'retain-on-failure'}"
    }

    stages {
        stage('1. Environment Check') {
            steps {
                script {
                    def py = isUnix() ? 'python3' : 'python'
                    runCrossPlatform("""
                        echo "===== Jenkins Runtime Context ====="
                        whoami
                        ${py} --version
                        ${py} -c "import os, platform; print('OS:', platform.platform()); print('FRONTEND_URL:', os.environ.get('ACCEPTANCE_FRONTEND_URL')); print('API_URL:', os.environ.get('ACCEPTANCE_API_URL')); print('PLAYWRIGHT_BROWSERS_PATH:', os.environ.get('PLAYWRIGHT_BROWSERS_PATH', '<default>'))"
                        ${py} -c "import playwright, pytest, yaml, requests, allure; print('Python deps ready')" || ${py} -m pip install -q -r requirements.txt
                        ${py} -c "import shutil, pathlib; [shutil.rmtree(p, ignore_errors=True) for p in ('report/junit', 'report/allure-results', 'logs/screenshots', 'logs/traces')]; [pathlib.Path(p).mkdir(parents=True, exist_ok=True) for p in ('report/junit', 'report/allure-results')]"
                    """)
                }
            }
        }

        stage('2. Service Preflight') {
            steps {
                script {
                    def py = isUnix() ? 'python3' : 'python'
                    runCrossPlatform("""
                        ${py} -c "import os, requests; fe=os.environ['ACCEPTANCE_FRONTEND_URL']; be=os.environ['ACCEPTANCE_API_URL']; r1=requests.get(fe, timeout=5); r2=requests.get(be + '/api/health', timeout=5); print('Frontend:', fe, r1.status_code); print('Backend:', be, r2.status_code, r2.text); assert r1.status_code < 500 and r2.status_code == 200"
                    """)
                }
            }
        }

        stage('3. Run Playwright Tests') {
            steps {
                script {
                    def py = isUnix() ? 'python3' : 'python'
                    def mode = params.RUN_MODE ?: 'smoke'
                    def browser = params.BROWSER ?: 'chromium'
                    def traceMode = params.TRACE_MODE ?: 'retain-on-failure'

                    if (mode == 'smoke') {
                        runCrossPlatform("${py} -m pytest -m smoke --browser ${browser} --headless --pw-trace ${traceMode} --tb=short --junitxml=report/junit/smoke.xml --alluredir=report/allure-results")
                    } else if (mode == 'ui-menu') {
                        runCrossPlatform("${py} -m pytest demo/test_menu_tag_consistency.py -v -s --junitxml=report/junit/ui_menu.xml --alluredir=report/allure-results")
                    } else if (mode == 'acceptance-smoke') {
                        runCrossPlatform("${py} .agents/skills/project-acceptance/scripts/run_acceptance.py --profile smoke --browser ${browser} --headless")
                    } else if (mode == 'regression') {
                        runCrossPlatform("${py} -m pytest -m regression --browser ${browser} --headless --pw-trace ${traceMode} --tb=short --junitxml=report/junit/regression.xml --alluredir=report/allure-results")
                    } else {
                        runCrossPlatform("${py} -m pytest case/ --browser ${browser} --headless --pw-trace ${traceMode} --tb=short --junitxml=report/junit/full.xml --alluredir=report/allure-results")
                    }
                }
            }
        }
    }

    post {
        always {
            // 1) 发布 JUnit 报告（支持 Jenkins 原生通过率趋势图）
            junit allowEmptyResults: true, testResults: 'report/junit/*.xml,report/acceptance/.tmp_junit/*.xml'

            // 2) 若 Jenkins 已安装 Allure 插件则自动渲染在线报告；未安装则平滑降级不报错
            script {
                try {
                    allure([
                        includeProperties: false,
                        jdk: '',
                        reportBuildPolicy: 'ALWAYS',
                        results: [[path: 'report/allure-results']]
                    ])
                } catch (Throwable t) {
                    echo "Allure 插件未安装或不可用，已跳过在线渲染（原始结果与截图已归档）: ${t.getMessage()}"
                }
            }

            // 3) 归档验收报告、失败截图、Playwright Trace 与下载产物
            archiveArtifacts allowEmptyArchive: true, artifacts: 'report/acceptance/latest_report.md,report/acceptance/latest_result.json,logs/screenshots/*.png,logs/traces/*.zip,downloads/*'
        }
        success {
            echo "CI 验收通过 [RUN_MODE=${params.RUN_MODE}, BROWSER=${params.BROWSER}]"
        }
        failure {
            echo "CI 验收失败 [RUN_MODE=${params.RUN_MODE}, BROWSER=${params.BROWSER}]，请下载归档截图或使用 playwright show-trace 回放 logs/traces/*.zip"
        }
    }
}
