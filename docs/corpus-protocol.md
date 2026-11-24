# Corpus protocol (v0.5) — write kill criteria before running

Goal: test **discriminatory power** and **game resistance**, not that anyone is
"senior". Public output is anonymous percentiles only. Named-person scorecards
are forbidden.

## Groups in this repository

| Group | What it represents | In this repo |
|---|---|---|
| A | High verification culture | golden click, express, typer |
| D | Template / fork / no tests | golden gitignore, Spoon-Knife |
| B | Notable individual works | not shipped (ethics: no personal ranking) |
| C | AI-heavy / vibe-coding | not shipped until a public pin is agreed |
| E | Private ground truth | Grift-only; never copied here |

## Kill criteria (written before measurement)

Compute group A vs group D on `test_cochange.all_time.value` among repos where
the metric is observed with `narrate_rate=true`.

- Discard test co-change if the two group medians differ by less than 0.10
  (absolute) **or** the ranges fully overlap.
- Rework: WP1b-1 裁定により `corrective_rework_rate` は **観測専用**
  （件名規約依存の交絡。evidence_claim から降格）。`path_retouch_rate`
  も観測専用。いずれもコーパスの証拠主張に使わない。行レベル再挑戦は v0.6。
- Do not load a corpus until H-4 (corrective definition + click sanity
  gate < 20%) is closed.
- Survival is opt-in (`--survival`). Kill it if wall time per repo exceeds
  120 seconds before any language rewrite is considered (git I/O first).
- Line-level rework is v0.6 opt-in (numstat/diff), same I/O caution as survival.

If a metric is killed, keep origin/attribution as the floor. Do not invent a
composite score to replace it.

## Narrative lock (corrective rework)

Registered before any corpus interpretation:

> Low `corrective_rework_rate` is **not** evidence of few bugs. The metric
> measures whether paths written recently needed an immediate fix/revert —
> **fresh-work stability**. Expanding it to “code quality” or “seniority”
> is forbidden (grade smell).

Markdown reports must carry this limit next to the number.

## A vs D pass criteria (registered 2026-08-22, before this pilot run)

Two tiers. A metric may pass Tier 1 and still be **inconclusive** on Tier 2.
Do not promote an inconclusive rate test into a pass by lowering the bar
after seeing numbers.

### Pins for this pilot

- **A**: golden `click` (identity present), `express`, `typer`
- **D**: golden `gitignore`, `Spoon-Knife` (already in `.golden-cache`)
- **C** (selected, not required for A/D): `https://github.com/mabene/vibe.git`
  — self-described 100% AI-generated product code. Reports use the **repo
  name only** (no person scorecard). SHA is pinned at first clone in
  `corpus/manifest.toml`. A/D does not wait on C.

### Tier 1 — observation status (A vs D)

Pre-specified direction: D is “no verification substrate / no tenant
population”, not “a low rate”.

- D: `test_cochange.kind == not_observed` with reason
  `no_test_framework_or_directory` **or** `pending_attribution`.
- A with an identity file: `test_cochange.kind == observed` and
  `all_time.narrate_rate == true`.
- Population below 20: do not narrate the ratio and do not attach a
  reference decile (`insufficient_population`). Raw counts only
  (e.g. `9コミット中2件`).
- A without identity: excluded from tenant-rate comparison. `test_frameworks`
  may still be observed (culture marker only).

**Pass**: every D pin matches D; every identity-bearing A pin matches A.
**Fail**: any D pin posts an observed narratable co-change rate, or click
fails to narrate.

### Tier 2 — rates (only if both groups have n ≥ 2 observed + narratable)

Metrics: `test_cochange.all_time.value`, `corrective_rework_rate.value`.
`path_retouch_rate` is excluded from the claim.

For each metric, **all** of:

1. Direction (co-change): median(A) − median(D) ≥ 0.10.
   Direction (corrective): **not** “A has fewer bugs”. Pre-specified only
   vs C later: median(C) − median(A) ≥ 0.10 would support “fresh work less
   stable”. A vs D has **no** required direction on corrective because D is
   expected not_observed.
2. Range: closed intervals [min, max] of A and D must not fully contain
   one another (complete overlap / inclusion → fail).
3. Effect size: Cliff’s δ, A vs D, |δ| ≥ 0.33 (medium). With n < 2 in
   either group, **do not compute δ**; mark `inconclusive_small_n`.

**Kill** the metric if Tier 2 runs and fails (1) or (2) or (3).
**Inconclusive** if n < 2 in a group — keep the floor (origin/attribution);
do not declare discriminatory power.

### C pin (public, for a later C vs A run)

Not executed in the A/D pilot. First public pin:

| id | url | why it is C (repo-level, not a person) |
|---|---|---|
| C1-vibe | https://github.com/mabene/vibe.git | README states the codebase was generated through AI dialogue with no human-authored source |

## Command

```bash
grift analyze <repo> --identity .tep/identity.toml
# survival is separate because blame is git-I/O bound
grift analyze <repo> --survival
```

## 公開リポジトリからの基準分布づくり（0.9.6・`scripts/corpus_bootstrap.py`）

`contribute`（利用者からの提出）に頼らず、公開リポジトリだけで新しい版の基準分布を作る手順です。出荷済みの `v2026.09` と `v2026.11` は変えません（スクリプトも拒否します）。新しい版名（例: `v2026.12`）で作ります。

1. `plan`（オフライン）: 候補の一覧（TOML か JSON。`url` と任意の `group`・`sha`）か、既存の pin ファイル（`--from-pins`）から計画を作ります。公開 https の URL 以外（認証情報つき、ssh、公開ホスト以外）、重複、clone が重い repo、上限超えを理由つきで外します。
2. `observe`（ネットワーク）: 計画の repo を clone し、空の identity・`scope=repo` で分析します（`--survival` で survival も記録）。個人の identity は入りません。repo ごとの値は gitignored の `corpus/runs-<版>/results.jsonl` にだけ置き、公開する `corpus/pins-<版>.toml` には url・sha・group だけを書きます。
3. `build`: `results.jsonl` から `corpus/<版>/distributions.json` を作ります。十分位は n ≥ 30 の指標だけに出し、足りない指標は理由を note に残して分布を出しません（`reference_too_small` になります）。`src/tep_core/data/<版>/` への配置と `REFERENCE_VERSION` の切り替えは、結果を確かめたあとに人が行います。

```bash
python scripts/corpus_bootstrap.py plan --version v2026.12 --from-pins corpus/pins-v2026.11.toml --out plan.json
python scripts/corpus_bootstrap.py observe --plan plan.json --survival
python scripts/corpus_bootstrap.py build --version v2026.12
```

個別 repo の値を並べた表は公開しません（[validation.md](validation.md) の公開の決まり）。

### survival の事前登録（基準を結果の前に固定する）

survival（τ=180d の行の残り方）は、0.9.6 から `interpretation.survival` として基準位置を出せます。ただし公開分布に survival が無いため、今は `reference_too_small` です。最初の survival 分布を作る前に、次の基準を固定します。結果を見たあとに下げません。変えるときは、変えた理由と日付を記録して残します。

- 母数: 基準に入れるのは、`lines_sampled ≥ 20` の repo だけです。n < 30 なら十分位を出しません。
- A vs C: 中央値の差が 0.10 以上、Cliff δ の絶対値が 0.33 以上、A と C の範囲（最小〜最大）が互いに包含し合わないこと。向き（A が高い、など）は事前に決めず、観測した向きを記録します。
- 年齢の交絡: survival は古い repo ほど低く出やすい性質があります。repo の年齢との Spearman の順位相関の絶対値が 0.5 以上なら、その指標は年齢の代理として扱い、判別には使いません。

どれかを満たさなければ、test co-change の A vs C が `fail_tier2` だったときと同じく、結果をそのまま公開します。
