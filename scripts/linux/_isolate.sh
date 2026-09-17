#!/usr/bin/env bash
# 项目级 Python 隔离：只用本仓库 .venv，清掉全局 PYTHONPATH / PIP_TARGET，避免多项目串包。
# 由管理脚本 source，不要直接执行。
AKRAG_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
unset PYTHONPATH PYTHONHOME PIP_TARGET PIP_USER PYTHONSTARTUP
export PYTHONNOUSERSITE=1
export VIRTUAL_ENV="$AKRAG_ROOT/.venv"
export UV_PROJECT_ENVIRONMENT="$AKRAG_ROOT/.venv"
if [[ -x "$VIRTUAL_ENV/bin/python" ]]; then
  export PATH="$VIRTUAL_ENV/bin:$PATH"
fi
