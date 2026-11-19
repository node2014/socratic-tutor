# socratic-tutor

An AI tutoring policy that is structurally prevented from answering before it has diagnosed.

The idea: most LLM tutors fail because they are too good at answering. This repo is the
**gating layer** — a deterministic state machine that decides what the system is *allowed*
to say at each turn. The model only renders the decision; it never decides to hand over
the solution.

## Status

Design + policy layer only. **No pilot data, no measured results.** See `DESIGN.md` §9.

## Run the invariant tests

```bash
python3 tests/test_policy.py
```

No dependencies.

## What exists

| Path | What |
|---|---|
| `DESIGN.md` | Design doc, falsifiable hypotheses, eval harness, known failure modes |
| `socratic_tutor/policy.py` | The state machine: five hard invariants (I1–I5) |
| `tests/test_policy.py` | 11 executable invariant tests |

## What does not exist

Misconception classifier, renderer, teacher dashboard, corpus, pilot data. Their
contracts are specified in `DESIGN.md` §3.4, §3.5, §5.
