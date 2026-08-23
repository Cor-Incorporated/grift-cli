# DISCRIMINANT-v2026.11 — 判別再走（基準 5f2665e 凍結のまま・逐語）

実行: 2026-08-23（スクリプト `scripts/discriminant_v2026_11.py`・生出力そのまま）。
コーパス: v2026.09 全行 + v2026.11 admission 70 件（計 117 repos・repo スコープ）。

## 母数の正直な記録（目標に対する不足を逐語）

- **C narratable = 14（目標 30 に対し不足）**。研究段階の tests ヒントは narratable を過大評価していた（tree 走査と CLI 実測の乖離）。admission では全 pin の narratable フラグを機械実測で確定した（`corpus/pins-v2026.11.toml` 参照）。
- D total = 29（目標 20 達成）・**D narratable = 14**。テンプレ派生 repo の本番コミット母数が20に届かないケースが半数（テンプレの本質的性質 — P1c-4 の予測どおりの所見として記録）。
- v2026.11 の行は narratable と関係なく全件 test_frameworks 観測を取ったため、判別の母集団は「narratable のみ」（H-5 規則どおり率の叙述可能な群のみ）。

## 判別結果（スクリプト生出力・逐語）

```
test_cochange A vs C: fail_tier2 (median_A 0.2379, median_other 0.0769, gap 0.161, Cliff δ 0.291, n 18/21)
test_cochange A vs D: separated (median_A 0.2379, median_other 0.0718, gap 0.1661, Cliff δ 0.9198, n 18/18)
corrective_rework A vs C: no_required_direction (median_A 0.0522, median_other 0.1841, gap -0.1319, Cliff δ -0.8333, n 18/36)
corrective_rework A vs D: no_required_direction (median_A 0.0522, median_other 0.0469, gap 0.0053, Cliff δ 0.0139, n 18/32)
```

## 読み（判別の変化と理由 — 観測記録であり主張の昇格ではない）

1. **A vs D separated（初めて n が立った）**: v2026.09 では D の narratable 観測が 1 件で `inconclusive_small_n` だった。テンプレ/ボイラープレート D 群 n=18 になり、A（検証文化）との分離が δ=0.92 で立った。gap 0.166 ≥ 0.10・範囲重なりなし・δ ≥ 0.33 の Tier 2 全条件を満たす。
2. **A vs C fail_tier2（v2026.09 の separated から変化）**: C 群が「tests を持つ AI 駆動 repo」に広がった結果、C の median co-change が 0.0306→0.0769 に上昇し δ が 0.71→0.29 に低下。Tier 2 の effect-size 条件 (|δ|≥0.33) を満たさない。**登録済み基準を下げて再合格にしない** — 判別力の現況として逐語記録する。C 群の内部多様性（AI 駆動でも検証文化を持つ群の存在）が分離を弱めた、が正直な読み。
3. **corrective_rework**: A vs D は事前登録どおり方向要件なし（観測専用指標）。A vs C で δ=-0.83（C の方が corrective が高い）は v0.5.0 から一貫した観察で、証拠主張には使わない。

## 分布 v2026.11 について

- test co-change global n=68・corrective n=101（`corpus/v2026.11/distributions.json`・deciles 収録で values 非同梱 = リーグテーブル再構成不能）。
- 文脈層別: **active n=34 のみ deciles 発行**（MIN_N 30 達成）。community n=25 / solo n=9 / small_team n=2 / dormant n=1 / maintained n=1 は `context_stratum_too_small` として global のみ + 本記録（裁定4-2 どおり）。
- v2026.09 は不変のまま選択可能（`--reference-version v2026.09`）。CLI 既定は v2026.11。

## 履歴

- v2026.09 Run 2（当時）: A vs C `separated` / A vs D `inconclusive_small_n` / corrective A vs C `fail_tier2`（`corpus/DISCRIMINANT-v2026.09.md` に逐語履歴として残存）。
