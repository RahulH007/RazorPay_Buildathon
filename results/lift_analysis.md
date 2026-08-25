# RecoverOS - Incremental Lift Measurement

- Population per run: **2,000 contacts**
- Runs: **10** (seeds 20260825-20260834)
- Holdout: **20%**, never contacted
- Observation window: **72h**
- Assumed merchant margin: **20%**

## Result

| Metric | Value |
|---|---|
| Treated recovery rate | 62.7% |
| Control recovery rate (uncontacted) | 28.8% |
| **Incremental lift** | **+33.9 pp** (95% CI +33.0 to +34.9) |
| Incremental GMV per run | Rs 4,204,956 |
| Value at 20% margin | Rs 840,991 |
| Channel spend per run | Rs 1,189.95 |
| Incremental recoveries per run | 545 payments |
| **Cost per incremental recovery** | **Rs 2.18** |

## Why the control rate is not zero

A meaningful share of failed payments recover with no intervention at
all - transient bank faults especially. The control arm measures that,
and only the difference is claimed. Reporting the treated rate alone
would overstate this system's contribution by 28.8 percentage points.

## What actually constrains this

Channel spend is small because messaging in India is cheap - well under
a rupee to reach a customer holding a payment worth thousands. The
binding constraint on recovery is therefore not budget but consent and
customer tolerance, which is why the stopping rules matter more than
the cost ceiling for most records. The CAC ceiling only bites on
micro-payments, where it correctly refuses to spend 50p chasing 40p.

## Per-run detail

| Seed | Treated | Control | Lift (pp) |
|---|---|---|---|
| 20260825 | 63.0% | 28.6% | +34.3 |
| 20260826 | 61.0% | 28.9% | +32.1 |
| 20260827 | 63.4% | 31.3% | +32.1 |
| 20260828 | 61.4% | 29.0% | +32.5 |
| 20260829 | 61.7% | 28.4% | +33.2 |
| 20260830 | 62.9% | 28.1% | +34.8 |
| 20260831 | 62.4% | 29.0% | +33.4 |
| 20260832 | 64.0% | 29.6% | +34.4 |
| 20260833 | 62.7% | 27.1% | +35.7 |
| 20260834 | 64.6% | 28.0% | +36.7 |
