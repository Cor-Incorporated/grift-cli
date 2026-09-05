# v0.6.0 一次資料と実装判断

調査日: 2026-08-31。ここでは仕様を「参考リンク」として並べるだけでなく、
どの実装判断を拘束するかを記録する。provider の現在仕様は release 前にも再確認する。

| 一次資料 | 確認した契約 | v0.6 実装判断 |
|---|---|---|
| [Git mailmap](https://git-scm.com/docs/gitmailmap.html) | name/email は case-insensitive に照合され、4つの記法でcanonical name/emailを指定する。working-tree symlinkは追わない | 対象revisionのtreeから `.mailmap` blobを読み、Git互換規則で適用する。working tree/global configは入力にしない |
| [GitHub commits REST](https://docs.github.com/en/rest/commits/commits) | `sha`を起点にでき、`per_page`上限は100。commit内の生authorとtop-level account objectは別 | 固定OID+100/pageで全paginationし、account対応はtop-level `author.id`だけをstable keyにする |
| [GitHub REST pagination](https://docs.github.com/en/rest/using-the-rest-api/using-pagination-in-the-rest-api) | `Link` response headerで次頁を辿る | 同一originの`rel=next`だけを受理し、cross-origin Linkを拒否する |
| [GitLab commits API](https://docs.gitlab.com/api/commits/) | projectはURL-encoded pathを受理し、`ref_name`はbranch/tag/revision rangeを受理する | 固定OIDを`ref_name`へ渡す。commit responseに文書化されたaccount linkageがないため、GitLab account joinは`unsupported/not_proven` |
| [GitLab REST pagination](https://docs.gitlab.com/api/rest/#pagination) | `x-next-page`等があるがGitLab.comでは一部headerが省略され得る。Link利用も規定 | 空頁/同一origin Link/headerを組み合わせ、62頁等を勝手な上限で完全扱いしない |
| [RFC 9309](https://www.rfc-editor.org/rfc/rfc9309.html) | robots exclusionはcrawlerの取得動作を規定 | provider公式REST API経路へrobots gateを適用しない。将来HTML crawlerを作る場合だけ別実装する |
| [NIST SP 800-188](https://csrc.nist.gov/pubs/sp/800/188/final) | 単純maskだけで十分とは限らず、目的・再識別risk・公開/保護enclave等のsharing modelを先に選ぶ | aggregate/named-publicとcontrolled masked/rawを別契約にし、public doorでcontrolled payloadをhard errorにする |
| [FIPS 198-1](https://csrc.nist.gov/pubs/fips/198-1/final) | HMACは共有秘密鍵を用いるmessage authentication方式 | masked pseudonymはHMAC-SHA-256。32-byte以上のkey file/FDだけを受け、CLI引数/env/payload/logへ鍵を出さない |
| [Sigstore blob signing](https://docs.sigstore.dev/cosign/signing/signing_with_blobs/) | cosignはblob signature/bundleを生成・検証できる | canonical statementを`cosign sign-blob --bundle`へ渡す。検証時は受領者指定certificate identity/issuerを必須にし、bundle自己申告をtrust anchorにしない |
| [OpenSSH ssh-keygen](https://man.openbsd.org/ssh-keygen) | `-Y sign/-Y verify`はnamespaceとallowed signers/principalを使う | 専用namespaceを固定し、verifyは受領者指定allowed_signers/principalなしでは`CANNOT_VERIFY` |
| [W3C PROV Primer](https://www.w3.org/TR/prov-primer/) | entity/activity/agentと生成・帰属の関係を分ける | 入力entity、測定activity、actor/account agent、生成artifactを別fieldとdigestで記録する |
| [Hatch build selection](https://hatch.pypa.io/latest/config/build/) | `only-include`はroot走査対象を明示限定する | sdistをallowlist化し、dirty checkoutの`.worktrees`/`.claude`/nested repo/smoke/lockを構造的に除外する |

## 推論を実装しない箇所

- GitLab commit author name/emailからaccountを検索して結びつけない。
- GitHub/GitLab handleや表示名の類似からActorを統合しない。
- 生emailをhash化しただけで匿名化済み・公開安全とは主張しない。
- signatureを数値の正しさ、品質、能力、優秀さの証明とは記述しない。
- public API coverage欠落をGit履歴上の不存在へ読み替えない。
