"""監査 #9 — `min_share` の受理と拒否を実 TOML で通す。

`_with_min_share` は 4 つの経路で入力を拒否するが、既存のテストは
`declared_view` に手組みの dict を渡していた。手組みの dict は
`tomllib` が実際に何を返すかを確かめないので、TOML では到達しない形を
検証していたかもしれず、逆に TOML でしか起きない形（`min_share` が
テーブルではなく float になる、など）は一度も通っていなかった。

ここでは案件担当者が実際に書く TOML 文字列をファイルに書き、
`load_project_toml` → `declared_view` の本番経路をそのまま通す。

拒否のメッセージは原因を名指すこと。「不正」だけでは、案件担当者は
どのキーをどう直せばよいか分からない。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tep_core.project import declared_view, load_project_toml
from tep_core.secrets_guard import InputValidationError

_HEAD = 'schema_version = "tep-project-v1"\nproject_id = "acme-portal"\n\n'


def _declared_from_toml(tmp_path: Path, body: str) -> dict:
    path = tmp_path / "project.toml"
    path.write_text(_HEAD + body, encoding="utf-8")
    return declared_view(load_project_toml(path))


# --------------------------------------------------------------------------
# 正常系: TOML に書いた床が declared までそのまま届く
# --------------------------------------------------------------------------


def test_a_floor_written_in_toml_reaches_the_declared_view(tmp_path: Path) -> None:
    declared = _declared_from_toml(
        tmp_path,
        "[requirements.surfaces]\n"
        'required = ["backend", "frontend"]\n\n'
        "[requirements.surfaces.min_share]\n"
        "backend = 0.4\n\n"
        "[requirements.verification]\n"
        'required = ["unit", "e2e"]\n\n'
        "[requirements.verification.min_share]\n"
        "e2e = 0.1\n",
    )
    assert declared["surfaces"]["min_share"] == {"backend": pytest.approx(0.4)}
    assert declared["verification"]["min_share"] == {"e2e": pytest.approx(0.1)}
    # 床を書かなかった要求は presence のまま残る。
    assert "frontend" not in declared["surfaces"]["min_share"]


# --------------------------------------------------------------------------
# 拒否 4 経路。いずれも原因を名指す。
# --------------------------------------------------------------------------


def test_a_floor_on_a_type_not_in_required_is_refused(tmp_path: Path) -> None:
    """`required` に無い型の床は、比較する相手がいないので受理しない。"""
    with pytest.raises(InputValidationError) as exc:
        _declared_from_toml(
            tmp_path,
            "[requirements.verification]\n"
            'required = ["unit"]\n\n'
            "[requirements.verification.min_share]\n"
            "e2e = 0.3\n",
        )
    message = str(exc.value)
    assert "requirements.verification.min_share.e2e" in message, message
    assert "not in required" in message, message


def test_a_non_numeric_floor_is_refused(tmp_path: Path) -> None:
    with pytest.raises(InputValidationError) as exc:
        _declared_from_toml(
            tmp_path,
            "[requirements.verification]\n"
            'required = ["unit"]\n\n'
            "[requirements.verification.min_share]\n"
            'unit = "high"\n',
        )
    message = str(exc.value)
    assert "requirements.verification.min_share.unit" in message, message
    assert "must be a number" in message, message


def test_a_floor_outside_zero_to_one_is_refused(tmp_path: Path) -> None:
    """床は share なので 1 を超えられない。3 は「3 割」ではない。"""
    with pytest.raises(InputValidationError) as exc:
        _declared_from_toml(
            tmp_path,
            "[requirements.surfaces]\n"
            'required = ["backend"]\n\n'
            "[requirements.surfaces.min_share]\n"
            "backend = 3\n",
        )
    message = str(exc.value)
    assert "requirements.surfaces.min_share.backend" in message, message
    assert "between 0 and 1" in message, message


def test_a_min_share_that_is_not_a_table_is_refused(tmp_path: Path) -> None:
    """TOML でしか起きない形: 型ごとの表を書かず、床を 1 つの値で書いた。"""
    with pytest.raises(InputValidationError) as exc:
        _declared_from_toml(
            tmp_path,
            '[requirements.surfaces]\nrequired = ["backend"]\nmin_share = 0.4\n',
        )
    message = str(exc.value)
    assert "requirements.surfaces.min_share" in message, message
    assert "must be a table" in message, message


# --------------------------------------------------------------------------
# 床を書かない既存の brief は意味を変えない
# --------------------------------------------------------------------------


def test_a_brief_without_any_floor_carries_no_min_share(tmp_path: Path) -> None:
    declared = _declared_from_toml(
        tmp_path,
        '[requirements.surfaces]\nrequired = ["backend"]\n',
    )
    assert "min_share" not in declared["surfaces"]
