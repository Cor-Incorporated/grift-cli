# Migrating to the 0.9.5 candidate

Pass the full directory produced by `grift actor --out DIR` to the recipient.
With the original Git revision available locally, both `grift verify DIR --repo REPO` and `grift verify DIR/repo-report.json --repo REPO` validate the complete collection. Supply the original identity with `--identity FILE` when applicable. A detached JSON member returns exit 2 with instructions to obtain the directory.

Collections created by 0.9.3 can still be verified from their original directory. To reproduce a standalone report from an earlier definition version, use the CLI that produced it, or regenerate it using the new definition.

When contributing a report-v1 file, omitting `--purpose` selects `reference-distributions`. Choose report-v2 for outcome linkage. An unsupported purpose on report-v1 now stops before writing a contribution or opening a pull request. See the [usage guide](usage.md) for disclosure options.
