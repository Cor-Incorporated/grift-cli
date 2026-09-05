"""Markdown for report-v2 / project-v1 / alignment-v1. Units required. No raw dicts."""

from __future__ import annotations

from typing import Any

from tep_core.actor_basis import (
    ActorBasis,
    actor_basis_notice,
    actor_basis_notices,
    classify_actor_basis,
    without_actor_basis_notices,
)
from tep_core.role_lens import emphasized_keys, emphasized_sections, lens_intro
from tep_core.tendency import rhythm_tendency, surface_tendency
from tep_core.v2_constants import (
    ALIGNMENT_NOTICE,
    COMPARISON_JA,
    EVIDENCE_DISCLAIMER,
    FORGE_NOT_OBSERVED_NOTE,
    PROJECT_OBSERVED_MISSING_NOTE,
    RHYTHM_LIMITATION,
    RHYTHM_TIMESTAMP_LIMITATIONS,
    RHYTHM_WINDOW_NOTE,
    SURFACE_LIMITATION,
    SURFACES,
    TENDENCY_CHANGE_NOTE,
    TRACKER_NOT_OBSERVED_NOTE,
)


def _window_text(node: Any) -> str:
    if not isinstance(node, dict):
        return str(node or "—")
    if node.get("kind") in {"not_observed", "not_proven"}:
        return _obs(node)
    start = node.get("start")
    end = node.get("end")
    if start and end:
        return f"{start}〜{end}"
    return "—"


def _display_value(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item) for item in value)
    if isinstance(value, dict):
        return "複合値"
    return str(value)


def _obs(node: Any) -> str:
    if not isinstance(node, dict):
        return "未観測"
    kind = node.get("kind")
    if kind == "not_observed":
        reason = node.get("reason", "unspecified")
        return f"未観測（not_observed。測定できなかった。実績がないことではない）理由: {reason}"
    if kind == "not_proven":
        reason = node.get("reason", "unspecified")
        return f"未証明（not_proven。確認できない。0件ではない）理由: {reason}"
    if kind == "not_declared":
        reason = node.get("reason", "requirement_not_provided")
        return f"未宣言（not_declared。案件側が書いていない。不足ではない）理由: {reason}"
    unit = node.get("unit") or ""
    if kind == "declared":
        return f"{_display_value(node.get('value'))} {unit}".strip()
    sample = node.get("sample_size")
    value = node.get("value")
    if value is None:
        return f"観測あり（単位 {unit or 'profile'}、n={sample if sample is not None else '—'}）"
    extra = f"（母数 n={sample}）" if sample is not None else ""
    return f"{_display_value(value)} {unit}{extra}".strip()


def _unique(notes: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for note in notes:
        if note and note not in seen:
            seen.add(note)
            ordered.append(note)
    return ordered


def _coverage_line(coverage: dict[str, Any], key: str, present: str, missing: str) -> str:
    node = coverage.get(key) or {}
    if (
        isinstance(node, dict)
        and node.get("kind") == "observed"
        and node.get("provided") is not False
    ):
        if node.get("value") is True or node.get("provided") is True:
            return present
    if isinstance(node, dict) and node.get("kind") == "not_observed":
        return f"{missing}（{_obs(node)}）"
    return missing


def _license_lines(coverage: dict[str, Any]) -> list[str]:
    public_forge = coverage.get("public_forge") or {}
    license_evidence = (
        public_forge.get("repository_license") if isinstance(public_forge, dict) else None
    )
    if not isinstance(license_evidence, dict):
        return ["- 固定Git treeのルートlicense証跡は未観測です。"]
    target = license_evidence.get("target_oid") or {}
    digest = license_evidence.get("digest") or {}
    files = license_evidence.get("files") or []
    lines = [
        "- 固定Git treeのルートlicense証跡: "
        f"status={license_evidence.get('status')} files={len(files)} "
        f"target={target.get('algorithm')}:{target.get('value')}",
        f"- License証跡digest: `{digest.get('value')}`（API termsとは別）",
    ]
    for item in files:
        if not isinstance(item, dict):
            continue
        blob = item.get("blob_oid") or {}
        lines.append(
            f"- `{item.get('path')}`: blob={blob.get('algorithm')}:{blob.get('value')} "
            f"sha256={item.get('sha256')} bytes={item.get('bytes')}（本文は非出力）"
        )
    return lines


def _actor_subject_line(subject: dict[str, Any]) -> str:
    """Describe an actor report through the shared fail-closed basis."""

    cid = subject.get("canonical_id")
    state = subject.get("attribution_state")
    basis = classify_actor_basis(subject.get("selection"), state)
    if basis is ActorBasis.PUBLIC_INFERRED:
        return (
            f"公開Git上のactor cluster観測。対象 actor cluster は `{cid}`。"
            "実在人物との同一性は証明していません。"
            "分析範囲は repo-local の Git primary-author cluster です。"
        )
    if basis is ActorBasis.ADMIN_VERIFIED:
        return (
            f"管理対象リポジトリの identity 定義（attribution_state=verified）に基づくactor観測。"
            f"対象 canonical_id は `{cid}`。"
            "本人同意または本人性は証明せず、本人向け証拠ビューとは呼びません。"
        )
    if basis is ActorBasis.SELF_CLAIMED:
        return (
            "attribution_state=claimed と記録された identity に基づく本人向けactor観測。"
            f"対象 canonical_id は `{cid}`。"
            "CLI はその申告者、本人同意または本人性を証明しません。"
        )
    if basis is ActorBasis.EXPLICIT_NONCONSENT:
        return (
            f"明示identity（attribution_state={state}）により選択されたactor観測。"
            f"対象 canonical_id は `{cid}`。本人同意または本人性は証明しておらず、"
            "experience / role は観測しません。"
        )
    return (
        f"表示根拠を確認できないactor観測。対象 canonical_id は `{cid}`。"
        "selection または attribution_state が欠落・不整合のため、本人同意または"
        "本人性を証明せず、本人向け証拠ビューとは呼びません。"
    )


def render_evidence_markdown(report: dict[str, Any]) -> str:
    subject = report.get("subject") or {}
    prov = report.get("provenance") or {}
    kind = subject.get("kind")
    lens = (report.get("role_lens") or {}).get("name")
    shown = set(emphasized_sections(lens))
    coverage = report.get("input_coverage") or {}
    who = (
        _actor_subject_line(subject)
        if kind == "actor"
        else "リポジトリ全体の作業領域観測です。対象は Git working tree の人間 commit（repo）。個人の適性評価ではありません。"
    )
    lines: list[str] = [
        "# TEP 証拠レポート",
        "",
        "## このレポートは誰・何を対象にしたか",
        f"- {who}",
        f"- 観測日: {prov.get('observation_date')}（窓の基準={prov.get('window_basis')}。"
        "explicit_as_of は --as-of、legacy_head_date は履歴 HEAD 日）",
        "",
        "## 何を入力として見たか",
        f"- {_coverage_line(coverage, 'git', 'Git 履歴を入力として使った', 'Git 履歴は使っていない')}",
        f"- {_coverage_line(coverage, 'forge', 'ローカル forge export を入力として使った', 'forge export は未提供')}",
        f"- {_coverage_line(coverage, 'tracker', 'ローカル tracker export を入力として使った', 'tracker export は未提供')}",
        *(
            ["- 明示指定された公開Forge API証跡を入力として使いました。"]
            if (coverage.get("public_forge") or {}).get("kind") in {"observed", "not_proven"}
            else ["- GitHub / GitLab / tracker API には接続していません。"]
        ),
        *_license_lines(coverage),
        "",
        "## 何を見ていないか",
        "- 非公開の経歴、会議、レビューの質、労働時間は見えません。",
        f"- {FORGE_NOT_OBSERVED_NOTE if (coverage.get('forge') or {}).get('kind') == 'not_observed' else 'forge 入力がある場合でも、レビューの良し悪しは測りません。'}",
        f"- {TRACKER_NOT_OBSERVED_NOTE if (coverage.get('tracker') or {}).get('kind') == 'not_observed' else 'tracker 入力がある場合でも、対人調整の質は測りません。'}",
        "",
        "## 観測された数値",
    ]
    if lens:
        lines += [
            f"- 表示プリセット: `{lens}`（職種分類ではありません）",
            f"- {lens_intro(lens)}",
            f"- 強調する観測キー: {', '.join(emphasized_keys(lens)) or '（既定の全項目）'}",
        ]
    else:
        lines.append("- 表示プリセット未指定。下記の観測項目をすべて表示します。")
    if "surface_profile" in shown:
        lines += _surface_lines(report.get("surface_profile") or {})
    if "change_rhythm" in shown:
        lines += _rhythm_lines(report.get("change_rhythm") or {})
    if "verification_profile" in shown:
        lines += _verification_lines(report.get("verification_profile") or {})
    if "coordination_profile" in shown:
        lines += _coordination_lines(report.get("coordination_profile") or {})
    lines += _event_observation_lines(report.get("event_observation") or {})
    lines += _event_rhythm_lines(report.get("event_rhythm") or {})
    lines += _lifecycle_lines(report.get("tracker_lifecycle") or {})
    if kind == "repo":
        lines += _actor_directory_lines(report)
    lines += [""] + _reading_notes()
    lines += ["", "## 基準値・比較材料"]
    ref_lines = _reference_lines(report.get("reference"))
    lines += ref_lines or [
        "- このレポートには外部基準値はありません。観測値を基準値で置き換えていません。"
    ]
    tendencies = _evidence_tendency_nodes(report)
    lines += ["", "## 傾向"]
    for label, node in tendencies:
        lines += _tendency_lines(label, node)[:1]
    lines += ["", "## 傾向の強さと確からしさ"]
    for label, node in tendencies:
        lines += _tendency_lines(label, node)
    lines += [""] + _gap_lines(report)
    lines += ["", "## 言えること / 言えないこと"]
    extra = [
        EVIDENCE_DISCLAIMER,
        SURFACE_LIMITATION,
        RHYTHM_LIMITATION,
        RHYTHM_WINDOW_NOTE,
        RHYTHM_TIMESTAMP_LIMITATIONS,
        TENDENCY_CHANGE_NOTE,
    ]
    if kind == "actor":
        extra.extend(
            actor_basis_notices(
                subject.get("selection"),
                subject.get("attribution_state"),
            )
        )
    persisted_limitations = list(report.get("limitations") or [])
    if kind == "actor":
        persisted_limitations = without_actor_basis_notices(persisted_limitations)
    extra += persisted_limitations
    for note in _unique(extra):
        lines.append(f"- {note}")
    lines += [
        "",
        "## 再現情報",
        f"- 分析 SHA: `{prov.get('analyzed_commit_sha')}`",
        f"- 定義版: {prov.get('definition_version')}",
        (
            f"- 分析範囲(machine): {prov.get('analysis_scope')}"
            "（tenant=verified/claimed identity、actor_cluster=repo-local Git cluster。"
            "どちらも表示basis・本人同意・本人性を単独では証明しません）"
            if kind == "actor"
            else f"- 分析範囲: {prov.get('analysis_scope')}（repo=リポジトリの人間 commit）"
        ),
        f"- identity の要約ハッシュ: {prov.get('identity_digest') or 'なし'}（生メールは含みません）",
        f"- 入力ハッシュ: forge={((prov.get('input_digests') or {}).get('forge'))} "
        f"tracker={((prov.get('input_digests') or {}).get('tracker'))} "
        f"license={((prov.get('input_digests') or {}).get('license_evidence'))}",
        f"- Git window: {_window_text(prov.get('git_window') or coverage.get('git_window'))}",
        f"- Forge/Tracker window: {_window_text(prov.get('event_window') or coverage.get('event_window'))}",
        "",
    ]
    return "\n".join(lines)


def _surface_lines(profile: dict[str, Any]) -> list[str]:
    lines = [
        "### 作業領域プロファイル（surface）",
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
        "### 変更提出の間隔（change rhythm）",
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
    lines = ["### 検証の観測（test path heuristic。QA 適性ではない）"]
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


def _tendency_label(value: Any) -> str:
    if not isinstance(value, str) or not value:
        return "未証明"
    if value.endswith("_surface_prominent"):
        name = value[: -len("_surface_prominent")]
        return f"{name}系surfaceが相対的に多い傾向"
    mapping = {
        "regular_submission_direction": "定期的な変更提出の傾向が観測される",
        "rhythm_observed": "変更提出の間隔が観測される",
    }
    return mapping.get(value, value)


def _tendency_lines(label: str, node: Any) -> list[str]:
    if not isinstance(node, dict):
        return [f"- {label}: 未証明"]
    if node.get("kind") in {"not_proven", "not_observed", "not_comparable"}:
        return [f"- {label}: {_obs(node)}"]
    basis = node.get("basis") or {}
    sources = basis.get("source") or []
    source_text = ", ".join(sources) if isinstance(sources, list) else str(sources)
    return [
        f"- {label}: {_tendency_label(node.get('value'))}",
        f"  - 根拠: {basis.get('metric')} observed={basis.get('observed')} "
        f"n={basis.get('n')} denominator={basis.get('denominator')} "
        f"window={_window_text(basis.get('window'))} source={source_text}",
        f"  - 傾向の強さ: {node.get('strength') or '—'}",
        f"  - 確からしさ: {node.get('confidence') or '—'}",
        f"  - 注意: {'; '.join(node.get('limitations') or [])}",
    ]


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
        lines.append(f"| … | {len(actors) - 50} more |  |  |  |  |")
    return lines


def _reading_notes() -> list[str]:
    return [
        "### 数値の読み方（単位・分母・母数）",
        "- 件数の単位は commits / days / events です。比率は 0〜1 で、分母（n=）を併記します。",
        "- 0 件は「この範囲で該当証拠が無かった」です。未観測（not_observed）は「測れなかった」です。",
        "- surface の分母は、merge を除く人間 commit のうち path が取れたものです。",
        "- rhythm の分母は observation_date から 180 日以内の Git author timestamp です。",
    ]


def _gap_lines(report: dict[str, Any]) -> list[str]:
    coverage = report.get("input_coverage") or {}
    lines = ["## 比較不能・未観測・未証明"]
    for key in ("git", "forge", "tracker", "window_alignment", "event_window", "tracker_window"):
        node = coverage.get(key)
        if isinstance(node, dict) and node.get("kind") in {"not_observed", "not_proven"}:
            lines.append(f"- {key}: {_obs(node)}")
    observed = report.get("project_observed")
    if isinstance(observed, dict) and observed.get("kind") == "not_observed":
        lines.append(f"- {PROJECT_OBSERVED_MISSING_NOTE}")
    if len(lines) == 1:
        lines.append("- この入力では、追加の比較不能項目は記録されていません。")
    return lines


def _evidence_tendency_nodes(report: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    prov = report.get("provenance") or {}
    window = _window_text(prov.get("git_window"))
    return [
        (
            "作業領域",
            surface_tendency(
                report.get("surface_profile") or {},
                window=window,
                source=["git:path"],
            ),
        ),
        (
            "変更提出間隔",
            rhythm_tendency(
                report.get("change_rhythm") or {},
                window=window,
                source=["git:author_timestamp"],
            ),
        ),
    ]


def render_project_markdown(report: dict[str, Any]) -> str:
    declared = report.get("declared") or {}
    observed = report.get("observed")
    prov = report.get("provenance") or {}
    coverage = (observed or {}).get("input_coverage") or {}
    lines = [
        "# TEP project レポート",
        "",
        "## このレポートは誰・何を対象にしたか",
        "- 案件の宣言（declared）と、Git から見た運用の形（observed）です。会社評価ではありません。",
        f"- project_id: {_obs(declared.get('project_id'))}",
        "",
        "## 何を入力として見たか",
        "- declared は案件所有者が書いた TOML です。CLI は空欄を埋めません。",
        f"- {_coverage_line(coverage, 'git', 'Git 履歴を観測した', 'Git 履歴は見ていない（declared のみ）')}",
        f"- {_coverage_line(coverage, 'forge', 'project 側の forge export を使った', 'project の forge export は未提供')}",
        f"- {_coverage_line(coverage, 'tracker', 'project 側の tracker export を使った', 'project の tracker export は未提供')}",
        "",
        "## 何を見ていないか",
        "- 会社の良し悪し、採用判定、actor 個人の履歴はこのレポートの対象外です。",
        "- forge/tracker を付けない限り、project の review / issue 運用は未観測です。",
        "",
        "## 案件側の宣言",
        f"- 180 日活動日の下限: {_obs((declared.get('change_rhythm') or {}).get('active_days_180d_min'))}",
        f"- 間隔中央値の上限: {_obs((declared.get('change_rhythm') or {}).get('median_gap_days_max'))}",
        f"- 間隔 p90 の上限: {_obs((declared.get('change_rhythm') or {}).get('p90_gap_days_max'))}",
        f"- 必要な surface: {_obs(declared.get('surfaces'))}",
        f"- 必要な verification: {_obs(declared.get('verification'))}",
        f"- 必要な入力: {_obs(declared.get('inputs'))}",
        "",
        "## 観測された数値",
    ]
    if not observed or observed.get("kind") == "not_observed":
        lines.append(
            f"- {_obs(observed or {'kind': 'not_observed', 'reason': 'repository_not_provided'})}"
        )
    else:
        lines += _surface_lines(observed.get("surface_profile") or {})
        lines += _rhythm_lines(observed.get("change_rhythm") or {})
        lines += _verification_lines(observed.get("verification_profile") or {})
        lines += _coordination_lines(observed.get("coordination_profile") or {})
        lines += _event_observation_lines(observed.get("event_observation") or {})
        lines += _event_rhythm_lines(observed.get("event_rhythm") or {})
        lines += _lifecycle_lines(observed.get("tracker_lifecycle") or {})
    lines += [""] + _reading_notes()
    lines += [
        "- declared は要求です。observed は Git（と明示した local export）の観測です。混ぜません。",
        "",
        "## 基準値・比較材料",
    ]
    ref_lines = _reference_lines(report.get("reference"))
    lines += ref_lines or ["- このレポートには外部基準値はありません。宣言を観測値で埋めません。"]
    observed_block = observed if isinstance(observed, dict) else {}
    tendencies = [
        (
            "作業領域",
            surface_tendency(
                observed_block.get("surface_profile") or {},
                window=_window_text(prov.get("git_window")),
                source=["git:path"],
            ),
        ),
        (
            "変更提出間隔",
            rhythm_tendency(
                observed_block.get("change_rhythm") or {},
                window=_window_text(prov.get("git_window")),
                source=["git:author_timestamp"],
            ),
        ),
    ]
    lines += ["", "## 傾向"]
    for label, node in tendencies:
        lines += _tendency_lines(label, node)[:1]
    lines += ["", "## 傾向の強さと確からしさ"]
    for label, node in tendencies:
        lines += _tendency_lines(label, node)
    project_for_gaps = dict(report)
    project_for_gaps["input_coverage"] = coverage
    lines += [""] + _gap_lines(project_for_gaps)
    lines += [
        "",
        "## 言えること / 言えないこと",
        f"- {EVIDENCE_DISCLAIMER}",
        f"- {TENDENCY_CHANGE_NOTE}",
        "- このレポートだけで採用の合否を決めてはいけません。",
        "",
        "## 再現情報",
        f"- 定義版: {prov.get('definition_version')}",
        f"- 入力ハッシュ: project={(prov.get('input_digests') or {}).get('project')} "
        f"forge={(prov.get('input_digests') or {}).get('forge')} "
        f"tracker={(prov.get('input_digests') or {}).get('tracker')}",
        f"- Git window: {_window_text(prov.get('git_window'))}",
        "",
    ]
    return "\n".join(lines)


def _alignment_actor_basis_line(subject: dict[str, Any]) -> tuple[str, str, str]:
    """Return (subject line, input line, notice) without inferring consent."""

    cid = subject.get("actor_canonical_id")
    state = subject.get("actor_attribution_state")
    basis = classify_actor_basis(subject.get("actor_selection"), state)
    notice = actor_basis_notice(basis)
    if basis is ActorBasis.PUBLIC_INFERRED:
        return (
            f"公開Git上のactor cluster観測（actor `{cid}`）と案件宣言"
            f"（project `{subject.get('project_id')}`）の軸ごとの並びです。"
            "実在人物との同一性は証明していません。",
            "- actor observed は公開Git上のactor cluster観測です。"
            "project observed は対象リポジトリの運用観測です。",
            notice,
        )
    if basis is ActorBasis.ADMIN_VERIFIED:
        subject_basis = (
            "管理対象リポジトリの identity 定義（attribution_state=verified）に基づく"
            "admin-authorized actor観測"
        )
    elif basis is ActorBasis.SELF_CLAIMED:
        subject_basis = "attribution_state=claimed と記録された identity に基づく本人向けactor観測"
    elif basis is ActorBasis.EXPLICIT_NONCONSENT:
        return (
            f"明示identity（attribution_state={state}）により選択されたactor観測"
            f"（actor `{cid}`）と案件宣言（project `{subject.get('project_id')}`）の軸ごとの並びです。"
            "本人同意または本人性は証明していません。",
            "- actor observed は明示identityで選択された非同意actor観測です。"
            "project observed は対象リポジトリの運用観測です。",
            notice,
        )
    else:
        return (
            f"表示根拠を確認できないactor観測（actor `{cid}`）と案件宣言"
            f"（project `{subject.get('project_id')}`）の軸ごとの並びです。"
            "本人同意または本人性は証明していません。",
            "- actor observed の selection / attribution_state が欠落または不整合です。"
            "project observed は対象リポジトリの運用観測です。",
            notice,
        )
    return (
        f"{subject_basis}（actor `{cid}`）と案件宣言（project `{subject.get('project_id')}`）の軸ごとの並びです。",
        "- actor observed は actor レポートの観測です。"
        "project observed は対象リポジトリの運用観測です。",
        notice,
    )


def render_alignment_markdown(report: dict[str, Any]) -> str:
    prov = report.get("provenance") or {}
    subject = report.get("subject") or {}
    subject_line, input_line, actor_notice = _alignment_actor_basis_line(subject)
    lines = [
        "# TEP alignment レポート",
        "",
        "## このレポートは誰・何を対象にしたか",
        f"- {subject_line}",
        f"- actor repo SHA: `{(prov.get('actor_commit_sha') or prov.get('analyzed_commit_sha'))}`",
        f"- project repo SHA: `{prov.get('project_commit_sha')}`",
        f"- {ALIGNMENT_NOTICE}",
        "",
        "## 何を入力として見たか",
        input_line,
        "- declared は project TOML です。観測と混ぜません。",
        "",
        "## 何を見ていないか",
        "- 総合点、順位、適合率、採用推奨は計算していません。",
        "- Git-only では review / issue triage / stakeholder 活動は未観測です。",
        "",
        "## 案件側の宣言",
        f"- surfaces: {_obs((report.get('declared') or {}).get('surfaces'))}",
        f"- verification: {_obs((report.get('declared') or {}).get('verification'))}",
        f"- inputs: {_obs((report.get('declared') or {}).get('inputs'))}",
        "",
        "## 観測された数値 / 軸ごとの並び",
    ]
    project_missing = (report.get("project_observed") or {}).get("kind") == "not_observed"
    if project_missing:
        lines.append(f"- {PROJECT_OBSERVED_MISSING_NOTE}")
    for axis in report.get("axes") or []:
        comparison = axis.get("comparison")
        label = COMPARISON_JA.get(comparison, comparison)
        lines.append(
            f"- {axis.get('axis')}: {label}。"
            f"actor観測={_obs(axis.get('actor_observed') or axis.get('observed'))} / "
            f"project実測={_obs(axis.get('project_observed'))} / "
            f"宣言={_obs(axis.get('declared'))}。"
            f"actor_n={axis.get('actor_n')} project_n={axis.get('project_n')} "
            f"actor_denominator={axis.get('actor_denominator')} "
            f"project_denominator={axis.get('project_denominator')} "
            f"actor_source={axis.get('actor_source')} "
            f"project_source={axis.get('project_source')} "
            f"actor_window={_window_text((axis.get('actor_basis') or {}).get('window'))} "
            f"project_window={_window_text((axis.get('project_basis') or {}).get('window'))} "
            f"coverage={(axis.get('coverage') or {}).get('status')}。"
            f"比較不能={axis.get('incomparable_reason') or 'なし'}。"
            f"根拠={', '.join(axis.get('evidence_paths') or [])}"
        )
    lines += [""] + _reading_notes()
    lines += [
        "- overlap は重なり、observed_zero は 0 件、not_observed は測れない、not_declared は要求なしです。",
        "- actor と project の n・denominator・source・window は混ぜません。",
        "",
        "## 基準値・比較材料",
    ]
    ref_lines = _reference_lines(report.get("reference"))
    lines += ref_lines or ["- 基準は project declared と、提供された場合の project observed です。"]
    lines += ["", "## 傾向"]
    for axis in report.get("axes") or []:
        name = axis.get("axis")
        lines += _tendency_lines(f"actor {name}", axis.get("actor_tendency"))[:1]
        lines += _tendency_lines(f"project {name}", axis.get("project_tendency"))[:1]
        rel = axis.get("relationship") or {}
        lines.append(
            f"- relationship {name}: {rel.get('kind')}（similar_direction は採用・適合ではない）"
        )
    lines += ["", "## 傾向の強さと確からしさ"]
    for axis in report.get("axes") or []:
        name = axis.get("axis")
        lines += _tendency_lines(f"actor {name}", axis.get("actor_tendency"))
        lines += _tendency_lines(f"project {name}", axis.get("project_tendency"))
        rel = axis.get("relationship") or {}
        lines.append(f"- relationship {name} 確からしさ: {rel.get('confidence')}")
    lines += [""] + _gap_lines(report)
    lines += [
        "",
        "## 言えること / 言えないこと",
        f"- {ALIGNMENT_NOTICE}",
        f"- {EVIDENCE_DISCLAIMER}",
        f"- {actor_notice}",
        f"- {TENDENCY_CHANGE_NOTE}",
        "- この並びだけで採用の合否を決めてはいけません。",
        "",
        "## 再現情報",
        f"- 分析 SHA: `{prov.get('analyzed_commit_sha')}`",
        f"- 定義版: {prov.get('definition_version')}",
        f"- identity の要約ハッシュ: {prov.get('identity_digest')}",
        f"- actor report digest: {report.get('actor_report_digest')}",
        f"- project report digest: {report.get('project_report_digest')}",
        f"- 入力ハッシュ: forge={(prov.get('input_digests') or {}).get('forge')} "
        f"tracker={(prov.get('input_digests') or {}).get('tracker')} "
        f"project={(prov.get('input_digests') or {}).get('project')}",
        f"- Git window: {_window_text(prov.get('git_window'))}",
        f"- event window: {_window_text(prov.get('event_window'))}",
        "",
    ]
    return "\n".join(lines)
