# grift-cli への貢献のしかた

**日本語** | [English](CONTRIBUTING.en.md)

grift は、エンジニアの git 履歴から改竄できない事実を取り出し、点数も順位もつけずに案件と照らす CLI です。
この文書は、その設計を壊さずに手を入れるための最短の道順です。手元で動かすまで 5 分、全体を読むのに 10 分を目安にしています。

- 使い方だけ知りたい: [README](README.md)（1 コマンドで自分の repo を見る）
- 数値の読み方: [docs/metrics-guide.md](docs/metrics-guide.md)
- 守るべき利用規範: [docs/norms.md](docs/norms.md)（7 条、日英併記）
- 行動規範: [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) / 脆弱性の報告: [SECURITY.md](SECURITY.md)

---

## 1. 2 つのリポジトリの関係

| | 開発リポジトリ | 公開リポジトリ |
|---|---|---|
| 場所 | `Cor-Incorporated/grift-cli-dev`（private） | [`Cor-Incorporated/grift-cli`](https://github.com/Cor-Incorporated/grift-cli)（public・MIT） |
| 履歴 | 日々の PR が `main` に入る | release ごとの snapshot だけ。dev の `main` から `git archive` で取り出し、`release/vX.Y.Z` ブランチ → PR → `main` → annotated tag |
| ブランチ | 作業ブランチ多数 | `main` のみ（2026-10-25 実測） |
| PyPI | 出ない | 人が tag を `publish` workflow に渡したときだけ [`grift-cli`](https://pypi.org/project/grift-cli/) に出る（`publish.yml` は `github.repository == 'Cor-Incorporated/grift-cli'` のときだけ publish する） |
| 証跡（§5） | dev の commit に束縛 | 公開 commit に束縛し直す |

公開リポジトリは dev の commit を持たないので、公開リポジトリの `main` に直接積んだ変更は次の snapshot で上書きされます。
手順の正本は [docs/RELEASE-REPORT-v0.7.2-20260908.md](docs/RELEASE-REPORT-v0.7.2-20260908.md) §5 と
[docs/RELEASE-REHEARSAL-v051-20260822.md](docs/RELEASE-REHEARSAL-v051-20260822.md) §5 です。

### 外からの変更をどこに出すか

- **Issue は公開リポジトリへ。** テンプレート（bug / feature / question）が「観測値と期待値」「再現 repo の形」を聞きます。
- **PR の受け口は（未検証）。** 2026-10-25 時点で公開リポジトリに外部からの PR が来た実績はなく（PR #5〜#16 はすべてメンテナの release PR）、次の 2 案から決めます。
  - **案 A（推奨）: 公開リポジトリへ PR を出す。** メンテナが dev へ転記し、commit に `Co-authored-by:` で貢献者を残し、公開側の PR には転記先の dev PR 番号を書いてクローズする。貢献者は 1 つの repo だけ見ればよい。
  - **案 B: dev リポジトリへの招待を受けて直接 PR を出す。** 継続的に関わる人向け。小さな修正には重い。
  - どちらでも、§6（PR の作法）と §7（禁止事項）は同じです。
- Discussions は 2026-10-25 時点で無効です。有効化はメンテナの判断なので、それまでは question テンプレートの Issue を使ってください。

---

## 2. 手元で動かす（5 分）

必要なもの: Python 3.11 以上、git。実行時依存はゼロです（`pyproject.toml` の `dependencies = []`）。

```bash
git clone https://github.com/Cor-Incorporated/grift-cli.git
cd grift-cli
uv venv && source .venv/bin/activate        # uv が無ければ: python -m venv .venv
uv pip install -e ".[dev]"                  # uv が無ければ: python -m pip install -e ".[dev]"
python -m pytest tests -m "not golden" -q   # CI の test job と同じ範囲
```

- `-m "not golden"` は network を使う live golden corpus（固定した公開 repo を clone する）を外します。golden を回すのは `python -m pytest -m golden`。
- lint は ruff です。repo の設定は `pyproject.toml` の `[tool.ruff]`（`line-length = 100`、`target-version = "py311"`）だけで、ルールは `E4` / `E7` / `E9` / `F`（ruff 0.15 までの既定）です。CI に ruff の job は無いので、手元で 0 件にしてから出してください。ruff 0.17 以降は既定のルール集合が広がり、同じ木で 463 件出ます（2026-10-25 実測、0.15.14 は 0 件）。版に左右されないよう、ルールを明示して測ります。

```bash
uvx ruff check --isolated --select E4,E7,E9,F --line-length 100 --target-version py311 src tests scripts
```

- 変更後に手元の CLI を叩くときは、同じ venv の `grift` を使います（`pip install -e` で入っています）。

```bash
grift repo .            # Markdown を stdout へ。保存するときだけ --out DIR
grift --version
```

---

## 3. テストの階層と CI

| 層 | 走らせ方 | 何を守るか |
|---|---|---|
| Unit / contract | `python -m pytest tests -m "not golden" -q` | schema・禁止キー・docs と code の一致（§7）。合成 git repo を `tests/git_fixture.py` で作って測る |
| Golden（network） | `python -m pytest -m golden` | 固定した公開 repo（pallets/click ほか）を clone し、期待値と一致するか |
| 証跡ゲート | §5 | 同梱した証拠がこの source tree で作られたものか |

CI（`.github/workflows/ci.yml`）の job と、落ちたときに見る場所:

| job | 役割 | 落ちたら |
|---|---|---|
| `test (3.11 / 3.12)` | 上の Unit / contract。intake 契約テストが skip になっても fail させる | 失敗したテスト名を PR に貼る |
| `p0-falsify` | 公開 repo の v0.5.9 を baseline に、互換の反証スイート（43 仮説）を回す | legacy（report-v1 / export-v1）の出力を変えていないか |
| `intake-contract-parity` | 受け口 `tep-contributions` の schema と `PURPOSES` を実送信で突合 | `contribution_v2.py` と受け口 schema の両側 |
| `exact-pr-head` | PR head そのものを analyze → verify | 決定論が崩れていないか |
| `v060-golden` | v0.6 golden fixture の再生と、公開 digest-only registry の検証 | §5 の #2 と #4 |
| `action-dogfood` | 同梱 GitHub Action（`action.yml`）をこの repo に実行 | `action.yml` と `scripts/action_contract_guard.py` |
| `package-smoke` | 汚れた作業木から sdist / wheel を作り、clean install して smoke | `pyproject.toml` の `only-include` と追跡ファイルの対応 |
| `gitleaks` | secret scan（`.gitleaks.toml`） | 公開 OID の誤検知なら allowlist 済み path かを見る |
| `golden` | live golden corpus。PR では skip、schedule で走る | network を使う期待値 |

---

## 4. 変更の種類ごとの最短ルート

| 変更 | 最低限やること |
|---|---|
| docs だけ | 対応する英語版（`README.en.md`、`docs/en/*`）も同じ PR で直す。`tests/test_v060_docs_parity.py` と `tests/test_v070_norms_link.py` が日英と code の一致を見る |
| 数値の名前・定義 | `docs/metrics-guide.md` の訳語対応表が正。README は表をコピーせずリンクする（`test_site_glossary_is_linked_not_copied`） |
| `src/` | §5 の証跡ゲートが赤になる。意図した出力変更なら PR 本文に「どのゲートが、なぜ」を書く |
| 新しい観測値の追加 | schema（`src/tep_core/schemas/`）・`docs/report-v2.md`・`docs/metrics-guide.md`・テストを同じ PR で。§7 の禁止キーに当たる名前は付けられない |
| `norms.md` の条文 | 条文と強制点（code / schema）が 2 箇所にあるなら、両方を 1 つのテストで結ぶ（`tests/test_v070_norms_link.py` の形） |

---

## 5. `src/` を変えると赤になる証跡ゲート 4 本

同梱した証拠は「どの source tree で作られたか」に束縛されています（`runner.source_binding` の `source_tree_digest`（sha256）と `commit_oid`）。
`src/`・`pyproject.toml`・`scripts/v060_provider_live_gate.py`・`scripts/v060_scenario_matrix.py` のどれかを変えると、次の 4 本が「source binding is stale」や digest 不一致で赤になります。**赤になるのが設計です。** 片側だけ変わっていないことを検出しています。

| # | 証跡 | 見るテスト / CI | 検証コマンド | 再生成（意図した変更のとき） |
|---|---|---|---|---|
| 1 | `evidence/v060/scenarios`（private registry、R0x 6 本） | `tests/test_v060_scenario_matrix.py` | `python scripts/v060_scenario_matrix.py --verify-registry --output-root evidence/v060/scenarios` | `python scripts/v060_scenario_matrix.py --output-root evidence/v060/scenarios --replace` |
| 2 | `evidence/v060/scenarios-public`（digest-only registry、P01〜P03） | CI `v060-golden`、`tests/test_v060_public_registry_export.py` | `python scripts/v060_scenario_matrix.py --verify-registry --digest-only --output-root evidence/v060/scenarios-public` | provider live gate の PR tier: `python scripts/v060_provider_live_gate.py --tier pr --registry-output evidence/v060/scenarios-public --replace-registry`（公開 repo への read-only fetch を伴う） |
| 3 | `evidence/v070/benchmark.json`（この repo 自身の履歴を `PINNED_OID` で測る） | `tests/test_v070_benchmark.py` | `python scripts/v070_benchmark.py` | `python scripts/v070_benchmark.py --write` |
| 4 | `benchmarks/v060/golden`（expected / manifest / migrations）と `DEFINITION_VERSION` | CI `v060-golden`、`scripts/v060_golden.py` | `python scripts/v060_golden.py --result /tmp/v060-golden-result.json` | 出力が正当に変わるなら `src/tep_core/version.py` の `DEFINITION_VERSION` を上げ、expected を更新。`DEFINITION_VERSION` を上げると、前の版で保存した report は `grift verify` で `CANNOT_VERIFY` になる |

release での流れ（毎リリースの手順、[RELEASE-REPORT v0.7.2 §5](docs/RELEASE-REPORT-v0.7.2-20260908.md) より）:

1. dev の `main` で 4 本すべてが緑であることを確認する。
2. 公開リポジトリへ snapshot を載せた `release/vX.Y.Z` ブランチで、#1〜#3 を**公開 commit に束縛し直す**（#3 は公開側の `PINNED_OID` が別。dev 側は `fa9bc31`、公開側は `6711a3c`）。
3. 公開ブランチで `--verify-registry` ×2 が rc=0、benchmark が 6/6、全件 pytest が rc=0 になってから PR を出す。

貢献者がやること・やらないこと:

- `src/` を変えた PR で #1・#3・#4 が赤になったら、**意図した出力変更かどうかを PR 本文に書く**。意図したものなら上の再生成コマンドで作り直して同じ PR に含める。
- #2（public registry）は公開 commit に束縛するので、貢献者の PR では赤のままで構いません。メンテナが release で再束縛します。
- 期待値をいじって緑にするだけの変更は受け付けません。「何が変わったか」が差分で読めることが条件です。

---

## 6. PR の作法

- **1 PR = 1 意図。** ブランチ名と PR タイトルの type を一致させる: `feat/<説明>`、`fix/<説明>`、`docs/<説明>`、`refactor/<説明>`、`chore/<説明>`。
- **commit は Conventional Commits** `<type>: <説明>`（type は `feat` / `fix` / `refactor` / `docs` / `test` / `chore` / `perf` / `ci`）。説明は日本語でも英語でも構いません（履歴は日本語が多い）。
- **`feat` にはテストを含める。** 新しい観測値には「その値が無いときに落ちるテスト」を付ける。
- **PR テンプレートの欄を埋める**（`.github/PULL_REQUEST_TEMPLATE.md`）。
  - `H5-E2E:` 実際に実行したコマンドと、その生出力の要約（20 文字以上）か安定したログ path。実行環境を持たない変更（docs のみ）は `H5-E2E: none`。
  - **ADR-0001 の確認欄 G / R / B**（このテンプレートでの定義）:
    - **G（Green）**: 受入条件を満たすテストが通った。コマンドと出力を貼る。
    - **R（Red）**: 片側だけ変える（code を戻す、docs だけ変える）とそのテストが落ちることを実測した。何を壊して何が落ちたかを書く。
    - **B（Binding）**: 宣言（docs / norms / schema）と実体（code）が 2 箇所にあるなら、両方を 1 つのテストで結んだ。該当しなければ「該当なし」と書く。
- **CHANGELOG** は [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/) 形式。利用者に見える変更は `## [Unreleased]` に 1 行足す。版数と tag はメンテナが付けます。
- レビューは「正しいか」より先に「§7 を破っていないか」を見ます。

---

## 7. 設計上の禁止事項（ここを破る PR は内容が正しくても入りません）

grift は **合成スコア・順位・推奨・合否を出さない** ツールです。これは文章の方針ではなく、code と schema とテストで強制されています。

| 禁止 | 強制している場所 | 具体 |
|---|---|---|
| 総合点・順位・推奨・合否のキー | `FORBIDDEN_VERDICT_KEYS`（[src/tep_core/v2_constants.py](src/tep_core/v2_constants.py)） | `score` `rank` `percentile_for_actor` `fit` `compatibility_score` `recommendation` `hire` `pass` `fail` `overall` `fit_score`。alignment の出力にこのキーがあると `forbidden_key_hits` に出て、schema 検証とテスト（`tests/test_v060_schema.py` ほか）が落ちる |
| 等級語彙・倍率表現 | [scripts/check_forbidden_vocab.py](scripts/check_forbidden_vocab.py) | リテラル `素晴らしい` `シニア相当` `ジュニア相当` `スコアカード`、正規表現 `総合スコア` `grade` `elite` `N倍` `シニア` `ジュニア`。生成した Markdown にテストが掛ける |
| 利用規範 7 条 | [docs/norms.md](docs/norms.md) | 1 不在を負に読まない / 2 単独足切りの禁止 / 3 申告を負に読まない / 4 同意なき第三者プロファイリング禁止 / 5 監視転用の非準拠 / 6 選択性の明示 / 7 重み付け・換算の禁止 |
| 人を観測量で並べる・選ぶ | [docs/adr/ADR-0001-v08-no-volume-ordering.md](docs/adr/ADR-0001-v08-no-volume-ordering.md) | R1 既定の成果物は人を観測量で並べない（actor 列挙は id 順）/ R2 観測量による選別は量であることを名前と注記で明示 / R3 参照分布上の位置は明示要求時のみ / R4 各観測に「膨らませ方」を開示し補正はしない / R5 両側判断でも宣言と観測を混ぜない |
| 宣言と実体の二重管理 | `tests/test_v070_norms_link.py`、`tests/test_v060_docs_parity.py` | norms の数（最小チーム人数 3 名など）や purpose の集合は、code の定数と 1 つのテストで結ばれている。片方だけ変えると両方の値を挙げて落ちる |

そのほか、設計の前提として守るもの:

- **LLM を使わない。** 同じ入力（SHA・identity・export・`--as-of`）から `analyzed_at` 以外が一致する決定論。
- **既定は local。** network に出るのは明示経路だけ（`--fetch-public`、`update --check`、`contribute --open`、cosign keyless）。新しい network 経路は opt-in フラグ付きでしか足せない。
- **生メールや個人を特定する値を出力に載せない。** identity は `email_sha256`、report に raw email は出ない。
- **`not_observed` は「測れなかった」であり、低実績ではない。** 母数 20 未満の率は出さない。見えない履歴を補完・推測しない。
- **`--top N` は commit 数による抽出であり、品質ランキングではない。** 新しい選別フラグを観測量で作らない（ADR-0001 R2）。

迷ったら、「この出力を見た採用担当が、面接せずに人を落とせるか」を考えてください。落とせる形になっていたら、それはこの repo には入りません。

---

## 8. 最初の一歩に向くもの

- README / `docs/` の英語版を日本語版に追随させる（`tests/test_v060_docs_parity.py` が差分を教えてくれる）
- [docs/READERS-GUIDE-draft-20260822.md](docs/READERS-GUIDE-draft-20260822.md)（非エンジニア向けの読み方、draft）の仕上げ
- Issue テンプレートで足りない質問の追加
- `grift repo` の出力を実際の repo で読んで、分かりにくかった文言を question テンプレートで報告する

---

## 9. ライセンス

貢献は [MIT License](LICENSE) で公開されることに同意したものとみなします。
他人の code や文章を持ち込むときは、そのライセンスと出典を PR に書いてください。
