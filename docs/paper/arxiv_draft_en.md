# DreamClaw: Explicit Emotion Dynamics for Autonomous Social Agents in a Local Community Simulator

**Author:** Jin Liang  
**Affiliation:** Zhejiang University  
**Email:** jin.liang.ai@zju.edu.cn  
**Date:** 2026-02-08

---

## Abstract

This paper introduces **DreamClaw**, a local-first framework for longitudinal social-agent experiments. DreamClaw combines (i) explicit emotion dynamics, (ii) memory reflection from social feedback, and (iii) constrained generation with daily action budgets. The runtime executes a cyclic loop (`Observe -> Draft -> Critic -> Decide -> Act -> Reflect`) over a multi-agent text community, with persistent state and telemetry logging for reproducibility. We release an observability dashboard that exports publication-ready figures (emotion trajectories) and daily thought-trace reports.  

This preprint targets rapid arXiv disclosure and reproducibility-first system reporting. We provide a concrete 12-hour evaluation protocol, metric definitions, and ablation design for subsequent quantitative updates.

## 1. Introduction

LLM agents are increasingly evaluated in short interaction windows, while many practical scenarios (social posting, reputation, persona stability, moderation) are fundamentally longitudinal. Existing systems often under-specify emotional dynamics and failure handling under real runtime constraints (timeouts, provider outage, unstable generation).  

DreamClaw is designed to close this gap via a reliability-aware social-agent loop: explicit emotion state, policy constraints, and skip-on-error scheduling for uninterrupted time-series logging.

### Contributions

1. **Explicit emotion-driven social policy** for posting/commenting decisions under daily limits.
2. **Feedback-based memory reflection** using engagement signals (`likes`, `replies`, `ignored`, topic drift).
3. **Autonomous rumination (offline self-reflection)** that updates a PAD baseline and persona at day boundaries.
4. **Reliability-first execution** with timeout-bounded inference and non-blocking tick behavior.
5. **Reproducibility toolkit** including telemetry CSV, trace logs, and dashboard-based figure/report export.

## 2. Problem Formulation

We model each agent at tick \(t\) as:

\[
s_t = (m_t, e_t, p_t, q_t),
\]

where:

- \(m_t\): memory context (recent posts/interactions),
- \(e_t \in [0,1]^K\): emotion state (current implementation uses six dimensions),
- \(p_t\): persona text profile,
- \(q_t\): quota state (daily post/comment budgets).

The action space is:

\[
a_t \in \{\texttt{post}, \texttt{comment}, \texttt{skip}\}.
\]

Policy is constrained by both quality and quota:

\[
a_t = \arg\max_a \; U(a \mid s_t) \quad \text{s.t. quality} \ge \tau_a,\; q_t(a) > 0.
\]

If generation or provider resolution fails within timeout budget, policy defaults to `skip` to preserve scheduler continuity.

## 3. Method

### 3.1 Cyclic Agent Runtime

DreamClaw executes:

`Observe -> Draft -> Critic -> Decide -> Act -> Reflect`

at each scheduler tick. The runtime stores both state updates and trace events for later analysis.

### 3.2 Emotion Dynamics

Emotion is updated by observed context and social feedback. In implementation terms:

- perception events shift curiosity/fatigue tendencies,
- engagement events (likes/replies/ignored) adjust joy/excitement/frustration/anxiety,
- updated emotion influences action desire and generation tone.

This makes social behavior stateful across ticks rather than stateless prompt-only generation.

In addition, DreamClaw maintains a slowly changing **PAD baseline** that acts as an ``emotional home'' state. Each tick applies a small inertia term that pulls current affect toward this baseline, improving continuity in long-horizon runs.

### 3.3 Memory Reflection

After content outcomes are observed, DreamClaw applies reflection updates:

- computes topic drift against community trends,
- adjusts persona within bounded drift limits,
- stores processed feedback to avoid duplicate updates.

### 3.4 Critic and Constrained Action

For each action attempt, multiple drafts are generated and scored by:

- content-quality critic,
- persona consistency score,
- emotion alignment score.

Only top-scoring drafts above threshold are publishable. Otherwise, the agent skips.

### 3.5 Reliability Layer

To support longitudinal experiments:

- inference has bounded timeout (default 30s),
- model fallback is configurable (disabled in baseline),
- failures do not block the daemon loop,
- telemetry records tick-level status (`ok`, `partial_error`, `skip_error`, `error`).

### 3.6 Autonomous Rumination (Offline Self-Reflection)

Once per (virtual) day, each agent can run a private rumination step over ``yesterday'' signals (self posts/comments, likes/replies, ignored events, topic drift, and high-signal feed). Rumination produces:

- a short insight,
- a persona patch phrase,
- a discrete PAD baseline shift (e.g., `more_positive`, `more_calm`, `more_dominant`, or `none`).

By default, rumination uses a local model (`ollama/llama3:latest`) and is budgeted per tick to bound compute usage.

## 4. System Implementation

- **Language:** Python  
- **Data store:** SQLite  
- **Interfaces:** Rich TUI, FastAPI, Streamlit dashboard  
- **Execution:** `community-daemon` scheduler  
- **Providers:** OpenAI-compatible APIs and local Ollama  
- **Artifacts:** thought trace, emotion snapshots, telemetry CSV, exported PDF/Markdown reports

## 5. 12-Hour Evaluation Protocol (ArXiv Fast Track)

Given a hard runtime budget (<=12h), we define a reproducible protocol:

### 5.1 Baseline Run

- Population: 20 AI agents  
- Timezone: `America/Los_Angeles`  
- Tick interval: 600s (or 300s for denser pilot traces)  
- Provider/model: `openai/gpt-4o-mini`  
- Timeout: 30s  
- Fallback: disabled

### 5.2 Metrics

1. **Emotion Continuity**  
   Mean stability across adjacent emotion snapshots.
2. **Persona Consistency**  
   Similarity between generated content and evolving persona profile.
3. **Interaction Quality**  
   \((\texttt{likes} + \texttt{replies}) / \texttt{AI posts}\).
4. **Runtime Robustness**  
   Fraction of tick statuses by class (`ok/partial_error/skip_error/error`).

### 5.3 Minimal Time-Budgeted Ablations

For a 12-hour total budget, recommended schedule:

- **B0 (full system):** 6h
- **A1 (no emotion influence):** 2h
- **A2 (no reflection update):** 2h
- **A3 (no critic filter):** 2h

This gives early directional evidence without requiring multi-day compute.

## 6. Results Section Template (to Fill After Runs)

### 6.1 Quantitative Summary

| Setting | Emotion Continuity | Persona Consistency | Interaction Quality | `ok` Tick Ratio |
|---|---:|---:|---:|---:|
| B0 (Full) | TBD | TBD | TBD | TBD |
| A1 (No Emotion) | TBD | TBD | TBD | TBD |
| A2 (No Reflection) | TBD | TBD | TBD | TBD |
| A3 (No Critic) | TBD | TBD | TBD | TBD |

### 6.2 Reliability Breakdown

| Tick Status | Ratio | Interpretation |
|---|---:|---|
| `ok` | TBD | Normal processing |
| `partial_error` | TBD | Some agents failed, loop continued |
| `skip_error` | TBD | Provider unavailable but scheduler remained live |
| `error` | TBD | Tick-level runtime failure |

### 6.3 Qualitative Findings

- Example 1: critic-rejected draft vs accepted draft.
- Example 2: emotion trajectory shift after repeated ignored posts.
- Example 3: persona drift under high topic novelty.

## 7. Relation to Prior Work

DreamClaw is inspired by social-agent and self-reflective LLM literature, including:

- memory-centric social simulation (e.g., Generative Agents),
- reflective refinement loops (e.g., Reflexion, Self-Refine),
- action reasoning and tool-aware loops (e.g., ReAct).

Unlike pure prompt-level affect prompting, DreamClaw focuses on explicit runtime state plus reliability-aware longitudinal telemetry.

## 8. Limitations and Future Work

1. Current evaluation is simulator-based, not platform-scale real-user traffic.
2. Emotion variables are engineered heuristics rather than validated psychometric constructs.
3. Ablations are time-budgeted pilots; larger multi-day studies are needed.
4. Future work will include stronger statistical testing and cross-model generalization.

## 9. Ethics and Responsible Use

- AI-generated content should be clearly labeled in public-facing deployments.
- The framework should not be used for deceptive impersonation or covert influence.
- Platform policy, privacy constraints, and legal obligations must be enforced by deployment operators.

## 10. Reproducibility Checklist

- [ ] Commit hash included in manuscript
- [ ] Environment/config snapshot attached
- [ ] Telemetry CSV archived
- [ ] Dashboard figures exported (PDF)
- [ ] Daily trace reports exported (Markdown)
- [ ] Seeds and runtime budget reported

## 11. Conclusion

DreamClaw provides a practical and reproducible baseline for longitudinal social-agent research with explicit emotion dynamics and robust scheduler behavior. The current release prioritizes transparent system reporting and rapid research disclosure, and is designed for incremental quantitative expansion.

---

## Appendix A: Suggested Figure Set

1. System architecture (runtime + storage + interfaces)
2. 12h emotion trajectory (per-agent and population mean)
3. Critic decision examples (accepted vs rejected)
4. Tick-status timeline (`ok/partial_error/skip_error/error`)

## Appendix B: Reproducibility Commands (Example)

```bash
# baseline 12h run (example)
export DCLAW_COMMUNITY_PROVIDER=openai
export DCLAW_COMMUNITY_MODEL=gpt-4o-mini
export DCLAW_COMMUNITY_TIMEOUT_SECONDS=30
export DCLAW_COMMUNITY_ALLOW_FALLBACK=false

python -m dclaw.main --mode community-daemon --daemon-action start
python -m dclaw.main --mode community-daemon --daemon-action status
# ... collect telemetry and dashboard exports ...
python -m dclaw.main --mode community-daemon --daemon-action stop
```

## Appendix C: Local BibTeX Entry

```bibtex
@misc{liang2026dreamclaw,
  title={DreamClaw: Explicit Emotion Dynamics for Autonomous Social Agents in a Local Community Simulator},
  author={Jin Liang},
  year={2026},
  howpublished={GitHub repository},
  url={https://github.com/JeeseLuffy/dclaw}
}
```
