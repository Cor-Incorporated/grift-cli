"""Markdown rendering. Units required. No grade vocabulary. No person scorecards."""

from __future__ import annotations

from typing import Any

# P0-d-2: first-party merges are not narrated as upstream_sync.
_ORIGIN_ORDER = (
    "tenant_unique",
    "tenant_merge_or_sync",
    "upstream_sync",
    "inherited_upstream",
    "unresolved",
    "ambiguous_origin",
    "tenant_derivative",
    "external_upstream_contribution",
    "template_inherited",
    "generated_or_vendor",
    "bot",
)

_DISPLAY_NAME = {
    "tenant_merge_or_sync": "merge commits (PR flow)",
}

_SKIP_NOT_OBSERVED = frozenset({"upstream_sync", "tenant_merge_or_sync"})


def _fmt_obs(obs: dict[str, Any], *, fallback: str = "not observed") -> str:
    if obs.get("kind") == "not_observed":
        return f"not observed ({obs.get('reason', 'unspecified')})"
    value = obs.get("value")
    unit = obs.get("unit", "")
    sample = obs.get("sample_size")
    if sample is not None:
        return f"{value} {unit} (n={sample} days)"
    return f"{value} {unit}".strip() if unit else fallback


def shared_block(report: dict[str, Any]) -> list[str]:
    """P1a: 3-5 line copy-pasteable summary. Numbers+units+n+definition version
    only. No absolute paths, no grade vocabulary. One-line reader's-guide
    pointer included (P1g)."""
    prov = report["provenance"]
    scope = prov.get("analysis_scope")
    lines = [
        f"- tool: {prov['tool_name']} {prov['tool_version']} (method {prov.get('method_name') or 'TEP'}, definition {prov['definition_version']})",
        f"- scope: {scope} (analyzed at commit `{prov['analyzed_commit_sha'][:12]}`)",
    ]
    tests = report.get("test_frameworks") or {}
    if tests.get("kind") == "observed":
        cochange = (report.get("test_cochange") or {}).get("all_time") or {}
        if cochange.get("kind") == "observed":
            if cochange.get("narrate_rate", True):
                lines.append(
                    f"- test co-change: {cochange['value']} ratio ({cochange['cochanged']} of {cochange['population']} commits)"
                )
            else:
                lines.append(
                    f"- test co-change: not narrated (insufficient_population; {cochange['cochanged']} of {cochange['population']} commits)"
                )
    activity = report.get("activity") or {}
    tenant = activity.get("tenant_commits") or {}
    if tenant.get("kind") == "observed" and scope == "tenant":
        lines.append(f"- tenant commits: {tenant['value']} commits")
    lines.append("- 読み方: 本レポートは証拠であり判定ではない（docs/norms.md 参照）")
    lines.append("- Reading: this report is evidence, not a verdict (see docs/norms.md)")
    return lines


def render_markdown(report: dict[str, Any]) -> str:
    prov = report["provenance"]
    identity = report["identity"]
    lineage = report["lineage"]
    origin = report["origin"]
    activity = report["activity"]
    core = report["core_activity_period"]
    tests = report["test_frameworks"]
    repo = report.get("repository") or {}

    lines: list[str] = [
        "# TEP analysis",
        "",
        "## Shared block (copy-pasteable)",
        *shared_block(report),
        "",
        "## Provenance",
        f"- method: {prov.get('method_name') or 'TEP'}",
        f"- tool: {prov['tool_name']} {prov['tool_version']}",
        f"- definition version: {prov['definition_version']}",
        f"- analyzed commit SHA: `{prov['analyzed_commit_sha']}`",
        f"- analyzed at: {prov['analyzed_at']}",
        "",
        "## Repository",
        f"- name: {repo.get('name') or 'unknown'}",
        f"- remote: {repo.get('remote') or 'none'}",
        "",
        "## Lineage",
        f"- is_fork: {str(lineage['is_fork']).lower()}",
        f"- parent: {lineage['parent'] or 'none'}",
        f"- has_upstream_lineage: {str(lineage['has_upstream_lineage']).lower()}",
        "",
        "## Identity",
        (
            f"- pending_attribution: {str(identity['pending_attribution']).lower()} "
            f"({identity['actor_count']} configured actors)"
        ),
        "",
        "## Origin (commits)",
    ]
    for name in _ORIGIN_ORDER:
        obs = origin.get(name)
        if not obs:
            continue
        if obs.get("kind") == "not_observed" and name in _SKIP_NOT_OBSERVED:
            continue
        if (
            name == "inherited_upstream"
            and not lineage.get("has_upstream_lineage")
            and obs.get("kind") == "observed"
            and obs.get("value") == 0
        ):
            continue
        label = _DISPLAY_NAME.get(name, name)
        lines.append(f"- {label}: {_fmt_obs(obs)}")
    lines += [
        "",
        "## Activity (tenant_unique commits)",
        f"- tenant commits: {_fmt_obs(activity['tenant_commits'])}",
        f"- active days: {_fmt_obs(activity['active_days'])}",
        f"- commits per active day: {_fmt_obs(activity['commits_per_active_day'])}",
        (
            "- commits per active day (median): "
            f"{_fmt_obs(activity['commits_per_active_day_median'])}"
        ),
        f"- active days (13 weeks): {_fmt_obs(activity['active_days_13w'])}",
        "",
        "## Core activity period",
    ]
    if core.get("kind") == "not_observed":
        lines.append(f"- not observed ({core.get('reason')})")
    else:
        share_pct = round(float(core["share"]) * 100, 1)
        lines.append(
            f"- {core['start']} to {core['end']} "
            f"({share_pct} percent of tenant_unique commits; {core['unit']}; "
            f"definition {core['definition_version']})"
        )
        if activity["commits_per_active_day_median"].get("sample_size", 99) < 5:
            lines.append("- comparison narrative omitted: median sample size is below 5 days")
    lines += ["", "## Test frameworks"]
    if tests.get("kind") == "not_observed":
        lines.append(f"- not observed ({tests.get('reason')})")
    else:
        names = ", ".join(tests.get("names") or []) or "none named"
        lines.append(f"- observed: {names} (boolean {tests.get('value')})")
    lines += [
        "",
        "## Test co-change",
        "（何を測るか / What this measures: 本番コードを変えたコミットのうち、同じコミットでテストも変更した割合。高い=変更にテストが伴う習慣。テストが前提でない仕事は正当に低くなる — the share of production-changing commits whose same commit also changed tests. High = the habit of pairing changes with tests. Work where tests are not the norm legitimately lands low.)",
        f"- {_fmt_metric_block(report.get('test_cochange'))}",
    ]
    interp = report.get("interpretation") or {}
    lines += _fmt_interp_line("co-change", interp.get("test_cochange"))
    lines += [
        "",
        "## Rework",
        "（何を測るか / What this measures: 作った直後に手直しが発生した傾向の観測。バグ件数でも品質でもなく、件名慣習の影響を受けるため比較・合否には使えない — observed tendency of immediate rework after fresh changes. Not a bug count, not quality; subject-convention dependent, so never use for comparisons or pass/fail.)",
        *_fmt_rework_lines(report.get("rework")),
    ]
    lines += _fmt_interp_line("corrective rework", interp.get("corrective_rework"))
    lines += [
        "",
        "## Survival (tau=180 days)",
        "（何を測るか / What this measures: 6ヶ月後も残っている行の割合。1.0に近い=書いたものが残り続けている — the share of lines still present after 6 months. Near 1.0 = what was written keeps living.)",
        f"- {_fmt_metric_block(report.get('survival'))}",
    ]
    lines += ["", *(_fmt_context_lines(report.get("context_profile")))]
    lines += ["", *readers_guide_lines()]
    lines.append("")
    return "\n".join(lines)


def _fmt_langs(value: Any) -> str:
    """Shares as human-readable percents; empty-safe (#50)."""
    if not isinstance(value, dict) or not value:
        return "not observed"
    top = list(value.items())[:3]
    return ", ".join(f"{name} {share * 100:.0f}%" for name, share in top) or "not observed"


def _fmt_context_lines(ctx: dict[str, Any] | None) -> list[str]:
    if not ctx or ctx.get("kind") != "observed":
        if ctx and ctx.get("kind") == "not_observed":
            return ["## Context profile", f"- not observed ({ctx.get('reason')})"]
        return []

    def val(key: str) -> Any:
        node = ctx.get(key) or {}
        return node.get("value")

    lines = [
        "## Context profile (observational; not a ranking)",
        "（このrepoのかたち / The shape of this repo: 協働・活動密度・プロセスの分類。序列ではなく、数値の読み方を条件付ける文脈 — collaboration, activity density, and process classification. Not a ranking; context that conditions how to read the numbers.)",
        (
            f"- collaboration: {val('collaboration_class')} "
            f"({val('resolved_human_actors')} resolved human actors; "
            f"top actor share {val('top_actor_share')} ratio)"
        ),
        (
            f"- lifecycle: {val('lifecycle_stage')} "
            f"(active_days_180d {val('active_days_180d')} days = 直近180日で人がコミットした日数 / unique days with human commits in the last 180 days; "
            f"days_since_last_human_commit {val('days_since_last_human_commit')} = 最終コミットからの日数 / days since the last human commit; "
            f"repo age {val('repo_age_days')} days)"
        ),
        f"- process: pr_flow_share {val('pr_flow_share')} ratio; conventional subjects {val('conventional_commit_share')} ratio",
        f"- languages (touch-share): {_fmt_langs(val('language_composition'))}",
    ]
    return lines


def readers_guide_lines() -> list[str]:
    """P1g: fixed reader's guide appended to every report.md (data-layer
    template, no LLM). Golden snapshots and vocab gates pin the wording."""
    return [
        "## この数値でしてはいけない判断 / Decisions these numbers must NOT be used for",
        "- このレポートは「観測できた証拠」であり、書かれていないことは「無かったこと」を意味しません / This report is observed evidence; what is not written does not mean it did not happen",
        "- 分布位置は同スコープ・同文脈の repo 間の位置であり、優劣の等級ではありません / Distribution positions are locations among same-scope, same-context repositories — not grades",
        "- 単独の数値での合否判断・他者との比較表の作成は TEP 非準拠です（docs/norms.md 参照） / Standalone pass/fail decisions and person-to-person comparison tables are non-compliant with the TEP norms (see docs/norms.md)",
        "- 観測には限界があります（各指標の limit 欄を参照してください） / Observations have limits (see each metric's limit notes)",
    ]


def _fmt_metric_block(obs: dict[str, Any] | None) -> str:
    if not obs:
        return "not observed (missing)"
    if obs.get("kind") == "not_observed":
        return f"not observed ({obs.get('reason')})"
    if "all_time" in obs:
        block = obs["all_time"]
        if block.get("kind") == "not_observed":
            return f"all-time not observed ({block.get('reason')})"
        rate = block.get("value")
        pop = block.get("population")
        unit = block.get("unit", "ratio")
        narrate = block.get("narrate_rate", True)
        if not narrate:
            return (
                "all-time not narrated (insufficient_population; "
                f"{pop}コミット中{block.get('cochanged')}件)"
            )
        return f"all-time {rate} {unit} (population {pop} commits)"
    if "corrective_rework_rate" in obs:
        return _fmt_rework_lines(obs)[0].lstrip("- ")
    if "survival_index" in obs:
        return (
            f"survival index {obs['survival_index']} {obs.get('unit')} "
            f"(tau {obs.get('tau_days')} days; {obs.get('files_sampled')} files; "
            f"{obs.get('lines_sampled')} lines)"
        )
    return "observed"


def _fmt_rework_lines(obs: dict[str, Any] | None) -> list[str]:
    if not obs:
        return ["- not observed (missing)"]
    if obs.get("kind") == "not_observed":
        return [f"- not observed ({obs.get('reason')})"]
    corr = obs.get("corrective_rework_rate") or {}
    touch = obs.get("path_retouch_rate") or {}
    window = obs.get("window_days")
    lines: list[str] = []
    if corr.get("kind") == "observed":
        if corr.get("narrate_rate", True):
            lines.append(
                f"- corrective rework (observational, subject-convention dependent; "
                f"not an evidence claim): {corr.get('value')} {corr.get('unit')} "
                f"({corr.get('corrective_commits')} of {corr.get('population')} "
                f"commits; {window} day window)"
            )
            lines.append(
                "- limit: corrective rework is fresh-work stability "
                "(recent paths needing an immediate fix/revert); "
                "it is not a bug count"
            )
        else:
            lines.append(
                "- corrective rework (observational, subject-convention dependent; "
                "not an evidence claim): not narrated (insufficient_population; "
                f"{corr.get('population')}コミット中{corr.get('corrective_commits')}件)"
            )
            lines.append(
                "- limit: corrective rework is fresh-work stability "
                "(recent paths needing an immediate fix/revert); "
                "it is not a bug count"
            )
    touch_pop = touch.get("population")
    if isinstance(touch_pop, int) and touch_pop < 20:
        lines.append(
            "- path retouch (observational, not an evidence claim): "
            "not narrated (insufficient_population; "
            f"{touch_pop}コミット中{touch.get('retouch_commits')}件)"
        )
    else:
        lines.append(
            "- path retouch (observational, not an evidence claim): "
            f"{touch.get('value')} {touch.get('unit')} "
            f"({touch.get('retouch_commits')} of {touch.get('population')} commits)"
        )
    return lines or ["- observed"]


def _fmt_interp_line(label: str, obs: dict[str, Any] | None) -> list[str]:
    if not obs or obs.get("kind") != "observed":
        return []
    return [
        f"- {label} {obs.get('value')} ({obs.get('analysis_scope')} scope) — "
        f"reference corpus {obs.get('reference_version')} (n={obs.get('n')}) "
        f"decile {obs.get('decile')}"
    ]
