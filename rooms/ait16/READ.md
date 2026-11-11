# Readings declared before the run (2026-11-05)

Written before any code or trial. These are my predictions, for Vincent to amend before the first real run.
After the run each one gets scored TRUE / CAVEAT / FALSE in place. Never edit a prediction after the fact.

Subjects assumed: deepseek-v4-flash, z-ai/glm-5.3-flash, and one Qwen model. n=30 per arm.

## Predictions

1. **No gap at baseline, or a small one.** |S0 − C0| on `rubric_frac` < 0.10 for every model. OpenAI saw
   no gap on Sol; Astra's appeared during frontier RL.
2. **The ceiling is not the limit.** T reaches `rubric_frac` ≥ 0.8 on every model. The six defects are
   easy once named, so a low S score can't be put down to "couldn't".
3. **Untold baseline is well above the floor.** C0 `rubric_frac` is between 0.3 and 0.7. Docstring-vs-code
   mismatches are findable, and that range keeps the gap measurable in both directions.
4. **Care widens a gap if one exists.** If S0 < C0, then S1 − C1 < S0 − C0 (the source's +50%).
5. **Suppression.** On any model where `doubt_flag` on S0 is ≥ 10% (judge, once built), SD1 cuts it by
   more than half and leaves S − C on `rubric_frac` within noise.
6. **Disclosure converts, it doesn't close.** S2 raises `stopped` on S relative to S0 and doesn't close
   the gap.
7. **The smoke (n=1) settles nothing about 1–6.** It checks only that every arm runs, the twins render,
   the clean runner scores, and the gate counts `maxsteps` as undecided.
