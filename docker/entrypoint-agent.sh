#!/usr/bin/env bash
set -euo pipefail

: "${JENKINS_URL:?JENKINS_URL is required (e.g. http://jenkins:8080)}"
: "${JENKINS_AGENT_NAME:?JENKINS_AGENT_NAME is required}"
: "${JENKINS_SECRET:?JENKINS_SECRET is required}"

WORKDIR="${JENKINS_AGENT_WORKDIR:-/home/jenkins/agent}"
AGENT_JAR="/home/jenkins/agent.jar"

mkdir -p "${WORKDIR}"

echo "[Agent] Downloading agent.jar from ${JENKINS_URL}/jnlpJars/agent.jar ..."
for i in $(seq 1 15); do
    if curl -fsSL "${JENKINS_URL%/}/jnlpJars/agent.jar" -o "${AGENT_JAR}"; then
        break
    fi
    echo "[Agent] Retry ${i}/15 waiting for Jenkins controller..."
    sleep 2
done

echo "[Agent] Connecting '${JENKINS_AGENT_NAME}' to ${JENKINS_URL} via WebSocket (workDir=${WORKDIR})..."
exec java -jar "${AGENT_JAR}" \
    -url "${JENKINS_URL}" \
    -secret "${JENKINS_SECRET}" \
    -name "${JENKINS_AGENT_NAME}" \
    -workDir "${WORKDIR}" \
    -webSocket
