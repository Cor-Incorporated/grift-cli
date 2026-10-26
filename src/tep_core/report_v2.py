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
from tep_core.report_v2_observed import (
    _actor_directory_lines,
    _coordination_lines,
    _event_observation_lines,
    _event_rhythm_lines,
    _lifecycle_lines,
    _reference_lines,
    _rhythm_lines,
    _surface_lines,
    _verification_lines,
)
from tep_core.report_v2_text import (
    _obs,
    _title_text,
    _unique,
    _window_text,
)
from tep_core.role_lens import emphasized_keys, emphasized_sections, lens_intro
from tep_core.tendency import rhythm_tendency, surface_tendency
from tep_core.trait_alignment import alignment_section
from tep_core.trait_sections import actor_section, project_section
from tep_core.trait_profile import not_shown_reason
from tep_core.v2_constants import (
    ACTIVE_DAYS_INFLATION_LIMITATION,
    ALIGNMENT_NOTICE,
    COMPARISON_JA,
    EVIDENCE_DISCLAIMER,
    FORGE_NOT_OBSERVED_NOTE,
    HISTORY_WINDOW_BASIS,
    PROJECT_OBSERVED_MISSING_NOTE,
    RHYTHM_LIMITATION,
    RHYTHM_TIMESTAMP_LIMITATIONS,
    RHYTHM_WINDOW_NOTE,
    SELECTIVITY_NOTICE_JA,
    SURFACE_LIMITATION,
    TENDENCY_CHANGE_NOTE,
    TENDENCY_CHANGE_NOTE_MD,
    TRACKER_NOT_OBSERVED_NOTE,
)


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
        else "リポジトリ全体の観測です。対象は Git working tree の人間 commit（repo）。個人の適性評価ではありません。"
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
    lines += ["", "## 傾向の確からしさ"]
    for label, node in tendencies:
        lines += _tendency_lines(label, node)
    lines += [""] + _gap_lines(report)
    lines += ["", "## 言えること / 言えないこと"]
    # Fixed notices come from the constants, not from report["notices"], so a
    # 0.7.x JSON renders the 0.8.0 wording; the JSON itself is what verify diffs.
    # norms §6 once per Markdown: the person-facing section carries it when shown.
    selectivity = [SELECTIVITY_NOTICE_JA] if not_shown_reason(report) is not None else []
    actor_notes = (
        [
            *actor_basis_notices(subject.get("selection"), subject.get("attribution_state")),
            *selectivity,
        ]
        if kind == "actor"
        else []
    )
    extra = [
        EVIDENCE_DISCLAIMER,
        SURFACE_LIMITATION,
        RHYTHM_LIMITATION,
        RHYTHM_WINDOW_NOTE,
        RHYTHM_TIMESTAMP_LIMITATIONS,
        ACTIVE_DAYS_INFLATION_LIMITATION,
        TENDENCY_CHANGE_NOTE_MD,
        *actor_notes,
    ]
    persisted_limitations = list(report.get("limitations") or [])
    if kind == "actor":
        persisted_limitations = without_actor_basis_notices(persisted_limitations)
    extra += [_md_note(note) for note in persisted_limitations]
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
    # ADR-0002: the plain sentences open the actor Markdown; the numbers follow.
    head = actor_section(report) if kind == "actor" else []
    return "\n".join([*head, *lines])


def _tendency_label(value: Any) -> str:
    if not isinstance(value, str) or not value:
        return "未証明"
    if value.endswith("_surface_prominent"):
        name = value[: -len("_surface_prominent")]
        return f"{name}系surfaceが相対的に多い傾向"
    mapping = {
        # Saved 0.8.0 payloads carry this label; it never meant a regular cadence.
        "regular_submission_direction": "変更のペース（変更リズム）が観測される",
        "rhythm_observed": "変更のペース（変更リズム）が観測される",
    }
    return mapping.get(value, value)


def _md_note(note: str) -> str:
    """The Markdown copy of a fixed note (strength is not printed since v0.9.0)."""
    return TENDENCY_CHANGE_NOTE_MD if note == TENDENCY_CHANGE_NOTE else note


def _tendency_lines(label: str, node: Any) -> list[str]:
    if not isinstance(node, dict):
        return [f"- {label}: 未証明"]
    if node.get("kind") in {"not_proven", "not_observed", "not_comparable"}:
        return [f"- {label}: {_obs(node)}"]
    basis = node.get("basis") or {}
    sources = basis.get("source") or []
    source_text = ", ".join(sources) if isinstance(sources, list) else str(sources)
    # ADR-0002: `strength` is not printed (two reports side by side read as a
    # stronger and a weaker person); JSON keeps it, deprecated, until the next schema.
    return [
        f"- {label}: {_tendency_label(node.get('value'))}",
        f"  - 根拠: {basis.get('metric')} observed={basis.get('observed')} "
        f"n={basis.get('n')} denominator={basis.get('denominator')} "
        f"window={_window_text(basis.get('window'))} source={source_text}",
        f"  - 確からしさ: {node.get('confidence') or '—'}",
        f"  - 注意: {'; '.join(_md_note(note) for note in node.get('limitations') or [])}",
    ]


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


def _history_text(prov: dict[str, Any]) -> str:
    """Surface counts cover the whole scoped history, not the 180-day window."""
    return _window_text({"end": prov.get("observation_date"), "basis": HISTORY_WINDOW_BASIS})


def _evidence_tendency_nodes(report: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    prov = report.get("provenance") or {}
    return [
        (
            "変えた部分の区分（作業領域）",
            surface_tendency(
                report.get("surface_profile") or {},
                window=_history_text(prov),
                source=["git:path"],
            ),
        ),
        (
            "変更のペース（変更リズム）",
            rhythm_tendency(
                report.get("change_rhythm") or {},
                window=_window_text(prov.get("git_window")),
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
        f"- 題名: {_title_text(declared.get('title'))}",
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
            "変えた部分の区分（作業領域）",
            surface_tendency(
                observed_block.get("surface_profile") or {},
                window=_history_text(prov),
                source=["git:path"],
            ),
        ),
        (
            "変更のペース（変更リズム）",
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
    lines += ["", "## 傾向の確からしさ"]
    for label, node in tendencies:
        lines += _tendency_lines(label, node)
    project_for_gaps = dict(report)
    project_for_gaps["input_coverage"] = coverage
    lines += [""] + _gap_lines(project_for_gaps)
    lines += [
        "",
        "## 言えること / 言えないこと",
        f"- {EVIDENCE_DISCLAIMER}",
        f"- {TENDENCY_CHANGE_NOTE_MD}",
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
    return "\n".join([*project_section(report), *lines])


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
        f"- 題名: {_title_text((report.get('declared') or {}).get('title'))}",
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
    # `relationship` stays in the JSON only: a direction next to a person reads
    # as fit (ADR-0002). The opening section lists overlaps and questions instead.
    lines += ["", "## 傾向"]
    for axis in report.get("axes") or []:
        name = axis.get("axis")
        lines += _tendency_lines(f"actor {name}", axis.get("actor_tendency"))[:1]
        lines += _tendency_lines(f"project {name}", axis.get("project_tendency"))[:1]
    lines += ["", "## 傾向の確からしさ"]
    for axis in report.get("axes") or []:
        name = axis.get("axis")
        lines += _tendency_lines(f"actor {name}", axis.get("actor_tendency"))
        lines += _tendency_lines(f"project {name}", axis.get("project_tendency"))
    lines += [""] + _gap_lines(report)
    lines += [
        "",
        "## 言えること / 言えないこと",
        # The selectivity notice (norms §6) is in the opening section's limits.
        f"- {ALIGNMENT_NOTICE}",
        f"- {EVIDENCE_DISCLAIMER}",
        f"- {ACTIVE_DAYS_INFLATION_LIMITATION}",
        f"- {actor_notice}",
        f"- {TENDENCY_CHANGE_NOTE_MD}",
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
    return "\n".join([*alignment_section(report), *lines])
