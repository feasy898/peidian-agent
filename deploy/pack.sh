#!/usr/bin/env bash
# deploy/pack.sh · 从 git 仓打发布 tar（不含 .venv/node_modules/__pycache__）
# 用法：bash deploy/pack.sh   →  产物 peidian-agent-release-<shashort>.tar.gz（/tmp 下）
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
SHA="$(git rev-parse --short=8 HEAD)"
OUT="/tmp/peidian-agent-release-${SHA}.tar.gz"
# 发布内容：web/ 前端与服务端 + fault/ 引擎与桥 + dsl/ （数据源可再导出）+ 部署件
git archive --format=tar.gz -o "$OUT" HEAD \
  peidian-agent/web peidian-agent/fault peidian-agent/dsl peidian-agent/deploy peidian-agent/pyproject.toml peidian-agent/README.md 2>/dev/null \
  || git archive --format=tar.gz -o "$OUT" HEAD peidian-agent/web peidian-agent/fault peidian-agent/dsl peidian-agent/deploy
echo "packed: $OUT ($(du -h "$OUT" | cut -f1))"
sha256sum "$OUT"
