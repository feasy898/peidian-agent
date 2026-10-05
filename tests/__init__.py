# -*- coding: utf-8 -*-
"""tests · EVAL 资产包标记（EVAL-SCHEMA.md §4 插件协议配套）。

存在意义：使 ``import tests.fixtures.<plugin>`` 在仓库根运行时（sys.path[0]=仓库根）
解析到**本仓库**的 tests 包——否则 site-packages 中的同名第三方 ``tests`` 包会抢占
模块名，tests 侧执行器插件（如 tests/fixtures/m3_eval_plugin.py）将无法被
run_evals.py 的 suite.executors 机制装载。除包标记外不含任何逻辑。
"""
