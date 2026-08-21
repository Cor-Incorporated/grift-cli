# Discriminant v2026.09 (repo scope)

Criteria: `docs/corpus-protocol.md` (registered `5f2665e`) plus WP4 A vs C.
No per-repo league table. reverse direction → kill.
Historical runs are kept below; they are not rewritten.

## Run 2 (WP1b-4, 2026-08-22)

- ok rows: 47 (failures: 0)
- groups: A=22, B=7, C=11, D=7
- analysis_scope: repo (all rows)
- WP1b-1: `corrective_rework` is observational (not an evidence claim). The
  comparison is retained as a diagnostic, not as a promotion criterion.

| comparison | verdict | n | gap | Cliff δ |
|---|---|---|---|---|
| test_cochange A vs D | inconclusive_small_n | 18/1 | None | None |
| test_cochange A vs C | separated | 18/7 | 0.2073 | 0.7143 |
| corrective_rework A vs C | fail_tier2 | 18/8 | -0.0541 | -0.7083 |

```json
[
  {
    "metric": "test_cochange A vs D",
    "verdict": "inconclusive_small_n",
    "n_A": 18,
    "n_other": 1
  },
  {
    "metric": "test_cochange A vs C",
    "verdict": "separated",
    "median_A": 0.2379,
    "median_other": 0.0306,
    "gap": 0.2073,
    "range_A": [
      0.1113,
      0.4964
    ],
    "range_other": [
      0.0,
      0.4154
    ],
    "contained": false,
    "cliffs_delta": 0.7143,
    "n_A": 18,
    "n_other": 7
  },
  {
    "metric": "corrective_rework A vs C",
    "verdict": "fail_tier2",
    "median_A": 0.0522,
    "median_other": 0.1063,
    "gap": -0.0541,
    "range_A": [
      0.0,
      0.1499
    ],
    "range_other": [
      0.047,
      0.1971
    ],
    "contained": false,
    "cliffs_delta": -0.7083,
    "n_A": 18,
    "n_other": 8
  }
]
```

## Run 1 (WP4, 2026-08-21) — historical, not overwritten

- ok rows: 31
- groups: A=9, B=7, C=8, D=7

| comparison | verdict | n | gap | Cliff δ |
|---|---|---|---|---|
| test_cochange A vs D | inconclusive_small_n | 8/1 | None | None |
| test_cochange A vs C | separated | 8/4 | 0.1609 | 1.0 |
| corrective_rework A vs C | fail_tier2 | 8/5 | -0.0345 | -0.6 |

corrective_rework 低 ≠ バグが少ない（fresh-work stability）。

```json
[
  {
    "metric": "test_cochange A vs D",
    "verdict": "inconclusive_small_n",
    "n_A": 8,
    "n_other": 1
  },
  {
    "metric": "test_cochange A vs C",
    "verdict": "separated",
    "median_A": 0.1683,
    "median_other": 0.0075,
    "gap": 0.1609,
    "range_A": [
      0.1113,
      0.4964
    ],
    "range_other": [
      0.0,
      0.0369
    ],
    "contained": false,
    "cliffs_delta": 1.0,
    "n_A": 8,
    "n_other": 4
  },
  {
    "metric": "corrective_rework A vs C",
    "verdict": "fail_tier2",
    "median_A": 0.0581,
    "median_other": 0.0926,
    "gap": -0.0345,
    "range_A": [
      0.0,
      0.1063
    ],
    "range_other": [
      0.047,
      0.1951
    ],
    "contained": false,
    "cliffs_delta": -0.6,
    "n_A": 8,
    "n_other": 5
  }
]
```
