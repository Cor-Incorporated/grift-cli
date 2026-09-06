# Changelog

形式は [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/)。バージョンは SemVer。

タグ・PyPI・リポ public 化は本ファイルの記載対象外（人間ゲート）。

## [0.7.1] — 2026-09-06

面は 1 つも増えない。公開 Forge 取得（provider-neutral Forge証跡、
GitHub/GitLab/self-managed、PARTIAL/resume）の 2 つの欠陥を直す patch release。
CLI フラグ・出力スキーマ・contribution-v2 の payload・attest / portfolio の
契約はいずれも変わらない。`暗黙 PyPI update check` を持たない設計も変わらない。

### Fixed

- **bot / app アカウントで `grift repo --actors --fetch-public` が exit 2 に
  なる欠陥**。GitHub の commit author が Bot / app installation
  （`Copilot`、`dependabot[bot]`、`renovate[bot]`、`github-actions[bot]`）の
  場合、`html_url` は `https://github.com/apps/<slug>` を指し、handle は
  角括弧を含む。0.7.0 はこの行にも public account を付けようとして
  `profile_url` が空の account を作り、actor 成果物の生成が
  `account '<provider>|<host>|<id>' needs a handle and profile URL` で
  落ちていた。fetch は 19 ページ coverage complete で成功しているのに
  report が 1 つも書かれない。

  **bot は 0.7.1 でも public account にしない。** これらの commit は
  `unlinked_commit_count` に数える。人の account が handle と canonical な
  profile URL を必ず持つ条件（`actor_artifacts._account_rows`）は
  変えていない。新しい payload キー・status 値・counter も増やしていないので、
  受け口（`tep-contributions`）の契約は不変である。実測: 公開 repo
  VOICEVOX を rev `c72a94cb` で収集すると rc=2 → rc=0、bundle の
  `sha_to_account` から account `198982749` が消える

- **切れた転送を検出せず、切れたまま JSON にしていた欠陥**。GitHub の
  commits ページは 1 ページ約 400KB あり、転送が宣言した長さに届かないまま
  終わることがある。実測で `Content-Length: 436443` に対し受信 372299 バイト、
  次の `read()` は即 `b""`。0.7.0 はこの切れた bytes をそのまま JSON として
  読み、`Forge response body is not valid UTF-8 JSON` という「Forge の応答が
  壊れている」形のエラーを出していた。実際は転送が途中で終わっただけである。

  0.7.1 は受信バイト数を `Content-Length` と照合し、足りなければ
  `ForgeTruncatedBodyError`（message に `truncated_body` /
  `content_length` / `received`）として扱う。**切れた body を JSON デコーダに
  渡さない。** そのうえで収集ループが同一 request を**最大 3 回**まで
  試す（backoff 0.5s / 1.0s）。使い切った場合は従来どおり
  `stop_reason: transport_error:ForgeTruncatedBodyError` で止まる。
  `TimeoutError` など他の transport error も同じ扱いになる。
  `Content-Length` を宣言しない chunked 応答は従来どおり EOF まで読む。
  1 ページあたりのバイト上限は hard stop としてそのまま残る。

  リトライ回数は bundle manifest に**書かない**。`public-evidence-v1` の
  page（`$defs.public_page`）は `additionalProperties: false` の閉じた
  オブジェクトであり、キーを足すことは patch release での契約変更に当たる。
  発生頻度は環境依存で、検収環境では 25 回中 2〜3 回、こちらの回線では
  145 回中 0 回だった

- **live gate が失敗の理由を残さない欠陥**。`scenario-execution-failed` /
  `resume-preflight-failed` は mismatch id だけを summary に残していたため、
  0.7.0 の release tier は上の exit 2 を「何かが失敗した」以上の情報なしに
  記録していた。例外クラス名と message 先頭 200 文字を `failure_detail` として
  残す。message は untrusted なので他の出力バイトと同じ sanitization に
  かけ、token やローカルパスを含む場合は `<redacted>` に落とす

### Changed

- 版数 0.7.1 / 定義版数 `tep-v0.7.1-2026-09-06`

## [0.7.0] — 2026-09-03

### Added

- **`library_context`**（actor scope）: 導入したライブラリが同梱の参照コーパスで
  どれだけ普及しているか。ライブラリを記述するのであって人を記述しない。
  不在は `absent_from_reference_corpus` であって希少の証拠ではない。
  ecosystem の n が 30 未満なら答えを出さない。バンド分けもしない
- **`grift align --team`**: 宣言された要求をチームが覆えているかを人数のみで出す。
  個人の測定値は匿名の最大値としても出ない。3 名未満は `not_observed`
  （`insufficient_team_size`）を返し、個人を特定しうる数を出さない
- **`outcome`**（`--outcome-declaration`）: git に写らない納品結果の申告経路。
  必ず `kind: "declared"` で、`observed` の分岐がスキーマに存在しない。
  `grift verify` は再計算しない。自己申告と第三者証跡を型で区別する
- **`grift contribute --purpose`**: 提出データの目的を提出者が選ぶ。
  無指定時は v0.6.0 と同じ意味
- **`scripts/v070_benchmark.py`**: v0.7.0 の主張を第三者が再実行できる形で測る。
  fixture は本リポジトリ自身の履歴の pin した commit から自前生成する

### Fixed

- **切り詰めた履歴を「リポジトリの実測値」として報告しない**。shallow クローン
  （`actions/checkout` の既定 `fetch-depth: 1` を含む）で 9 フィールドが
  truncation 由来の値を `observed` として申告していた。CI で生成した v0.6.0 の
  証跡は誤っている。promisor は degrade させない（全 commit を取得しており
  commit 数・日付・author は正確なため）
- `context_profile.scale` と `activity` が異なる母集団を持ちながら片方しか
  denominator note を持たなかった
- `grift contribute` の payload が denylist で組まれており、新しいトップレベル
  キーが既定で公開されていた。allowlist に転換
- 秘密検出が単語一致で誤拒否していた
- 範囲外タイムゾーン（`+518:00`）でのクラッシュ
- 測れなかったものを 0 として報告していた
- `time_phase` を本人の観測期間で三分割する
- **`verification_profile.test_type_share` を新設し、verification 軸の逆転を止めた**。
  `test_type_distribution` は commit 数しか持たず、type に対して床を宣言しても
  比較する share が無かった。`alignment._obs_share` は非ゼロの type すべてを
  `not_observed`、ゼロの type だけを `below_declared` にしていた（実際に手を
  動かした type が「未測定」と読める）。分母は「テストを触った commit 数」であり、
  各 type の share は独立に割るので **合計は 1 にならない**
- **`grift align --team` の入力を report-v2 に限定した**。`grift actor --out DIR` が
  書く `actor-card-v1` を受理していたが、card は surface 観測を持たないため
  全要求が `not_observed` になり、沈黙が「チームを測った結果」の形で出ていた。
  拒否時に report-v2 の作り方を示す
- **`grift verify` が `outcome` を比較しないことを明記した**。宣言 outcome には
  再計算する元が無く、verifier に宣言ファイルは渡されない。全 report の outcome が
  MISMATCH になっていたのを diff から外し、代わりに「**宣言を書き換えても verify は
  検知しない**」を report 自身の limitations に毎回載せる。「再計算しない」だけでは
  保護のように読めるが、実際は逆である
- **`--outcome-declaration` を `repo` / `actor` に限定した**。`project` / `align` は
  `report_outcome` を出さないため、フラグを提供するとファイルを受け取って何も
  読まず、outcome の無い report を返していた（「何も宣言されなかった」と読める）

### Changed

- **規範を 2 条項だけ改訂**。複数 actor 条項に `align --team` の例外を 1 つ追加し、
  目的拘束を提出者の選択に移した。§1 §2 §3 §4 §5 §6 §7、alignment no-verdict、
  保持期間、撤回手続き、推測リスク開示、profile 別アクセスは変更していない
- リリース整合性ゲートからバージョンリテラルを外した。移行文書のパスも
  version.py から導出する

### Notes

- v0.6.0 の面はすべて残る。`provider-neutral Forge証跡`（`GitHub/GitLab/self-managed`、
  `PARTIAL/resume`）、`attest / portfolio`、`contribution-v2`、
  `暗黙 PyPI update check` を持たない設計は v0.7.0 でも変わらない
- AI 同条件比較ゲートの判定は **PARITY**（4 軸中 2 勝 2 敗）。
  事前登録に従い SUPERIOR は宣言しない
- **offline 主張の範囲は Python プロセス層のみ**。`evidence/v070/benchmark.json` の
  `offline` は既定の解析経路が Python プロセスから socket を開かないことだけを
  測っている（`scope: "python_process_only"`）。**git subprocess の通信は測っていない**
  （`git_subprocess_network: "not_measured"`）。「grift はネットワークに触れない」という
  一般化の根拠には使えない
- **δ = -0.7871 は v0.7.0 では再現できない**。`validity-person-signal` の値は
  `role-profile-v1` の上で、同意ゲートより前に測ったものである。v0.7.0 は
  identity-v2 の `consent` + `authority` を記録した actor にしか `role_profile` を
  出さず、研究コーパスは公開 OSS contributor でその記録を持たない。再測定は
  本人に代わって同意を主張することになるため行わない
  （`reproducibility: "not_reproducible_on_this_version"`）

## [0.6.0] — 2026-08-31

### Added

- **Subject-first CLI**: `grift repo` / `grift actor` / `grift project` / `grift align`
- **report-v2**（repo / actor 証拠）。`observation_date` と `window_basis` を明示
- **project-v1** 宣言と観測を別セクション。`--init` は空 template のみ
- **alignment-v1** 軸ごとの comparison。総合点・順位・推奨は持たない
- surface / change_rhythm / verification / coordination 観測。role_lens は表示プリセット
- ローカル `tep-forge-export-v1` / `tep-tracker-export-v1`（API 接続なし）
- `change_rhythm` の gap 母集団を observation_date から 180 日窓に限定
- Markdown を非エンジニア向けの7節構成に。raw dict を出さない
- report-v2 validator が空の observed node を拒否
- **固定OID Actor partition**: 明示alias → 固定tree `.mailmap` → email →
  email欠落時nameの順でrepo-local clusterを確定し、公開account表示から分離
- **provider-neutral Forge証跡**: GitHub/GitLab/self-managed、SHA-1/SHA-256、
  full pagination、CAS bundle、offline replay、safe PARTIAL/resume
- **同意済みexperience / role**: rename/copy/re-add/delete、30/180日境界、
  release/tag、AI申告/human coauthorをversion付き四つ組で観測し、母数20未満を抑制
- **attest / portfolio**: OpenSSH/cosign detached signatureと受領者trust、
  明示subject bindingによる複数repo証拠台帳（score/rankなし）
- **contribution-v2**: aggregate / named-public / masked / rawをdoor別に分離。
  controlled HMAC sidecarとpublic intake allowlistを追加
- forge/tracker export-v2のprovider/host/project/OID/window/coverage bindingと
  不完全coverageのfail-closed検証
- 20種のclosed Draft 2020-12 schema、stdlib validator、schema mutation検査
- explicit package allowlist、runtime benchmark/schema assets、dirty-source package smoke

### Changed

- 測定コマンドの新入口は既定 `--format md`、既定では `.grift/` を作らない
- `analyze` / `report` / `verify` の暗黙 PyPI update check を廃止し、ネットワーク経路を明示的な `grift update --check` に分離
- `grift analyze --export` は解決後の scope を書く（省略時に `"None"` と出さない）
- `grift contribute` はreport-v1から既存v1を維持し、report-v2からprofile別v2を生成する
- 公開REST取得からcrawler用robots判定を除き、provider API terms/rate stateと
  固定tree licenseを別provenanceとして記録
- report-v2公開成果物をrepo report、actor index、選択cardへ分離し、
  population/partition/artifact digestを形式間で固定

### Compatibility

- `grift analyze` / `report` / `verify` / `contribute` の report-v1 意味は維持
- 明示パスの tenant default、裸 analyze の repo default は維持
- actor の `--export` と `--scope actor` は拒否
- report-v1 / export-v1は凍結互換を維持し、v0.6新schemaは未知キーを拒否
- GitLab commits APIにdocumented account linkageがない場合は推測せず
  `unsupported/not_proven`を維持

## [0.5.9] — 2026-08-25

### Changed（代表 UX フィードバック）

- **report.md の説明を項目ごと（行末）に配置**: セクション末尾への一括説明を廃止し、各値の行末に短い日英併記の gloss を直付け（origin 11分類・activity 5項目・test co-change・corrective/path retouch・survival・context 各行・test frameworks）。値と説明の距離がゼロになり、レポートを上から読むだけで各数値の意味が分かる
- **検収ゲート対応（提唱者4点）**: ①全 gloss の**単位一致**を機械強制（origin はコミット単位に統一 —「identityに一致しなかったコミット」等・行の単位と gloss の突合テスト）②gloss の**規範語ゲート**（良い/悪い/優れ/劣る/健全/理想等の混入ゼロをピン。解釈は metrics-guide 側のみ・rework の否定注記は維持）③**report.json は不変**（gloss は md のみ・render が dict を mutate しないことと verify が VERIFIED のままなことをテストで明示）④**Shared block は gloss なしと仕様明文化**（README 日英・metrics-guide に「簡潔さ優先、意味は本文行末 gloss が担う」の一行・gloss-free をピン）

## [0.5.8] — 2026-08-25

提唱者事前レビューの必須ゲート（A/B/C/D/E）+ 日英併記拡充。

### Changed

- **A: 無送信文言の精密化**: 全称 claim（「CLI は何も送信しません」等）を全公開物から除去し、スコープ化（「測定コマンドはネットワークに触れない / contribute は自動送信しない / --open は本人権限・本人 fork・最終ボタンは本人 / こちらへの自動送信は恒久にない」）。**claim整合テスト**が全称文言の再混入を CI で検知
- **report.md 全テンプレートを日英併記に**（読み方ガイド・共有ブロック1行・各節の意味行・lifecycle 説明・contribute 開示文・提出手順）
- **D: dev issue リンク張り替え**（persona-answers ×2・test_coverage ×1 → 公開 tracker 鏡 issue #7/#8 — 告けい第1波の 404 防止）
- **E: G1-click.toml 暫定ヘッダ注記**（公開コミットメタデータ由来・再現検証専用・削除依頼先明記。間接化本体は v0.6）

### Added

- **B: --open ガードレール**: ①フラグ無しでは git/gh サブプロセス不起動（spy 反証）②同意前 git 操作なし・非TTY+--yes無しは --open 付きでも exit 2（F-C1 整合）③push 先は本人 fork 限定（origin 拒否ガード）+ 同意文に「公開ドアです・アカウント名が表示されます・fork 自動作成」警告 ④gh/ブラウザ不在フォールバック。**push 前に intake と同一の schema+needle ローカル検査**（不合格は push させない）
- **C: manifest 競合の恒久解消**: 提出は payloads/<year>/<id>.json + <id>.meta.json の2ファイルのみ・manifest.jsonl は main 上で CI が生成（単一書き手・tep-contributions PR #3）。同時2PR反証で無衝突を実証

### テスト

- **F-1（タグ前検収）**: --open の gh 不在/失敗フォールバックURLを `compare/main...new`（不正）から**intake リポジトリ実在パスへ修正**。反証: フォールバックURLが `compare/` を含まないことのピン
- **F-2（タグ前検収）**: payload の `metrics.provenance.analyzed_commit_sha`/`analyzed_at` を README 日英・tep-contributions README 日英のフィールド一覧に明記（「SHA は中身を復元できない不透明値だが公開 repo では特定に使える」推測リスクと同旨の一行つき）。README.en の "manifest line committed" の古い言い回しを "meta file" へ修正
- test_v058_gates 12本（A claim整合×5対象 + B 4反証 + pre-push検査 + scoped必須 + F-1フォールバックピン）ほか

## [0.5.7] — 2026-08-25

代表実機レビュー（2026-08-25）の3問題（#49/#50/#51）を解消。

### Fixed

- **#49 追加: `grift contribute --open`** — payload と manifest 行をコミット済みのブランチを fork に push し（ユーザーの gh 認証・gh/git 必須）、ブラウザで PR 作成ページを開く。**残る操作は「Create pull request」ボタンのみ**。grift 自身のネットワーク送信なし（push は git 経由でユーザーの fork へ・最終ボタンはユーザーが押す）。gh がない環境はイントークリポジトリのページを開くフォールバック。実測: fork ブランチ `contrib/<id>` 作成・payload は intake validator 合格
- **#49 contribute の同意後行き止まり**: 同意（対話 yes または --yes）後にデフォルトで `.grift/contribution.json` を書き、**提出ID（MMDD-HHMM-hash8）・PR ファイル名・manifest 行（sha256 計算済み・コピー可能）・二枚扉の手順**を表示。CLI は引き続き何も送信しない
- **#50 出力値の読みやすさ**（context-v3）: `language_composition` の値を生カウントから**シェア（0-1・合計≈1）に修正**（unit が touch-share なのに値がカウントだった契約不一致バグ）／`actor_turnover` の `left` を **`last_active` に改名**（今年最終コミットの作者は退場していない）／`release_cadence` の単位を `releases/year` → `tags/year` に／report.md の言語構成をパーセント表記で表示

### Added

- **#51 `grift update`**: grift-cli 自身の明示的アップグレード（pipx 優先・フォールバック pip）。`--check` は PyPI メタデータの**読み取りのみ**（送信なし・無送信原則は不変）
- **#51 追加: アップデート通知** — 対話（TTY）実行の analyze/report/verify で新しいバージョンがあれば stderr に1行表示（PyPI メタデータの読み取りのみ・`GRIFT_NO_UPDATE_NOTICE=1` で非表示・CI/非TTYでは出ない）
- **report.md の数値に平易な意味を1行添付**（test co-change / rework / survival / context / lifecycle の各節に「何を測るか」の日本語1行・lifecycle の2観測には変数名の直後に平易説明）

### テスト

- 同意後のデフォルト書き込み+ガイド行（manifest 行の sha256 が実ファイルと一致）／シェア合計≈1／`left` 廃止／markdown パーセント／`update --check`

## [0.5.6] — 2026-08-23

公開後検収で発見の仕様記述↔実挙動の矛盾 3 件（D-1/D-2/D-3）を解消するホットフィックス。

### Fixed

- **動詞の意味を確定: `analyze` = 表示（stdout）・`report` = 記録（`.grift/`）**。README 日英の 2 語動詞表の analyze 行（「`.grift/` を生成」と誤記）を訂正
- **D-3b**: 裸 `grift analyze` の既定スコープを **repo** に統一（パス明示の従来モードは既定 tenant のまま不変）
- **D-3a**: `grift report --scope {repo,tenant}`（既定 repo）を追加
- D-2 文書: report の help「default: ./out」誤記を `.grift/` に訂正・docstring/examples を動詞意味確定版に更新
- **errata（0.5.5 の記載について）**: 0.5.5 の README/EVIDENCE に「裸 `grift analyze` が `.grift/` を自動生成する」との記述があったが、実挙動は stdout 出力のみ（`.grift/` は `grift report` が作る）。本版で文書をバイナリに合わせ、動詞意味を上記のとおり確定した
- CHANGELOG の受け口 URL 表記を tep-contributions に統一

### Added（報告規律・恒久）

- **「wheel 実測」節の各 claim には実行コマンドと生ログを添付する**（0.5.5 で裸 analyze の claim が公開 wheel で再現しなかった件の再発防止）

### テスト（反証）

- 裸 analyze が `.grift/` を作らず stdout へ出すピン / 裸 analyze の scope=repo ピン / パス明示の既定 tenant 維持ピン / 裸 report が `.grift/` を書き scope=repo のピン / `report --scope tenant` のピン / help 文言の golden（`./out` 残存なし）

## [0.5.5] — 2026-08-23

UX 統一（2語動詞 + `.grift/` 出力）+ contribute 受け口の実運用化 + 全ドキュメント日英対応。

### Changed

- **基本操作はすべて `grift <動詞>` の2語で完結**: `grift analyze`（対象=カレント・出力=`.grift/`）・`grift report`（常に HEAD を再分析）・`grift verify`（`.grift/report.json` をカレントリポで再計算）・`grift contribute`（`.grift/report.json` から payload 組立）。明示指定は従来どおり引数で
- **出力先を `.grift/` に統一**（旧 `./out`・`.grift-out` は読み取り互換のみ）。`.gitignore` への `.grift/` 追加を推奨・リポ標準 `.gitignore` に同梱
- Action の作業ディレクトリも `.grift/` へ・既定ピン 0.5.5

### Added

- **contribute 受け口リポ [grift-contributions](https://github.com/Cor-Incorporated/grift-contributions) を開設**: README（日英）・CONTRIBUTING・schema 検証 CI（`tep-contribution-v1`・メール形状拒否・禁止キー検査）。`grift contribute` の確認文が提出先と手順を明示
- **全公開ドキュメントの英語版を `docs/en/` に追加**: norms / metrics-guide（v2・帯規約・インベントリ・関連ツール節を含む完全英訳）/ report-schema / export-schema / identity-schema / corpus-protocol / coverage-map / persona-answers
- 読み方ガイド v2（帯規約の統一定義・全観測インベントリ・関連ツール節・表記確定）

### Removed

- publish-testpypi ワークフロー（TestPyPI シークレット不在による恒久失敗のため削除）

## [0.5.4] — 2026-08-23

`grift report` の stale 出力問題を解消 + 表示の版残存を一掃。

### Fixed

- **`grift report`（引数なし）は既存の `./out/report.json` があっても常に現在の HEAD を再分析**する（提唱者実測で検出: 旧仕様は既存 JSON を再表示し、2コミット目以降の SHA が古いまま残った — 自己証明の信頼性を損なう重大な問題として処理）。再分析なしの再レンダリングは引数指定時のみ
- README 日英: Action 使用例を `@v0.5.4` へ・**PyPI 欄を版に依存しない表記に変更**（「最新 0.5.2」等の古い版番号が残り続ける問題を構造的に解消）・`grift report` を「初回の簡単導線」として条件付きで説明（主 CTA は `grift analyze . --scope repo --out ./out` を維持）
- action.yml 既定ピンを 0.5.4 へ

## [0.5.3] — 2026-08-23

UX 改善（代表フィードバック）+ 公開 README の整合。

### Changed

- **`grift report`（引数なし）= そのディレクトリを分析して `./out/report.{json,md}` を自動作成**（`out/` がなければ作る）。引数を渡した場合は従来どおり既存 JSON からの再レンダリング（再分析なし）
- `grift contribute`（引数なし）は `./out/report.json` → `.grift-out/report.json` → `./report.json` を自動探索。無ければ「先に `grift report` を」と案内
- GitHub Action の使用例を `@v0.5.2` ぼ更新・「本公開は別ゲート」注記を公開済み表示に更新（README 日英）

### Fixed

- hygiene 除外リストに内部調査文書プレフィックス（SMOKE / REREVIEW / RELEASE-REHEARSAL / INTERNAL-PILOT）を追加

## [0.5.2] — 2026-08-23

基準の憲法（norms / reader's guide / verify）+ 文脈層（context_profile v2・lifecycle-v2）+ corpus v2026.11 + contribute。

### Added

- **norms.md v1**（7条 ja/en + 保持・削除条項）: 「TEP 準拠」の使用条件を定義。README 日英からリンク
- **reader's guide**: 全 report.md 末尾に「この数値でしてはいけない判断」節を自動同梱（テンプレート固定・LLM 不使用）
- **`grift verify`**: report.json を記録 provenance で再計算し全フィールド突合（VERIFIED / MISMATCH / CANNOT_VERIFY・exit 0/1/2）。改ざん検出の反証テストつき
- **context_profile v2**（裁定 §4/§5）: 16観測（collaboration_class / language_composition / dependency_manifests 等・定義版管理）。`resolved_human_actors` は bot・upstream 除外後の定義（push-copy fork 反証テストで上流混入排除を実証）
- **lifecycle-v2**（密度基準）: 一次出力 = `days_since_last_human_commit` + `active_days_180d`（クラスに常に併記）。帯 dormant≤2 / maintained 3-11 / active≥12。informed-by-pilot-1 を開示。180日沈黙+直近1日 fixture の反証テスト
- **共有ブロック**（`shared_block`）: report.md 冒頭に 3-5 行のコピペ要約（norms 1 行版つき）
- **`grift report`**: 既存 JSON から md を再レンダリング（再分析なし）
- **GitHub Action**（観測のみ）: `grift-cli` ピン install → STEP_SUMMARY に共有ブロック・artifact upload・PR コメントは明示 opt-in のみ。action-dogfood で自リポ動作保証
- **`grift contribute`**: 明示的 opt-in 提出 payload 組み立て（repo スコープ集計 + context クラス級 + 定義版のみ。canonical_id/メール/パス/repo 名/activity は構造的除外）。**CLI は何も送信しない（7禁止⑦）**。F-C1: 非 TTY + `--yes` なしは exit 2 で拒否・`--yes` でも開示文 + payload 全文表示（同意の痕跡）
- **corpus v2026.11**: admission 70 件（C33/D29/B8・narratable は機械実測で C=14/D=14 — 目標 30 に対する不足を逐語記録）。分布 test co-change n=68 / corrective n=101（deciles 収録・values 非同梱）。層別は active n=34 のみ発行・他は `context_stratum_too_small`
- `docs/coverage-map.md`（21問→観測の表）・`docs/persona-answers.md` 判別引用更新・`--reference-version`（旧 v2026.09 は不変で選択可能）

### Changed

- README 日英の判別節を v2026.11 逐語へ全面更新: **A vs D separated（δ=0.9198）を筆頭に、A vs C は fail_tier2 に転回**（基準 5f2665e 不変・転回をそのまま公開）。旧 separated 根拠の残存 0 を CI が機械強制
- CLI 既定の参照分布を v2026.11 に

## [0.5.1] — 2026-08-22

WP-P1e 二層契約 + Golden v2 第1波。Grift 本体統合（WP-G1）の unblock マイルストーン。

### Added

- export-v1（`--export <dir>`・opt-in）: commits.ndjson / actors.json / export-meta.json。生メール・生 author 文字列ゼロ出力。per-actor 品質指標は恒久禁止（`docs/export-schema.md`）
- `docs/report-schema.md`: report-v1 凍結（追加互換）・純stdlib検証器 `tep_core.schema.validate_report`
- golden G6〜G13 増設（計13本・上限内）: AI共著（claude-code）・引き継ぎ（axios）・dormant（co）・polyglot（pyscript）・テンプレ派生（scvi-tools）・solo（kilo）・founder（httpx）・日本語圏（voicevox）
- `golden/coverage.md` カバレッジ行列 + HOLE 機械検出（issue 紐付け強制）
- `docs/persona-answers.md`: 敵対レビュー21問の実数値実演集（転記数値は CI が golden 期待値と機械突合）
- パリティ検算レシピ（export-schema.md）+ 逐語実行テスト
- 終了コードと stdout 純度規約（README 日英）

### Fixed

- F-P10-3: identity loader が空・@含有・重複 canonical_id を受理し生メールが export に漏れる producer gap を修正。`CANONICAL_ID_PATTERN`（`^[a-z0-9][a-z0-9._-]{0,63}$`・版管理）で `IdentityValidationError`（CLI は exit 2・export 未書き出し）。schema 文書と実装は逐語一致テストで固定。性質テスト「exit 0 ⇒ export 内 `@` 0 バイト」

### Changed

- `schema_version` を `tep-report-v1` から `report-v1` へ改名（凍結前の最後の変更）

## [0.5.0] — 2026-08-22

定義Bの節目（`--scope`・参照分布 v2026.09・解釈層）。行レベル rework は v0.6 予約のまま。

### Added

- `--scope tenant|repo`。tenant は証拠、repo はプロセス観測と参照分布。混ぜると `ScopeMismatchError`
- 参照分布 v2026.09（repo スコープ）。n<30 の指標は位置を出さない
- survival（`--survival`、τ=180日）。参照分布は v2027 予定
- 公開コーパス pin（A/B/C/D、SHA 固定）。リーグテーブルは同梱しない

### Changed

- `corrective_rework_rate` を evidence_claim から観測専用へ降格（件名規約依存の交絡）
- git log の非 UTF-8 を `errors="replace"` で落とさない
- コマンド名を `grift` に確定（method=TEP / tool=grift）。旧 `tep` エントリは置かない
- PyPI 配布名を `grift-cli` に確定（公開操作は人間ゲート）
- H-5: 母数<20 では ratio と十分位を両方出さない（`insufficient_population`、件数の生表示のみ）

### Discriminant (verbatim from `corpus/DISCRIMINANT-v2026.09.md` Run 2)

- `test_cochange A vs D` → `inconclusive_small_n`
- `test_cochange A vs C` → `separated`
- `corrective_rework A vs C` → `fail_tier2`

## [0.1.1] — 2026-08-22

origin 語彙の P0 修正（検収合格 SHA `e954b16`）。ローカルタグ `v0.1.1` は未 push。v0.5.0 に一本化するかは代表判断。

## [0.1.0] — 2026-08-21

origin / activity の決定論的レポート。ゴールデン G1–G5。LLM なし。
