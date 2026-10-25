# セキュリティポリシー / Security Policy

**日本語** | [English below](#security-policy-english)

## 対象となる版

PyPI にある最新版だけを対象にします（`pip index versions grift-cli` または `grift update --check` で確認できます）。
古い版の脆弱性は、最新版で再現する場合に修正します。

## 何が脆弱性か

grift は手元の git 履歴を読み、既定では network に出ない CLI です。次のようなものは脆弱性として扱います。

- 既定（明示フラグなし）の実行で、履歴・identity・出力が端末の外へ送られる
- 出力（report / collection / payload）に生メールアドレスや個人を特定できる値が載る
- `grift verify` が改竄された report を `VERIFIED` と判定する
- `--fetch-public`、`update --check`、`contribute --open`、cosign keyless の明示 network 経路で、宣言していない宛先へ接続する
- 同梱 GitHub Action（`action.yml`）が、PR 側の code に write 権限のある token を渡す
- 細工した git リポジトリ・export ファイル・TOML を読ませたときの任意コード実行やパストラバーサル

設計上の判断（スコアを出さない、`not_observed` の扱いなど）への異論は脆弱性ではありません。question テンプレートの Issue で聞いてください。

## 報告のしかた

**公開 Issue には書かないでください。** 次のどちらかで連絡してください。

1. Cor.Incorporated の問い合わせ窓口 <https://cor-jp.com/contact/> から、件名の先頭に `grift-cli security` と書いて送る
2. GitHub の private vulnerability reporting（公開リポジトリで有効になっている場合。2026-10-25 時点では無効）

報告に含めてほしいもの:

- 影響を受ける版（`grift --version`）と OS / Python の版
- 再現手順。再現に使う repo は、公開 repo の URL と SHA、または合成 repo を作るスクリプトの形で
- 観測した出力と、本来あるべき出力
- 既に公開している場所があればその URL

受領の連絡を 5 営業日以内に返すことを目標にします。修正は PyPI の次の patch release で出し、CHANGELOG に記載します。報告者の名前を載せるかどうかは報告者が選べます。

## 秘密情報を見つけたとき

このリポジトリは `gitleaks`（`.gitleaks.toml`）で secret をスキャンしています。`docs/` `evidence/` `benchmarks/` などに並ぶ 40 / 64 桁の hex は公開 git の OID であり、秘密ではありません。
それ以外の鍵・token らしきものを見つけたら、上の窓口へ知らせてください。

---

## Security Policy (English)

### Supported versions

Only the latest version on PyPI is supported (`pip index versions grift-cli` or `grift update --check`).
A vulnerability in an older version is fixed when it reproduces on the latest one.

### What counts as a vulnerability

grift reads a local git history and stays off the network by default. The following are treated as vulnerabilities:

- A default run (no explicit flag) sends history, identity or output off the machine
- Output (report / collection / payload) contains a raw email address or another identifying value
- `grift verify` reports a tampered report as `VERIFIED`
- An explicit network path (`--fetch-public`, `update --check`, `contribute --open`, cosign keyless) connects to an undeclared destination
- The bundled GitHub Action (`action.yml`) hands a write-capable token to PR-controlled code
- Arbitrary code execution or path traversal through a crafted git repository, export file or TOML

Disagreement with a design decision (no score, how `not_observed` is handled, and so on) is not a vulnerability. Ask through the question issue template.

### How to report

**Do not open a public issue.** Use one of the following:

1. The Cor.Incorporated contact page <https://cor-jp.com/contact/>, with `grift-cli security` at the start of the subject
2. GitHub private vulnerability reporting, when it is enabled on the public repository (disabled as of 2026-10-25)

Please include:

- The affected version (`grift --version`) and your OS / Python version
- Reproduction steps. Describe the repository as a public URL plus SHA, or as a script that builds a synthetic repository
- The output you observed and the output you expected
- Any URL where the issue is already public

We aim to acknowledge a report within five business days. Fixes ship in the next patch release on PyPI and are listed in the CHANGELOG. Reporters choose whether to be credited.

### If you find a secret

This repository is scanned with `gitleaks` (`.gitleaks.toml`). The 40- and 64-digit hex strings under `docs/`, `evidence/` and `benchmarks/` are public git OIDs, not secrets.
Anything else that looks like a key or token: report it through the channel above.
