# DClaw (Workshop Short Version): Reliability-Aware Emotion Dynamics for Social LLM Agents

## Abstract

We present **DClaw**, a local community simulator for longitudinal LLM-agent studies. DClaw combines explicit emotion state, feedback-based persona reflection, and constrained publishing policy. Unlike one-shot chat settings, DClaw focuses on repeated social behavior under runtime uncertainty (timeouts/provider errors). We provide a 12-hour reproducible protocol with tick-level telemetry and dashboard exports for rapid experimental reporting.

## 1. Motivation

Most LLM-agent evaluations are short-horizon and prompt-centric. Social agents in practice must:

- keep behavioral continuity,
- adapt to engagement signals,
- remain operational when generation fails.

DClaw is built as an engineering-first baseline to make these properties measurable.

## 2. Method

### 2.1 Agent Loop

Each agent executes:

`Observe -> Draft -> Critic -> Decide -> Act -> Reflect`

per scheduler tick.

### 2.2 Emotion and Reflection

- Emotion state changes from perception and engagement events.
- Reflection uses `likes/replies/ignored/topic drift` signals to update persona under bounded drift.

### 2.3 Constrained Action

- Multiple drafts are generated.
- Hybrid scoring combines quality, persona consistency, and emotion alignment.
- Publish only if thresholds and daily quotas are satisfied.

### 2.4 Reliability Policy

- 30s timeout per model call.
- Optional fallback (disabled in baseline).
- If unavailable/error: `skip` action instead of blocking loop.

## 3. Experimental Setup (12h Budget)

- 20 AI agents, public timeline
- Baseline: `openai/gpt-4o-mini`
- Tick interval: 600s (or 300s for dense pilot)
- Telemetry statuses: `ok`, `partial_error`, `skip_error`, `error`

### Minimal Ablations

- B0 full system (6h)
- A1 no emotion policy (2h)
- A2 no reflection update (2h)
- A3 no critic filter (2h)

## 4. Metrics

1. Emotion continuity
2. Persona consistency
3. Interaction quality
4. Runtime robustness

## 5. Key Artifact Outputs

- `experiment_telemetry.csv` (time-series)
- emotion trajectory PDF (dashboard export)
- daily trace markdown report

These artifacts are intended for reproducible workshop/demo submissions.

## 6. Limitations

- Simulator environment (not large real-user deployment)
- Heuristic emotion variables
- Time-budgeted pilot evaluation

## 7. Conclusion

DClaw provides a practical baseline for studying social LLM agents under explicit emotion dynamics and reliability constraints. The framework is optimized for quick iterative experiments and reproducibility-first reporting.
