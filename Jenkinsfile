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
            description: '目标浏览器内核（chromium 缺失内置版本时自动回退本机 Chrome/Edge）'
        )
        choice(
            name: 'TRACE_MODE',
            choices: ['retain-on-failure', 'on', 'off'],
            description: 'Playwright Trace 录制策略（retain-on-failure 仅失败落盘）'
        )
        string(
            name: 'FRONTEND_URL',
            defaultValue: 'http://localhost:5173',
            description: '被测前端测试地址'
        )
        string(
            name: 'API_URL',
            defaultValue: 'http://127.0.0.1:5050',
            description: '被测后端接口地址'
        )
        string(
            name: 'PLAYWRIGHT_BROWSERS_PATH',
            defaultValue: 'C:/Users/Administrator/AppData/Local/ms-playwright',
            description: 'Playwright 浏览器内核共享缓存目录（解决 Windows Jenkins 服务账户看不到桌面用户缓存的问题）'
        )
    }

    environment {
        PYTHONUTF8 = '1'
        PYTHONIOENCODING = 'utf-8'
        PLAYWRIGHT_BROWSERS_PATH = "${params.PLAYWRIGHT_BROWSERS_PATH}"
        ACCEPTANCE_FRONTEND_URL = "${params.FRONTEND_URL}"
        ACCEPTANCE_API_URL = "${params.API_URL}"
        ACCEPTANCE_BROWSER = "${params.BROWSER}"
        ACCEPTANCE_TRACE_MODE = "${params.TRACE_MODE}"
    }

    stages {
        stage('1. Environment Check') {
            steps {
                bat '''
                    chcp 65001 > nul
                    echo ===== Python & Dependency Check =====
                    python --version
                    python -m pip install -q -r requirements.txt
                    python -c "import shutil, pathlib; [shutil.rmtree(p, ignore_errors=True) for p in ('report/junit', 'report/allure-results')]; [pathlib.Path(p).mkdir(parents=True, exist_ok=True) for p in ('report/junit', 'report/allure-results')]"
                '''
            }
        }

        stage('2. Service Preflight') {
            steps {
                bat '''
                    chcp 65001 > nul
                    python -c "import os, requests; fe=os.environ['ACCEPTANCE_FRONTEND_URL']; be=os.environ['ACCEPTANCE_API_URL']; r1=requests.get(fe, timeout=5); r2=requests.get(be + '/api/health', timeout=5); print('Frontend:', fe, r1.status_code); print('Backend:', be, r2.status_code, r2.text); assert r1.status_code < 500 and r2.status_code == 200"
                '''
            }
        }

        stage('3. Run Playwright Tests') {
            steps {
                script {
                    def mode = params.RUN_MODE
                    def browser = params.BROWSER
                    def traceMode = params.TRACE_MODE

                    if (mode == 'smoke') {
                        bat """
                            chcp 65001 > nul
                            python -m pytest -m smoke --browser ${browser} --headless --pw-trace ${traceMode} --tb=short --junitxml=report/junit/smoke.xml --alluredir=report/allure-results
                        """
                    } else if (mode == 'ui-menu') {
                        bat """
                            chcp 65001 > nul
                            python -m pytest demo/test_menu_tag_consistency.py -v -s --junitxml=report/junit/ui_menu.xml --alluredir=report/allure-results
                        """
                    } else if (mode == 'acceptance-smoke') {
                        bat """
                            chcp 65001 > nul
                            python .agents/skills/project-acceptance/scripts/run_acceptance.py --profile smoke --browser ${browser} --headless
                        """
                    } else if (mode == 'regression') {
                        bat """
                            chcp 65001 > nul
                            python -m pytest -m regression --browser ${browser} --headless --pw-trace ${traceMode} --tb=short --junitxml=report/junit/regression.xml --alluredir=report/allure-results
                        """
                    } else {
                        bat """
                            chcp 65001 > nul
                            python -m pytest case/ --browser ${browser} --headless --pw-trace ${traceMode} --tb=short --junitxml=report/junit/full.xml --alluredir=report/allure-results
                        """
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
