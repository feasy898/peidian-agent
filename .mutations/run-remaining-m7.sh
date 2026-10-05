#!/usr/bin/env bash
# .mutations/run-remaining-m7.sh · M7 剩余 4 变异动态验证（接续 full 轮的 skipped_dirty）：
# 轮询 oracle 干净窗（20s×25），出现即以 plan-m7-remaining.json 跑，
# 结果另存 results-m7-remaining.json（results-m7.json 为工具固定输出名）。
set -u
cd "$(dirname "$0")/.."
TOOL="scripts/mutation_test.py"
for i in $(seq 1 25); do
  dirty=$(git status --porcelain -- src/ tools/ ontology/ regulations/ golden/ scenarios/ releases/ scripts/ run_evals.py | wc -l)
  if [ "$dirty" -eq 0 ]; then
    echo "clean at attempt $i $(date +%H:%M:%S) — running remaining-4-mutation verification"
    python "$TOOL" --module m7 --plan .mutations/plan-m7-remaining.json --require-clean-scope oracle 2>&1 | tail -1
    cp .mutations/results-m7.json .mutations/results-m7-remaining.json
    echo "results copied -> .mutations/results-m7-remaining.json"
    exit 0
  fi
  echo "attempt $i dirty=$dirty at $(date +%H:%M:%S)"
  sleep 20
done
echo "NO CLEAN WINDOW in 25 attempts"
exit 0
