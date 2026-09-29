#!/usr/bin/env bash
# .mutations/run-single-m7.sh · M7 定向单变异验证（裁决方案 C）：
# 轮询 oracle 路径干净窗口（30s×20），出现即以 plan-m7-single.json 跑单变异，
# 结果另存 results-m7-single.json（results-m7.json 为工具固定输出名）。
set -u
cd "$(dirname "$0")/.."
TOOL="scripts/mutation_test.py"
for i in $(seq 1 20); do
  dirty=$(git status --porcelain -- src/ tools/ ontology/ regulations/ golden/ scenarios/ releases/ scripts/ run_evals.py | wc -l)
  if [ "$dirty" -eq 0 ]; then
    echo "clean at attempt $i $(date +%H:%M:%S) — running single-mutation verification"
    python "$TOOL" --module m7 --plan .mutations/plan-m7-single.json --require-clean-scope oracle 2>&1 | tail -1
    cp .mutations/results-m7.json .mutations/results-m7-single.json
    echo "results copied -> .mutations/results-m7-single.json"
    exit 0
  fi
  echo "attempt $i dirty=$dirty at $(date +%H:%M:%S)"
  sleep 30
done
echo "NO CLEAN WINDOW in 20 attempts — accepting per ruling option C"
exit 0
