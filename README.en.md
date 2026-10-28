**English** | [日本語](https://github.com/Cor-Incorporated/grift-cli/blob/main/README.md)

# grift

grift shows what kind of code an engineer has changed, how much, and how often those changes came with tests. It reads this from git, the system that records every change to a codebase, and every number comes with the counts behind it. grift does not score or rank anyone.

## How you might use it

### If you are an engineer looking for a project

If you wrote a repository (the place where code and its change history live) on your own, run `grift repo` on it to see which areas you have worked in, how much, and how often your changes came with tests, all with counts. If you shared the repository with others, list yourself in an identity file (a list of who wrote under which email address) and use `grift actor` to count only your own changes. Either way, you can put checkable facts next to the experience listed on your résumé. You decide which repositories to show and whether to share them at all.

### If you introduce engineers to projects

You can use a record that a candidate chose to share as material when you explain why you recommend them. Pass the numbers on together with their counts, such as "12 of 40" (a made-up figure). The [usage norms](https://github.com/Cor-Incorporated/grift-cli/blob/main/docs/en/norms.md) treat cutting candidates on a single number, or ranking people, as non-compliant use.

### If you are looking for engineers for a project

Run `grift project --init --out .tep/project.toml` to get an empty template, and fill in the areas and testing practices you need. `grift align` then places each candidate's record next to those requirements, item by item. It produces no total score and no pass/fail result. Use the numbers to decide what to ask in an interview.

## Try it

Engineers can look at their own repository with three commands:

```bash
pipx install grift-cli
cd your-repo
grift repo
```

At run time grift needs only Python 3.11 or newer and git. The report is printed to your terminal; grift writes no files and sends nothing anywhere. Add `--out DIR` to save it, or `--format json` for machine-readable output. If your shell cannot find `grift`, run `pipx ensurepath` and open a new terminal.

The report text is currently in Japanese; the JSON output uses English keys.

## Reading the output

`grift repo` prints values like these for the whole repository. Each value comes with its count: how many out of how many.

- Parts changed (work surface): for each of 11 areas (tests, docs, CI, frontend, and so on), how many commits (recorded changes) touched files in that area.
- Pace of change (change rhythm): on how many days in the last 180 changes were made, and how many days passed between one change and the next. These are not working hours or speed.
- How tests are added (verification profile): the share of commits that include test files, and which kinds of tests they touch (unit, integration, and so on).
- People involved: how many commits each person made, listed in ID order rather than by count.

The JSON output (`--format json`) and the output of `grift analyze` also include:

- Origin: whose work each commit is, in 11 classes, such as commits by people listed in the identity file, by other people, by bots (automated accounts), generated files, and changes inherited from an upstream fork.
- Test co-change (`test_cochange` in JSON): of the commits that changed production code, the share that also changed tests in the same commit. For example (a made-up case), if 40 commits changed production code and 12 of them also changed tests, the report says 12 of 40.

`grift align` places a project's declared requirements next to the values counted from history, item by item. Each item is one of five outcomes: overlap, outside the declared range, zero, not observed, or not declared.

The `grift actor` Markdown (for an identity the person claimed, with a recorded consent) and the `grift project` Markdown open with plain Japanese sentences on how the work shows in the record. The `grift actor` and `grift align` Markdown also list questions to confirm in an interview. The [decision tables](https://github.com/Cor-Incorporated/grift-cli/blob/main/docs/en/trait-profile.md) pick them from the numbers; they never become a score or a type name. An actor report for an identity registered by an administrator, or for an actor inferred from a public repository, gets no sentences, and the output says why. Alignment questions follow the same rule: an identity the person claimed, with a recorded consent.

A value that could not be measured is never written as 0. It is written as "not observed" with a reason (`not_observed` in the output). A missing record does not mean missing experience. When the population (the total number of items counted) is below 20, the report text shows counts instead of rates.

The [metrics guide](https://github.com/Cor-Incorporated/grift-cli/blob/main/docs/en/metrics-guide.md) explains each number in plain language. The table that maps the terms used on griftai.org and cor-jp.com to CLI terms is in the [Japanese guide](https://github.com/Cor-Incorporated/grift-cli/blob/main/docs/metrics-guide.md#サイトの訳語と-cli-の語の対応表).

## Why we built it

When a recruiting agency or an IT staffing firm recommends an engineer for a project, most of what they have to go on is a résumé and an impression from an interview. Meanwhile, "activity" such as commit counts is easy to inflate with generative AI. Cor.Inc. built grift to pull out only the facts that can be checked in git history, together with how they were counted, and released it as open source under the MIT license.

grift's numbers can also move with changes made only for show. Some of the known ways to inflate them, such as the number of days with changes, are disclosed next to the numbers in the report.

## How grift differs from self-report assessments and résumés

A personality assessment such as MBTI gives you a type based on your answers to a questionnaire. A résumé is also written by the person it describes. Both reflect how people see themselves. (grift is not affiliated with MBTI in any way.)

grift asks no questions. It counts what is recorded in git and reports tendencies together with the counts behind them. It does not sort people into types or give them labels. Because the same point in history, the same list of people and the same grift version give the same numbers on anyone's machine, a recipient can recompute them. Getting the same number again is not proof that the number is correct, or that the work is good or better than anyone else's. Work that never reaches git, such as meetings, design discussions, or private repositories, is invisible to grift.

## TEP (Technical Evidence Pipeline)

TEP (Technical Evidence Pipeline) is the name of the method grift uses. It is a set of rules: pull checkable facts out of git history, report them with what was counted, over which period, and out of how many, and make it possible for a recipient to recompute them the same way. grift is the command that carries out these rules. No large language model (LLM) is involved in measuring.

How the numbers may be used is set out in seven [usage norms](https://github.com/Cor-Incorporated/grift-cli/blob/main/docs/en/norms.md). Among them: do not read a missing record as missing experience, do not cut candidates on a single number, do not profile third parties without consent, do not use it for surveillance, and do not weight several numbers into one score. Compliance with these norms is a condition of using the TEP name.

## Main commands

- `grift repo`: the record for the whole repository.
- `grift actor ID`: the record for one person (actor). The ID is a canonical_id from the identity file, or an actor id derived from history when there is no identity file.
- `grift project`: observe how the repository is run, or read a project's declared requirements (`--requirements`). `--init --out FILE` writes an empty requirements template.
- `grift align`: place declarations and records side by side, item by item. No overall score.
- `grift verify`: recompute a saved report under the same conditions and check that it matches. The result is `VERIFIED`, `MISMATCH`, or `CANNOT_VERIFY` (could not be checked).

To compare one person's record with a project's requirements:

```bash
grift actor candidate_001 --identity .tep/identity.toml --format both --out actor-report.json
grift project --requirements .tep/project.toml --format both --out project-out
grift align \
  --actor-report actor-report.json \
  --project-report project-out/project.json \
  --format both --out alignment-out
```

Collections of several people, the identity file, public forge fetch, signing, exit codes, and upgrading from earlier versions are covered in the [usage guide](https://github.com/Cor-Incorporated/grift-cli/blob/main/docs/en/usage.md).

## Data and network

grift runs on your machine and uses the network only when you ask it to, for example with `--fetch-public`, `grift update`, or `grift contribute --open`. Each of these is an explicit network path; the [usage guide](https://github.com/Cor-Incorporated/grift-cli/blob/main/docs/en/usage.md#operations-that-use-the-network) lists every one. This CLI has no feature that sends data to us automatically, and we will not add one to this CLI. If Cor.Inc. offers a separate application or service built on grift, that service's terms of service and privacy policy will set out how it handles data.

`grift contribute`, which submits report values for the reference distributions, runs only when you choose to. Submissions go to the public [tep-contributions](https://github.com/Cor-Incorporated/tep-contributions) repository, and with `--open` the final button is yours.

## GitHub Actions

```yaml
permissions:
  contents: read
steps:
  - uses: actions/checkout@v4
    with:
      fetch-depth: 0
      persist-credentials: false
  - uses: actions/setup-python@v5
    with:
      python-version: "3.12"
  - uses: Cor-Incorporated/grift-cli@v0.9.1
    with:
      scope: repo
      comment: false
```

The action runs `grift analyze`, writes a summary to `$GITHUB_STEP_SUMMARY`, and uploads report.md and report.json as artifacts. It never turns observed values into pass/fail results or thresholds.

- It needs the caller repository's full history and Python 3.11 or newer. A missing checkout or a shallow clone stops the run before measurement (fail-closed, exit 2). Invalid inputs also fail closed.
- Run it with `contents: read` and `comment: false`, so code from a pull request never receives a write token. The `comment: true` path is implemented, but this project's own CI runs read-only, so that path is unproven. Do not grant write permission to pull-request code until a trusted follow-up workflow exists.

## Documentation

- [Usage guide](https://github.com/Cor-Incorporated/grift-cli/blob/main/docs/en/usage.md)
- [How to read reports](https://github.com/Cor-Incorporated/grift-cli/blob/main/docs/en/metrics-guide.md)
- [Usage norms](https://github.com/Cor-Incorporated/grift-cli/blob/main/docs/en/norms.md)
- [Metric validation and limits](https://github.com/Cor-Incorporated/grift-cli/blob/main/docs/en/validation.md): the design choices behind the numbers and their limits, and results from 117 public repositories, including the comparisons that did not separate
- Output formats: [report-v1](https://github.com/Cor-Incorporated/grift-cli/blob/main/docs/en/report-schema.md), [export](https://github.com/Cor-Incorporated/grift-cli/blob/main/docs/en/export-schema.md), [identity](https://github.com/Cor-Incorporated/grift-cli/blob/main/docs/en/identity-schema.md); in Japanese: [report-v2](https://github.com/Cor-Incorporated/grift-cli/blob/main/docs/report-v2.md), [alignment](https://github.com/Cor-Incorporated/grift-cli/blob/main/docs/alignment-schema.md), [project](https://github.com/Cor-Incorporated/grift-cli/blob/main/docs/project-schema.md)
- [Changelog](https://github.com/Cor-Incorporated/grift-cli/blob/main/CHANGELOG.md) (in Japanese) and [0.9.1 migration notes](https://github.com/Cor-Incorporated/grift-cli/blob/main/docs/en/migration-v091.md)

Product site: [griftai.org](https://griftai.org) (Japanese).

## Contributing and support

- Questions and bug reports: [Issues](https://github.com/Cor-Incorporated/grift-cli/issues) on the public repository.
- To change the code or docs, start with [CONTRIBUTING.en.md](https://github.com/Cor-Incorporated/grift-cli/blob/main/CONTRIBUTING.en.md). The code of conduct is [CODE_OF_CONDUCT.md](https://github.com/Cor-Incorporated/grift-cli/blob/main/CODE_OF_CONDUCT.md).
- Report vulnerabilities as described in [SECURITY.md](https://github.com/Cor-Incorporated/grift-cli/blob/main/SECURITY.md), not in a public issue.
- To ask for removal of an email address in the test data (taken from public commit metadata), open an issue on the public repository. The [tep-contributions](https://github.com/Cor-Incorporated/tep-contributions) README describes a private contact channel. A proxy contact can keep your name out of it, but data already published in the corpus does not become private.

## License

MIT. See [LICENSE](https://github.com/Cor-Incorporated/grift-cli/blob/main/LICENSE).

## 日本語の概要

このページは PyPI でも表示されるため、日本語の要点をここに置いています。全文は[日本語の README](https://github.com/Cor-Incorporated/grift-cli/blob/main/README.md) をご覧ください。

grift を使うと、エンジニアがこれまでどんなコードを、どれくらい、テストで確かめながら変えてきたかを、git（コードの変更を 1 件ずつ記録する仕組み）に残った記録から件数つきで知ることができます。点数や順位はつけません。人材紹介会社や SES の営業が推薦の理由を説明するときにも、エンジニア本人が経歴書に確かめられる事実を添えるときにも使えます。

```bash
pipx install grift-cli
cd your-repo
grift repo
```

MBTI のような性格診断は、本人の回答からタイプを出します。grift は質問をせず、git に残った記録を数えて、傾向とその根拠の件数を出します。人をタイプに分けたり、名前を付けたりはしません（grift は MBTI と関係も提携もありません）。

手法の名前は TEP（Technical Evidence Pipeline）です。git の履歴から確かめられる事実を取り出し、数え方を添えて出し、受け取った側が同じ手順で計算し直せるようにする決まりを指します。数値の使い方は[利用規範（norms）](https://github.com/Cor-Incorporated/grift-cli/blob/main/docs/norms.md)で決めています。

- [コマンドの詳しい使い方](https://github.com/Cor-Incorporated/grift-cli/blob/main/docs/usage.md)
- [レポートの読み方](https://github.com/Cor-Incorporated/grift-cli/blob/main/docs/metrics-guide.md)
- [製品サイト griftai.org](https://griftai.org)
