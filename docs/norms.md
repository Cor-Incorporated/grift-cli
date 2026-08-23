# TEP 利用規範（norms）— 「TEP 準拠」を名乗る条件 / TEP Usage Norms

**正式版（v1・2026-08-22実装・P1g）。「TEP 準拠（TEP-compliant）」を名乗る利用の条件を定める。**
**Norms v1 (2026-08-22, shipped as part of WP-P1g). Defines the conditions for calling a use "TEP-compliant."**

TEP は検証可能な証拠を出す方法論であり、判定機ではない。本規範は「TEP 準拠（TEP-compliant）」を名乗る利用の条件を定める。**本規範への適合を「TEP」の名の使用条件とする**（DORA ガイドライン型の規範的強制）。非準拠の利用は TEP と呼んでならない。

---

## 規範（ja）

### 1. 不在を負に読まない

TEP レポートの不在・private 経歴・低活動期間（gap）を、能力・実績の否定として扱う利用は非準拠である。
理由: not_observed ≠ 実績なし。育児・傷病・非公開業務の経歴は git に写らない。

### 2. 単独足切りの禁止

TEP の数値・分布位置を単独の合否基準にする利用は非準拠である。
理由: TEP は問いに答える証拠であり、判定機ではない。

### 3. 申告を負に読まない

declared_ai_assist の申告あり/なしのいずれも、それ自体を負の証拠として扱う利用は非準拠である。
理由: 透明性への罰は隠蔽を生む。申告なし ≠ AI 不使用。

### 4. 同意なき第三者プロファイリング禁止

本人の同意なく identity を構成して tenant 分析する利用は非準拠である。
理由: 個人化の入口は本人の意思でなければならない。

### 5. 監視転用の非準拠

組織構成員の常時比較・個人評価表化への利用は非準拠である（公開も内部も）。
理由: 個人を対象にした継続的な比較表は、この方法論が拒否する使われ方そのものである。

### 6. 選択性の明示

複数 repo の提示は「提供者が選択したものである」ことを明示して読む・示す。
理由: 選択的開示は禁止しないが、隠さない。閉じた経歴書と違い、選択が見えることが前進である。

### 7. 重み付け・換算の禁止

文脈・難易度による数値の補正は非準拠である。
理由: 補正は必ず仮説を含み、検証可能な一次記録を歪める。

---

## 保持・削除（提出データの扱い・`grift contribute` に関わる）

明示的提出（`grift contribute`）で受け取ったデータは「TEP Report 集計と参照分布 vNext」の目的にのみ使用し、それ以外に使わない。保持期間は次回年次 Report の発行までとし、撤回依頼には提出者が payload に同梱した撤連絡先（任意）経由または public リポの issue で応じる。

---

## Norms (en)

**TEP is a methodology that produces verifiable evidence; it is not a decision engine.** These norms define what may be called "TEP-compliant" use. Compliance with this document is a condition of using the TEP name (DORA-guideline-style normative enforcement). Non-compliant use must not be called TEP.

### 1. Do not read absence as negative

Treating a missing TEP report, a private career, or a low-activity period (gap) as evidence of lack of ability or accomplishment is non-compliant.
Reason: not_observed ≠ no achievement. Parental leave, illness, and non-public work do not appear in git.

### 2. No single-metric cutoff

Using any TEP number or distribution position as a standalone pass/fail criterion is non-compliant.
Reason: TEP answers questions with evidence; it does not make decisions.

### 3. Do not read declaration as negative

Treating either the presence or absence of declared AI assistance as negative evidence is non-compliant.
Reason: Punishing transparency breeds concealment. No declaration ≠ no AI use.

### 4. No third-party profiling without consent

Constructing an identity to run tenant analysis on someone without their consent is non-compliant.
Reason: The entry point to personalization must be the person's own choice.

### 5. Surveillance use is non-compliant

Using TEP for continuous comparison or scorecards of organization members — public or internal — is non-compliant.
Reason: A persistent per-person comparison table is exactly the use this methodology rejects.

### 6. Disclose selectivity

Presenting multiple repositories must be read, and shown, as "selected by the provider."
Reason: Selective disclosure is not forbidden; hiding the selection is. Unlike a closed résumé, visible selection is progress.

### 7. No weighting or conversion

Adjusting numbers by context or difficulty is non-compliant.
Reason: Adjustment always embeds hypotheses and distorts verifiable primary records.

---

## Data retention (applies to explicit submissions via `grift contribute`)

Explicitly submitted data is used solely for "TEP Report aggregation and the next reference distribution," for no other purpose. It is retained until the next annual Report; withdrawal requests are honored via the contact channel the submitter chose to include in the payload (optional) or via the public repository's issue tracker.
