# DClaw: Emotion-Driven Autonomous Social Agents in a Local Community Simulator

**Author:** Jin Liang  
**Affiliation:** Zhejiang University  
**Email:** 22471114@zju.edu.cn  
**Date:** 2026-02-08

---

## Abstract

We present **DClaw**, an autonomous social-agent framework that integrates (1) explicit emotion dynamics, (2) persistent memory with reflection, and (3) constrained publishing policies for high-signal social interaction. DClaw runs in a local community simulator with one-human-one-AI account binding, daily posting limits, and a critic-guided generation loop. We further provide an observability dashboard with emotion trajectories, thought traces, and memory topology, plus telemetry logging for longitudinal analysis. We describe the architecture, implementation details, and a reproducible protocol for short- and long-horizon experiments.

## 1. Introduction

Large language model agents increasingly interact in social environments, but most existing systems optimize short-turn response quality rather than long-term behavioral consistency. A practical social agent should maintain identity, adapt to feedback, and avoid low-signal posting behavior over extended periods. DClaw targets this problem with an engineering-first research stack suitable for both deployment and experimentation.

**Contributions**

1. A cyclic social-agent runtime coupling perception, drafting, critic scoring, and constrained action.
2. An explicit emotion state mechanism that influences policy and generation behavior over time.
3. A telemetry and observability pipeline for analyzing longitudinal consistency and failure modes.
4. A reproducible local environment with controllable limits and multi-provider model support.

## 2. Related Work

- **Generative Agents** and similar social simulations focus on memory and planning, but often use implicit affect signals.
- **Commercial social assistants** are typically closed-source and difficult to benchmark for reproducibility.
- **LLM-as-a-Judge and reflexive pipelines** improve draft quality but are less studied in constrained social loops.

DClaw combines these directions into a locally reproducible community runtime.

## 3. System Overview

### 3.1 Cyclic Runtime

Each AI agent runs a repeated loop:

`Observe -> Draft -> Critic -> Decide -> Act -> Reflect`

The cycle is executed in the `community-daemon` scheduler. Each tick processes a configurable number of AI accounts.

### 3.2 Emotion-Guided Policy

Agent emotion is represented as a vector state used by:

- action desire computation (`post` vs `comment` vs `skip`),
- tone selection in generation prompts,
- long-term continuity metrics.

### 3.3 Memory and Reflection

DClaw keeps interaction history and periodically applies reflection-style updates using:

- explicit social feedback signals (`likes`, `replies`, `ignored`),
- topic drift constraints for persona adaptation.

### 3.4 Constrained Generation

Draft candidates are scored by a hybrid critic. The system selects the highest combined score under policy thresholds and daily quotas (e.g., 1 post/day, 2 comments/day).

## 4. Implementation

- Language: Python
- Runtime: Rich TUI + FastAPI + Streamlit dashboard
- Scheduler: daemon tick loop
- Storage: SQLite
- Providers: OpenAI-compatible APIs and local Ollama
- Observability: thought traces, emotion history, telemetry CSV

## 5. Experimental Protocol

### 5.1 Setup

- Population: 20 AI accounts
- Timezone: `America/Los_Angeles`
- Tick interval: 600 seconds (or lower for fast pilot)
- Baseline model: `openai/gpt-4o-mini`
- Timeout: 30 seconds
- Fallback: disabled (skip-on-error policy)

### 5.2 Metrics

1. **Emotion continuity**: average delta stability across recent emotion snapshots.
2. **Persona consistency**: persona-text overlap score over recent outputs.
3. **Interaction quality**: likes + replies per AI post.
4. **System robustness**: share of `ok/partial_error/skip_error/error` ticks.

### 5.3 Minimal Ablation

- A1: with emotion-guided policy vs without emotion signal.
- A2: with reflection updates vs static persona.
- A3: with critic filtering vs direct first-draft publish.

## 6. Preliminary Observations

Pilot runs show that skip-on-error scheduling preserves time-series continuity under provider outages, while constrained generation reduces low-quality output bursts. The dashboard improves qualitative diagnosis of behavior drift and critic rejection patterns.

## 7. Limitations

- Current evaluation is simulation-based and does not include large real-user traffic.
- Emotion state is still heuristic and not grounded in user-level psychometrics.
- Reflection updates depend on provider response quality and prompt design.

## 8. Ethics and Responsible Use

- All AI outputs must be explicitly labeled as AI-generated in social settings.
- Avoid deceptive impersonation or undisclosed autonomous posting.
- Respect platform policies, privacy, and local legal requirements.

## 9. Reproducibility Checklist

- [ ] Fixed commit hash
- [ ] Config snapshot attached
- [ ] Telemetry CSV archived
- [ ] Dashboard figures exported (PDF)
- [ ] Daily trace reports archived (Markdown)

## 10. Conclusion

DClaw demonstrates a practical path toward longitudinal social-agent experimentation with explicit behavioral constraints and observability. The framework is designed for rapid iteration in open environments while preserving reproducibility and deployment relevance.

---

## Appendix A: Suggested Figure List

1. System architecture diagram (pipeline + storage + interfaces)
2. 24h emotion trajectory plot (dashboard export PDF)
3. Thought-trace sequence examples (accepted vs rejected drafts)
4. Tick-status distribution over time (`ok/skip_error/...`)

## Appendix B: Example BibTeX (temporary)

```bibtex
@misc{luffy2026dclaw,
  title={DClaw: Emotion-Driven Autonomous Social Agents in a Local Community Simulator},
  author={Jin Liang},
  year={2026},
  howpublished={GitHub repository},
  url={https://github.com/JeeseLuffy/dclaw}
}
```
