# 实验结果（D）

- `memory_layer_check.{json,md}`：记忆层自检，由 `experiments/memory/memory_layer_check.py` 生成（模拟输入，可复现）。
- `outputs.template.json`：待填写的三种条件输出/标注模板，由 `experiments/memory/build_inputs.py` 生成。
- `outputs.json`：**尚未生成**。C 的 Agent 跑完并完成人工标注后放在这里。
- `metrics.{json,md,csv}`：运行 `python experiments/evaluate.py` 后生成。目前没有，因为还没有真实输出；不要手写。
