#!/usr/bin/env bash
# Adaptive Knowledge RAG — Linux/macOS 项目管理脚本
# 用法: ./scripts/akrag.sh <deploy|start|stop|restart|status|infra-up|infra-down|logs> [--with-infra] [--all]

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="$ROOT/.run"
FRONTEND_DIR="$ROOT/frontend"
VENV_DIR="$ROOT/.venv"
VENV_BIN="$VENV_DIR/bin"
VENV_PYTHON="$VENV_BIN/python"
BACKEND_PID_FILE="$RUN_DIR/backend.pid"
FRONTEND_PID_FILE="$RUN_DIR/frontend.pid"
BACKEND_PORT=8000
FRONTEND_PORT=5173

COMMAND="${1:-status}"
shift || true

WITH_INFRA=0
STOP_ALL=0
for arg in "$@"; do
  case "$arg" in
    --with-infra|-WithInfra) WITH_INFRA=1 ;;
    --all|-All) STOP_ALL=1 ;;
    *) ;;
  esac
done

info() { printf '\033[36m[akrag]\033[0m %s\n' "$*"; }
ok() { printf '\033[32m[akrag]\033[0m %s\n' "$*"; }
warn() { printf '\033[33m[akrag]\033[0m %s\n' "$*"; }
err() { printf '\033[31m[akrag]\033[0m %s\n' "$*"; }

have_cmd() { command -v "$1" >/dev/null 2>&1; }

isolate_project_env() {
  # 绑定本仓库 .venv，去掉全局 PYTHONPATH/PIP_TARGET，避免多项目串包
  unset PYTHONPATH PYTHONHOME PIP_TARGET PIP_USER PYTHONSTARTUP
  export PYTHONNOUSERSITE=1
  export VIRTUAL_ENV="$VENV_DIR"
  export UV_PROJECT_ENVIRONMENT="$VENV_DIR"
  if [[ -x "$VENV_PYTHON" ]]; then
    export PATH="$VENV_BIN:$PATH"
  fi
}

assert_project_venv() {
  if [[ ! -x "$VENV_PYTHON" ]]; then
    err "未找到项目虚拟环境: $VENV_PYTHON。请先执行 ./deploy.sh（会在本仓库创建 .venv）"
    exit 1
  fi
}

isolate_project_env

port_pids() {
  local port="$1"
  if have_cmd lsof; then
    lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true
  elif have_cmd ss; then
    ss -lptn "sport = :$port" 2>/dev/null | sed -n 's/.*pid=\([0-9]*\).*/\1/p' | sort -u
  else
    true
  fi
}

port_listening() {
  local pids
  pids="$(port_pids "$1")"
  [[ -n "${pids// }" ]]
}

stop_pids() {
  local pids="$1"
  if [[ -n "${pids// }" ]]; then
    # shellcheck disable=SC2086
    kill $pids >/dev/null 2>&1 || true
    sleep 0.4
    # shellcheck disable=SC2086
    kill -9 $pids >/dev/null 2>&1 || true
  fi
}

stop_port() { stop_pids "$(port_pids "$1")"; }

stop_pidfile() {
  local file="$1"
  if [[ -f "$file" ]]; then
    local pid
    pid="$(tr -d '[:space:]' < "$file" || true)"
    if [[ -n "$pid" ]] && kill -0 "$pid" >/dev/null 2>&1; then
      kill "$pid" >/dev/null 2>&1 || true
      sleep 0.3
      kill -9 "$pid" >/dev/null 2>&1 || true
    fi
    rm -f "$file"
  fi
}

docker_ok() {
  have_cmd docker || return 1
  if have_cmd timeout; then
    timeout 4 docker info >/dev/null 2>&1
  else
    docker info >/dev/null 2>&1
  fi
}

compose() {
  (
    cd "$ROOT"
    if docker compose version >/dev/null 2>&1; then
      docker compose "$@"
    else
      docker-compose "$@"
    fi
  )
}

ensure_env() {
  local prefer_sqlite="$1"
  if [[ ! -f "$ROOT/.env" ]]; then
    if [[ ! -f "$ROOT/.env.example" ]]; then
      err "缺少 .env.example，无法生成配置文件"
      exit 1
    fi
    cp "$ROOT/.env.example" "$ROOT/.env"
    if [[ "$prefer_sqlite" == "1" ]]; then
      sed -i.bak 's|^DATABASE_URL=.*|DATABASE_URL=sqlite+aiosqlite:///./data/akrag.db|' "$ROOT/.env"
      rm -f "$ROOT/.env.bak"
      info "未检测到 Docker，已将 DATABASE_URL 设为 SQLite"
    else
      info "已从 .env.example 创建 .env"
    fi
  fi
}

cmd_infra_up() {
  if ! docker_ok; then
    err "Docker 不可用，无法启动基础设施"
    exit 1
  fi
  info "启动 docker compose 基础设施"
  compose up -d
  ok "基础设施已启动"
}

cmd_infra_down() {
  if ! docker_ok; then
    warn "Docker 不可用，跳过 infra-down"
    return 0
  fi
  info "停止 docker compose 基础设施"
  compose down
  ok "基础设施已停止"
}

cmd_deploy() {
  info "开始部署 / 安装依赖"
  if ! have_cmd uv; then
    err "未找到 uv。请先安装: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
  fi
  if ! have_cmd npm; then
    err "未找到 npm / Node.js。请安装 Node.js 18+"
    exit 1
  fi

  local use_infra=0
  if [[ "$WITH_INFRA" -eq 1 ]] && docker_ok; then
    use_infra=1
  elif [[ "$WITH_INFRA" -eq 1 ]]; then
    warn "已指定 --with-infra，但 Docker 不可用，将按本地降级模式安装"
  fi

  if [[ "$use_infra" -eq 1 ]]; then
    ensure_env 0
  else
    ensure_env 1
  fi
  mkdir -p "$ROOT/data"

  info "安装 Python 依赖到本仓库 .venv (uv sync)"
  (
    cd "$ROOT"
    export UV_PROJECT_ENVIRONMENT="$VENV_DIR"
    uv sync
  )
  isolate_project_env
  assert_project_venv
  info "项目解释器: $VENV_PYTHON"
  info "安装前端依赖 (npm install)"
  (cd "$FRONTEND_DIR" && npm install)

  if [[ "$use_infra" -eq 1 ]]; then
    cmd_infra_up
  fi
  ok "部署完成。接下来执行: ./scripts/akrag.sh start"
}

start_backend() {
  if port_listening "$BACKEND_PORT"; then
    warn "后端已在端口 $BACKEND_PORT 运行"
    return 0
  fi
  assert_project_venv
  isolate_project_env
  mkdir -p "$RUN_DIR"
  (
    cd "$ROOT"
    # 直接用项目 .venv 的 python -m uvicorn，不走全局 uv/python
    nohup "$VENV_PYTHON" -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port "$BACKEND_PORT" \
      >> "$RUN_DIR/backend.log" 2>&1 &
    echo $! > "$BACKEND_PID_FILE"
  )
  info "后端已启动 PID=$(cat "$BACKEND_PID_FILE") python=$VENV_PYTHON，日志 $RUN_DIR/backend.log"
}

start_frontend() {
  if port_listening "$FRONTEND_PORT"; then
    warn "前端已在端口 $FRONTEND_PORT 运行"
    return 0
  fi
  if ! have_cmd npm; then
    err "未找到 npm，请先执行 deploy"
    exit 1
  fi
  mkdir -p "$RUN_DIR"
  (
    cd "$FRONTEND_DIR"
    nohup npm run dev >> "$RUN_DIR/frontend.log" 2>&1 &
    echo $! > "$FRONTEND_PID_FILE"
  )
  info "前端已启动 PID=$(cat "$FRONTEND_PID_FILE")，日志 $RUN_DIR/frontend.log"
}

wait_health() {
  local i
  for i in $(seq 1 40); do
    if curl -fsS "http://127.0.0.1:${BACKEND_PORT}/health" >/dev/null 2>&1; then
      ok "后端健康检查通过 http://127.0.0.1:${BACKEND_PORT}/health"
      return 0
    fi
    sleep 0.5
  done
  warn "后端尚未就绪，请查看 $RUN_DIR/backend.log"
}

cmd_start() {
  if [[ "$WITH_INFRA" -eq 1 ]]; then
    if docker_ok; then
      cmd_infra_up
    else
      warn "Docker 不可用，跳过基础设施，应用将降级运行"
    fi
  fi
  start_backend
  start_frontend
  wait_health
  ok "应用已启动（监听 0.0.0.0，局域网可访问）"
  echo "  前端:  http://localhost:${FRONTEND_PORT}/  （或 http://<本机IP>:${FRONTEND_PORT}/）"
  echo "  后端:  http://0.0.0.0:${BACKEND_PORT}/"
  echo "  API:   http://localhost:${BACKEND_PORT}/docs"
}

cmd_stop() {
  info "停止应用进程"
  stop_pidfile "$FRONTEND_PID_FILE"
  stop_pidfile "$BACKEND_PID_FILE"
  stop_port "$FRONTEND_PORT"
  stop_port "$BACKEND_PORT"
  if [[ "$STOP_ALL" -eq 1 ]]; then
    cmd_infra_down
  fi
  ok "应用已停止"
}

cmd_status() {
  local backend="stopped" frontend="stopped"
  port_listening "$BACKEND_PORT" && backend="running"
  port_listening "$FRONTEND_PORT" && frontend="running"
  echo "backend  : $backend   http://0.0.0.0:${BACKEND_PORT}/"
  echo "frontend : $frontend   http://0.0.0.0:${FRONTEND_PORT}/"
  if [[ -x "$VENV_PYTHON" ]]; then
    echo "python   : $VENV_PYTHON"
  else
    echo "python   : missing (.venv). Run ./deploy.sh first"
  fi
  if have_cmd docker; then
    echo "docker   : installed"
  else
    echo "docker   : not installed (SQLite / in-memory fallback)"
  fi
}

cmd_logs() {
  mkdir -p "$RUN_DIR"
  echo "---- backend.log ----"
  tail -n 40 "$RUN_DIR/backend.log" 2>/dev/null || echo "(empty)"
  echo "---- frontend.log ----"
  tail -n 40 "$RUN_DIR/frontend.log" 2>/dev/null || echo "(empty)"
}

cd "$ROOT"
case "$COMMAND" in
  deploy) cmd_deploy ;;
  start) cmd_start ;;
  stop) cmd_stop ;;
  restart) cmd_stop; sleep 1; cmd_start ;;
  status) cmd_status ;;
  infra-up) cmd_infra_up ;;
  infra-down) cmd_infra_down ;;
  logs) cmd_logs ;;
  *)
    err "未知命令: $COMMAND"
    echo "用法: $0 <deploy|start|stop|restart|status|infra-up|infra-down|logs> [--with-infra] [--all]"
    exit 1
    ;;
esac
