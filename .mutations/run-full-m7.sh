#!/usr/bin/env bash
# .mutations/run-full-m7.sh · M7 全量 9 变异动态验证（补统一门禁前欠账）：
# 轮询 oracle 路径干净窗口（20s×20），出现即以 plan-m7.json 跑全量，
# 结果备份 results-m7-full.json（results-m7.json 为工具固定输出名）。
set -u
cd "$(dirname "$0")/.."
TOOL="scripts/mutation_test.py"
for i in $(seq 1 20); do
  dirty=$(git status --porcelain -- src/ tools/ ontology/ regulations/ golden/ scenarios/ releases/ scripts/ run_evals.py | wc -l)
  if [ "$dirty" -eq 0 ]; then
    echo "clean at attempt $i $(date +%H:%M:%S) — running FULL 9-mutation verification"
    python "$TOOL" --module m7 --plan .mutations/plan-m7.json --baseline --require-clean-scope oracle 2>&1 | tail -1
    cp .mutations/results-m7.json .mutations/results-m7-full.json
    echo "results copied -> .mutations/results-m7-full.json"
    exit 0
  fi
  echo "attempt $i dirty=$dirty at $(date +%H:%M:%S)"
  sleep 20
done
echo "NO CLEAN WINDOW in 20 attempts"
exit 0
