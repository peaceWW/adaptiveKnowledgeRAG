#!/usr/bin/env bash
DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
. "$DIR/_isolate.sh"
exec "$(cd "$DIR/.." && pwd)/akrag.sh" logs "$@"
