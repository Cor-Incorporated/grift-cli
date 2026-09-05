# ローカル forge / tracker export（v0.6）

外部 API には接続しない。利用者が事前に作った正規化ファイルだけを読む。
malformed schema は終了コード 2。黙って空配列にしない。
raw email / token / cookie / DSN は入力・出力・エラーに載せない。

`repo` / `actor` / `project` / `align` は、対象を取り違えないため
`tep-forge-export-v2` / `tep-tracker-export-v2` だけを受理する。v2 の
`binding` は provider、host、provider の stable project ID、project path、
generic Git OID、UTC window、coverage を必須とする。forge と tracker を
同時に与える場合は同じ binding でなければならない。v1 は既存の legacy
loader / command の読み取り互換だけを維持する。

## tep-forge-export-v2

```json
{
  "schema_version": "tep-forge-export-v2",
  "binding": {
    "provider": "gitlab",
    "host": "gitlab.example.com",
    "project_id": "gid://gitlab/Project/42",
    "project_path": "group/project",
    "target_oid": {"algorithm": "sha1", "value": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},
    "window": {"start": "2026-08-01T00:00:00Z", "end": "2026-09-01T00:00:00Z"},
    "coverage": {"status": "complete", "observed": 31, "expected": 31, "missing": 0, "unit": "days"}
  },
  "events": [
    {
      "event_id": "forge-opaque-1",
      "kind": "pull_request_review",
      "timestamp": "2026-08-29T00:00:00Z",
      "actor_canonical_id": "candidate_001",
      "project_id": "gid://gitlab/Project/42",
      "project_path": "group/project",
      "pr_number": 12,
      "commit_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    }
  ]
}
```

repo は全 event、actor は `actor_canonical_id` の完全一致だけを集計する。
email、name、provider handle から Actor を推測しない。report の
`event_observation` は event 件数・kind・active UTC days・window・binding
coverage（`observed` / `expected` / `missing`）を保持する。partial coverage
でも実際に含まれる件数は観測値として残すが、absence と cadence は
`not_proven(partial_source_coverage)` にする。

## tep-tracker-export-v2

tracker v2 は、表示用 issue number とは別に provider 内で安定した
`record_type` / `record_id` を使う。状態遷移 event は直前の状態 event を
`previous_event_id` で結び、`duration_seconds` は両 event の timestamp 差と
完全に一致させる。issue と milestone の関連は `linked_event_id` で結ぶ。

```json
{
  "schema_version": "tep-tracker-export-v2",
  "binding": {"provider": "gitlab", "host": "gitlab.example.com", "project_id": "gid://gitlab/Project/42", "project_path": "group/project", "target_oid": {"algorithm": "sha1", "value": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}, "window": {"start": "2026-08-01T00:00:00Z", "end": "2026-09-01T00:00:00Z"}, "coverage": {"status": "complete", "observed": 31, "expected": 31, "missing": 0, "unit": "days"}},
  "events": [
    {
      "event_id": "issue-opened-21",
      "kind": "issue_opened",
      "timestamp": "2026-08-28T00:00:00Z",
      "actor_canonical_id": "candidate_001",
      "project_id": "gid://gitlab/Project/42",
      "project_path": "group/project",
      "record_type": "issue",
      "record_id": "issue-global-21",
      "state": "open",
      "previous_state": null,
      "previous_event_id": null,
      "linked_event_id": null,
      "duration_seconds": null,
      "issue_number": 21,
      "commit_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    },
    {
      "event_id": "issue-closed-21",
      "kind": "issue_closed",
      "timestamp": "2026-08-29T00:00:00Z",
      "actor_canonical_id": "candidate_001",
      "project_id": "gid://gitlab/Project/42",
      "project_path": "group/project",
      "record_type": "issue",
      "record_id": "issue-global-21",
      "state": "closed",
      "previous_state": "open",
      "previous_event_id": "issue-opened-21",
      "linked_event_id": null,
      "duration_seconds": 86400,
      "issue_number": 21,
      "commit_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    }
  ]
}
```

許可状態は issue=`open|triaged|closed`、milestone=`active|closed`。
event ID 重複、必須状態欠損、非有限値、負の duration、timestamp 差との
不一致、timestamp の逆順、存在しない/未来/別 record の predecessor、
壊れた link、kind と state の不整合を拒否する。report の
`tracker_lifecycle` は event kind/state 件数、active UTC days、window、
coverage、観測できた issue transition の中央値を出す。これは作業時間、
能力、品質、速度ではない。actor 集計も canonical ID 完全一致だけである。

## legacy read compatibility

## tep-forge-export-v1

```json
{
  "schema_version": "tep-forge-export-v1",
  "provider": "github",
  "events": [
    {
      "event_id": "opaque-1",
      "kind": "pull_request_review",
      "timestamp": "2026-08-29T00:00:00Z",
      "actor_canonical_id": "candidate_001",
      "pr_number": 12,
      "commit_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    }
  ]
}
```

subject command への入力は拒否する。legacy loader では読み取り可能。

## tep-tracker-export-v1

```json
{
  "schema_version": "tep-tracker-export-v1",
  "provider": "github",
  "events": [
    {
      "event_id": "opaque-2",
      "kind": "issue_linked",
      "timestamp": "2026-08-29T00:00:00Z",
      "actor_canonical_id": "candidate_001",
      "issue_number": 21,
      "commit_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    }
  ]
}
```

subject command への入力は拒否する。legacy loader では読み取り可能。

v1 event は `timestamp` → `event_id` で安定ソートする。v2 tracker は状態列の
検証可能性を保つため、入力 event が timestamp 順であることを要求する。
provenance には内容 digest と credential-free binding だけを残し、絶対パスは
残さない。入力未指定はそれぞれ
`not_observed(reason="forge_export_not_provided")` /
`not_observed(reason="tracker_export_not_provided")` とし、0件とは扱わない。
