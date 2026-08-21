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
    lines += ["", "## Test co-change", f"- {_fmt_metric_block(report.get('test_cochange'))}"]
    interp = report.get("interpretation") or {}
    lines += _fmt_interp_line("co-change", interp.get("test_cochange"))
    lines += ["", "## Rework", *_fmt_rework_lines(report.get("rework"))]
    lines += _fmt_interp_line("corrective rework", interp.get("corrective_rework"))
    lines += ["", "## Survival (tau=180 days)", f"- {_fmt_metric_block(report.get('survival'))}"]
    lines.append("")
    return "\n".join(lines)


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
