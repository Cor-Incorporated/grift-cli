"""The 「観測された数値」 lines of the report-v2 and project-v1 Markdown."""

from __future__ import annotations

from typing import Any

from tep_core.report_v2_text import _obs
from tep_core.v2_constants import SURFACES


def _surface_lines(profile: dict[str, Any]) -> list[str]:
    lines = [
        "### 変えた部分の区分（作業領域、surface）",
        f"- 分類根拠: {profile.get('classification_basis') or 'path_pattern_and_extension_heuristic'}（意味理解ではない）",
        f"- 曖昧 path 数: {profile.get('ambiguous_count', '—')} 件（複数パターンに当たった path）",
        f"- 未分類 path 数: {profile.get('unclassified_count', '—')} 件（other）",
        f"- 分母: {profile.get('denominator_definition') or 'merge 除外の人間 commit（path 取得済み）'}。"
        f"母数={profile.get('population', profile.get('sample_size'))}",
    ]
    if profile.get("kind") == "not_observed":
        lines.append(f"- {_obs(profile)}")
        return lines
    counts = (profile.get("surface_commit_counts") or {}).get("values") or {}
    files = (profile.get("surface_file_counts") or {}).get("values") or {}
    unique = (profile.get("surface_unique_file_counts") or {}).get("values") or {}
    for name in SURFACES:
        if name in counts:
            lines.append(
                f"- {name}: {counts[name]} commits（その surface を1つ以上触った commit 数。入力=Git path）"
            )
        if name in files:
            lines.append(
                f"- {name} files: {files[name]} file-changes / unique={unique.get(name, 0)} files"
            )
    lines.append(f"- ファイル比率: {_obs(profile.get('surface_file_share'))}（commit 比率とは別）")
    lines.append(f"- 変更行: {_obs(profile.get('surface_line_counts'))}")
    share = profile.get("surface_commit_share") or {}
    lines.append(f"- 比率: {_obs(share)}。合計は 1 を超えてよい（1 commit が複数 surface）")
    lines.append(
        f"- トップレベル module 数: {_obs(profile.get('module_breadth'))}（名前は出さない）"
    )
    return lines


def _rhythm_lines(profile: dict[str, Any]) -> list[str]:
    lines = [
        "### 変更のペース（変更リズム、change rhythm）",
        f"- 時刻の根拠: {profile.get('timestamp_basis', 'git_author_timestamp')}",
        f"- 窓: observation_date={profile.get('observation_date')} から {profile.get('window_days')} 日",
    ]
    if profile.get("kind") == "not_observed":
        lines.append(f"- {_obs(profile)}")
        return lines
    lines += [
        f"- 窓内の commit 数: {profile.get('window_population', profile.get('sample_size'))} commits（分母）",
        f"- 窓の外の履歴: {_obs(profile.get('history_outside_window_commit_count'))}（統計に混ぜない）",
        f"- 180 日の活動日数: {_obs(profile.get('active_days_180d'))}",
        f"- 間隔の中央値: {_obs(profile.get('median_gap_days'))}",
        f"- 間隔の p90: {_obs(profile.get('p90_gap_days'))}",
        f"- 2 日以内の間隔の割合: {_obs(profile.get('burst_share_le_2d'))}",
        f"- 30 日以上の間隔の割合: {_obs(profile.get('long_gap_share_ge_30d'))}",
        f"- 間隔の標本数: {_obs(profile.get('interval_sample_size'))}",
    ]
    return lines


def _verification_lines(profile: dict[str, Any]) -> list[str]:
    lines = ["### テストの付け方（検証の形、test path heuristic。QA 適性ではない）"]
    if profile.get("kind") == "not_observed":
        lines.append(f"- {_obs(profile)}")
        return lines
    types = (profile.get("test_type_distribution") or {}).get("values") or {}
    lines += [
        f"- test だけを触った commit: {_obs(profile.get('test_only_commit_count'))}",
        f"- test を含む commit の割合: {_obs(profile.get('test_touch_share'))}",
        f"- fix/revert と test の同時変更: {_obs(profile.get('fix_with_test_pairing'))}",
    ]
    for name, value in types.items():
        lines.append(f"- test 種別 {name}: {value} commits（path heuristic）")
    return lines


def _coordination_lines(profile: dict[str, Any]) -> list[str]:
    git_block = profile.get("git") or {}
    lines = ["### 調整の観測（Git / ローカル export。能力判定ではない）"]
    if profile.get("kind") == "not_observed":
        lines.append(f"- {_obs(profile)}")
        return lines
    lines += [
        f"- merge commit 数: {_obs(git_block.get('merge_commit_count'))}（PR review ではない）",
        f"- merge commit 割合: {_obs(git_block.get('merge_commit_share'))}",
        f"- commit 件名の issue link: {_obs(git_block.get('issue_link_count'))}（heuristic）",
        f"- review: {_obs(profile.get('review'))}",
        f"- tracker: {_obs(profile.get('tracker'))}",
    ]
    return lines


def _bound_source_lines(profile: dict[str, Any]) -> list[str]:
    binding = profile.get("binding") or {}
    if not binding:
        return []
    target = binding.get("target_oid") or {}
    coverage = binding.get("coverage") or {}
    return [
        f"- bound source: {binding.get('provider')}:{binding.get('host')} "
        f"project={binding.get('project_id')} ({binding.get('project_path')})",
        f"- target OID: {target.get('algorithm')}:{target.get('value')}",
        f"- coverage: {coverage.get('status')} "
        f"{coverage.get('observed')}/{coverage.get('expected')} {coverage.get('unit')} "
        f"(missing={coverage.get('missing')})",
        f"- binding digest: {binding.get('digest')}",
    ]


def _event_observation_lines(profile: dict[str, Any]) -> list[str]:
    if not profile:
        return []
    lines = [
        "### イベント観測（bound forge / GH Archive。能力判定ではない）",
        *_bound_source_lines(profile),
    ]
    if profile.get("kind") in {"not_observed", "not_proven"}:
        lines.append(f"- {_obs(profile)}")
        return lines
    types = (profile.get("event_type_counts") or {}).get("values") or {}
    lines += [
        f"- 件数: {profile.get('sample_size')} events（分母=読み込んだ正規化イベント）",
        f"- 窓: {((profile.get('window') or {}).get('start'))}〜{((profile.get('window') or {}).get('end'))}",
        f"- 活動した UTC 日: {_obs(profile.get('active_utc_days'))}",
        f"- 重複: {_obs(profile.get('duplicate_count'))} / 影響率 {_obs(profile.get('duplicate_rate'))}",
        f"- 時刻正規化: {', '.join(profile.get('timezone_rules') or []) or 'utc_zulu'}",
    ]
    for name, value in types.items():
        lines.append(f"- {name}: {value} events")
    if profile.get("missing_event_types"):
        lines.append(
            f"- この入力に無い種別: {', '.join(profile['missing_event_types'])}（0件ではなく未出現）"
        )
    return lines


def _event_rhythm_lines(profile: dict[str, Any]) -> list[str]:
    if not profile:
        return []
    lines = ["### イベント間隔（観測ラベル。速度・生産性ではない）"]
    if profile.get("kind") in {"not_observed", "not_proven"}:
        lines.append(f"- {_obs(profile)}")
        return lines
    share = profile.get("active_day_share") or {}
    lines += [
        f"- 活動日の割合: {_obs(share)}（分母 window_days={share.get('denominator', profile.get('window_days'))}）",
        f"- 間隔中央値: {_obs(profile.get('inter_event_gap_median_hours'))}",
        f"- 間隔 IQR: {_obs(profile.get('inter_event_gap_iqr_hours'))}",
        f"- 同日イベント割合: {_obs(profile.get('same_day_event_share'))}",
        f"- burst 日割合: {_obs(profile.get('burst_day_share'))}",
        f"- release 間隔: {_obs(profile.get('release_interval_days'))}",
        f"- 形のラベル: {_obs(profile.get('shape_label'))}（観測上の集中。速さの判定ではない）",
    ]
    return lines


def _lifecycle_lines(profile: dict[str, Any]) -> list[str]:
    if not profile:
        return []
    lines = ["### Tracker lifecycle", *_bound_source_lines(profile)]
    if profile.get("kind") in {"not_observed", "not_proven"}:
        lines.append(f"- {_obs(profile)}")
        return lines
    kind = profile.get("fixture_kind") or profile.get("source_format") or "unknown"
    synthetic = kind == "synthetic_contract"
    lines += [
        f"- fixture_kind: {kind}（{'synthetic。実測・PM能力・速度・品質ではない' if synthetic else 'local export'}）",
        f"- sample size: {profile.get('sample_size', '—')}",
    ]
    projects = profile.get("projects") or {}
    for project_id, metrics in projects.items():
        if not isinstance(metrics, dict):
            continue
        lines += [
            f"- {project_id} issue created → in_progress: {_obs(metrics.get('issue_created_to_in_progress_median_hours'))}",
            f"- {project_id} issue created → closed: {_obs(metrics.get('issue_created_to_closed_median_hours'))}",
            f"- {project_id} PR created → first review: {_obs(metrics.get('pr_created_to_first_review_median_hours'))}",
            f"- {project_id} PR created → merged: {_obs(metrics.get('pr_created_to_merged_median_hours'))}",
            f"- {project_id} release count: {_obs(metrics.get('release_count'))}",
            f"- {project_id} release interval: {_obs(metrics.get('release_interval_days'))}",
            f"- {project_id} linked issue share: {_obs(metrics.get('linked_issue_share'))}",
            f"- {project_id} linked PR share: {_obs(metrics.get('linked_pr_share'))}",
        ]
    return lines


def _reference_lines(block: Any) -> list[str]:
    if not isinstance(block, dict):
        return []
    catalog = block.get("catalog") or {}
    lines = [
        "### 外部参照（比較材料。合否ではない）",
        f"- source_id: {catalog.get('id')}",
        f"- source: {catalog.get('source_url')}",
        f"- source_version: {catalog.get('source_version')}",
        f"- as_of: {catalog.get('as_of')}",
        f"- window: {catalog.get('window')}",
        f"- n: {catalog.get('n')}",
        f"- denominator: {catalog.get('denominator')}",
        f"- coverage: {catalog.get('coverage')}",
        f"- sha256: {catalog.get('sha256') or catalog.get('sha256_unavailable_reason')}",
        f"- limitations: {', '.join(catalog.get('limitations') or [])}",
        f"- 使ってよいこと: {', '.join(catalog.get('use_for') or [])}",
        f"- 使ってはいけないこと: {', '.join(catalog.get('do_not_use_for') or [])}",
    ]
    for row in block.get("comparisons") or []:
        ref = row.get("reference") or {}
        ref_text = (
            _obs(ref)
            if isinstance(ref, dict) and ref.get("kind")
            else str(ref.get("summary") or "")
        )
        lines.append(
            f"- {row.get('metric_id')}: 観測={_obs(row.get('observed'))} / 参照={ref_text} "
            f"/ coverage={(row.get('coverage') or {}).get('status')}"
        )
    return lines


def _actor_directory_lines(report: dict[str, Any]) -> list[str]:
    directory = report.get("actor_directory") or {}
    actors = directory.get("actors") or []
    attr = directory.get("attribution") or report.get("attribution") or {}
    activity = report.get("activity") or {}
    join = attr.get("public_join") or {}
    nonmerge = (
        activity.get("repo_human_nonmerge_commits") or activity.get("repo_commits") or {}
    ).get("value", "—")
    including = attr.get("attribution_human_including_merges", attr.get("attributed_commit_count"))
    merge_count = attr.get("merge_count", "—")
    lines = [
        "### actor 一覧（品質ランキングではない）",
        f"- repo 人間・非merge commit: {nonmerge}",
        f"- 帰属（merge込み）: {including}",
        f"- merge_count: {merge_count}（非merge + merge = merge込み + attribution unresolved）",
        f"- actor 数: {directory.get('observed_count', len(actors))}",
        f"- public_handle actors: {join.get('public_handle_actors', 0)} "
        f"（contributors login 一覧={join.get('fetched_login_count', '—')} 件、"
        f"SHA→login で根拠付きの login={join.get('commit_login_count', '—')} 件。"
        "一覧取得は actor 紐付けではない。SHA→login join が無いと public_handle は 0）",
        f"- unmatched/ambiguous: {join.get('unmatched', '—')}/{join.get('ambiguous', '—')}",
        "- commit_count は merge 込み。職種・能力・速度・採用判断ではない。",
        "- 行は actor_id 順（commit 数順ではない）。行の位置は何も意味しない。表は先頭 50 行まで、全件は JSON の actor_directory.actors。",
        "- 個別 actor の観測詳細は `actors/<actor_id の : を _ に替えた名前>.json`（--actors --out DIR 実行時に書かれる）。",
        "| actor_id | display | status | commits (merge込み) | nonmerge | card |",
        "|---|---|---|---:|---:|---|",
    ]
    for actor in actors[:50]:
        safe = str(actor.get("actor_id") or "").replace(":", "_")
        lines.append(
            f"| {actor.get('actor_id')} | {actor.get('display_name')} | "
            f"{actor.get('display_status')} | {actor.get('commit_count')} | "
            f"{actor.get('commit_count_nonmerge', '—')} | actors/{safe}.json |"
        )
    if len(actors) > 50:
        lines.append(f"| … | 残り {len(actors) - 50} 行は actor_id 順で JSON に続く |  |  |  |  |")
    return lines
