# 指標の検証と限界

grift の指標が、公開リポジトリのあいだで実際に違いを示すかを確かめた記録です。人やリポジトリに順位を付けるためのものではなく、指標そのものが使えるかどうかを、測る前に書いた基準で確かめています。手順は [corpus-protocol.md](corpus-protocol.md)、元の記録は `corpus/DISCRIMINANT-v2026.11.md` です。英語版は [docs/en/validation.md](en/validation.md) です。

## 設計の選択と、その境界

grift は、人を 1 つの数値にまとめることではなく、第三者が条件と限界を確かめ、必要なら計算し直せる記録を残すことを目的にしています。そのための設計の選択と、それぞれの境界は次のとおりです。

| 設計上の選択 | 利用者にとっての価値 | 境界 |
|---|---|---|
| LLMを使わない | モデル、provider、promptの更新で測定結果が変わらない | 定義版や入力revisionが変われば結果も変わるため、provenanceを併記する |
| 固定OID・版管理された定義・決定論的再計算 | 同じ入力を再実行し、差分や改ざんを確認できる | 再現できることは、数値の正しさ・品質・優秀さの証明ではない |
| 既定local/offline | 明示したnetwork経路を除き、履歴・identity・結果を端末外へ送らない | public fetch、`update`（`--check` を含む）、`contribute --open`、cosign keylessは明示network経路 |
| 合成score・rank・重み付けを生成しない | 単位、母数、観測窓、限界を隠さず、採用閾値へ自動変換しない | 読み手による文脈確認と面接・レビューは置き換えない |
| `not_observed` と母数20未満の抑制 | 見えない履歴や小標本を、実績が無いことへ読み替えない | private履歴やgit外の成果を補完・推測しない |
| attest とportfolioの選択性開示 | 誰がどの条件で測ったか、どのrepoを選んだかを受領者が確認できる | 署名は実行事実、portfolioは選んで出した記録の一覧であり、人物評価ではない |

## 指標ごとの限界

| 指標 | 何の記録か | 限界 |
|---|---|---|
| origin / 帰属 | 誰の仕事か | identity 未設定は unresolved。Cor 実メールは同梱しない |
| test co-change | 本番変更にテストが伴うか | テスト基盤なしは not_observed。母数<20 は率も十分位も出さない（`insufficient_population`） |
| corrective rework | 件名が fix/revert の直近パス回帰（観測） | 証拠主張には使わない（降格済み）。件名規約依存の交絡あり。バグ件数ではない。再挑戦は v0.6 行レベル |
| path retouch | 同一ファイル再接触 | 観測のみ。証拠主張に使わない |
| survival (τ=180d) | 行の残り方 | `--survival` のみ。参照分布は **v2027 予定**。今回の公開分布には含めない |

## 参照用の位置

report-v1 が出す参照用の位置は「第N十分位」の 1 行だけです。repo スコープの公開リポジトリの分布の中で、そのリポジトリの値がどの帯にあるかを示します。tenant スコープの分布は無いため、tenant スコープでは出しません（`not_observed(scope_is_tenant)`）。n<30 の指標は位置を出しません（`reference_too_small`）。現行 v2026.11 の観測 n: test co-change 68 / corrective rework 101（観測）/ survival 0（v2027 予定）。旧 v2026.09 は不変のまま `--reference-version` で選べます。帯の定義は [metrics-guide.md](metrics-guide.md) の十分位の表記規約にあります。

## 群のあいだの違い（repo スコープ・基準 `5f2665e`）

検証では、性格の違う公開リポジトリの群を測る前に決めておき、指標の値に差が出るかを見ます。A は検証の文化がある repo、C は AI を多く使った repo、D はテンプレートや fork などテストの無い repo です（群の定義は [corpus-protocol.md](corpus-protocol.md)）。

出典: `corpus/DISCRIMINANT-v2026.11.md`（n=117・v2026.09 全行 + v2026.11 admission 70 件）。verdict はファイルから逐語。

- `test_cochange A vs D` → `separated`（median_A 0.2379, median_other 0.0718, gap 0.1661, Cliff δ 0.9198, n 18/18）。母数がそろった状態で初めて差が出た比較で、「commit 数のような量は誰でも増やせるが、テストを伴う変更はそうはいかない」という grift の前提を支える最初の強い結果です
- `test_cochange A vs C` → `fail_tier2`（median_A 0.2379, median_other 0.0769, gap 0.161, Cliff δ 0.291, n 18/21）。v2026.09 では `separated`（δ 0.7143）でしたが、C 群が「tests を持つ AI 駆動 repo」に広がり差が小さくなりました。登録済みの基準は下げず、変わった結果をそのまま公開しています
- `corrective_rework A vs C / A vs D` → 方向要件なし（観測専用・v0.5.0 から不変）。A vs C δ -0.8333 / A vs D δ 0.0139
- 母数: C narratable = 14（目標 30 に届かず、admission の実測で訂正）/ D total 29（目標 20 達成）
- survival: 参照分布は v2027 予定

v2026.09 の記録（Run 2: A vs C `separated` ほか）は `corpus/DISCRIMINANT-v2026.09.md` に履歴として残しています。

## 公開の決まり

- 実在個人のスコアカード・順位表は、公開も内部共有も禁止します
- 等級の語（シニア / ジュニア / 素晴らしい）を出しません
- コーパスの manifest（リポ名 + SHA）は再現のために公開してよいものとします。**個別リポの値を並べた表は公開しません**
- 対照群 E（私的な ground truth）はこのリポジトリに入れません
