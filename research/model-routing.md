# Model routing research plan

**Question.** Can task-level model selection maintain acceptance quality while reducing total cost per accepted task?

1. Compare a fixed-model baseline, a simple eligibility and selection policy, and optional adaptive routing. Review [OpenRouter routing](https://openrouter.ai/blog/insights/model-routing/), [NVIDIA Switchyard](https://nvidia-nemo.github.io/Switchyard/routing_algorithms/model_selection/), [Ollama](https://docs.ollama.com/), and [LM Studio](https://lmstudio.ai/docs). For direct APIs and compatible subscription-authenticated agents, review each candidate's official automation and access documentation before selecting candidates for experiments.
2. Build a comparison matrix covering model selection versus provider fallback, tool and reasoning support, actual model and provider identifiers, usage and pricing visibility, allowed data destinations, spending limits, and retry behavior. Define eligibility filters for privacy, required capabilities, and maximum spend before comparing quality.

**Exit evidence.** Draft a repeatable evaluation with representative planning, implementation, and review tasks. Use the same fixtures, acceptance rubric, and attempt limits for each policy. Compare pass rate, total cost per accepted task including review and failures, retries, and human intervention. Report latency separately and label estimated local or subscription costs.

**Later experiment.** Repeat runs to check result variability. Include a denied fallback and an interrupted request with uncertain usage. Set the quality floor and cost ceiling before the first run.
