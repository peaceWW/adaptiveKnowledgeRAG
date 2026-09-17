#!/usr/bin/env bash
ROOT="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
. "$ROOT/scripts/linux/_isolate.sh"
exec "$ROOT/scripts/akrag.sh" status "$@"
