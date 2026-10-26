#!/bin/bash
# Rebuild the four synthetic repositories and run grift 0.8.0 on them.
#
# usage: run_080.sh WORKDIR
#   WORKDIR/synth/   synthetic repositories (recreated on every run)
#   WORKDIR/out080/  actor / project / align outputs (md and json)
# Set GRIFT to a grift 0.8.0 executable; the default is `grift` on PATH.
set -u
HERE="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$1"
GRIFT="${GRIFT:-grift}"
OUT="$WORK/out080"
rm -rf "$OUT" && mkdir -p "$OUT"
python3 -I "$HERE/tools/make_synth.py" "$WORK/synth" || exit 1
"$GRIFT" --version
for a in a b; do
  repo=$([ "$a" = a ] && echo ledger-api || echo shop-front)
  for fmt in md json; do
    "$GRIFT" actor "candidate-$a" "$WORK/synth/$repo" --identity "$HERE/inputs/identity-$a.toml" \
      --as-of 2026-10-20 --format "$fmt" --out "$OUT/actor-$a.$fmt" >/dev/null 2>"$OUT/actor-$a.$fmt.err"
    echo "actor $a $fmt rc=$?"
  done
done
for pair in p1:payments-api:p1-payments p2:storefront:p2-storefront; do
  IFS=: read -r id repo toml <<<"$pair"
  for fmt in md json; do
    "$GRIFT" project "$WORK/synth/$repo" --requirements "$HERE/inputs/$toml.toml" \
      --as-of 2026-10-20 --format "$fmt" --out "$OUT/project-$id.$fmt" \
      >/dev/null 2>"$OUT/project-$id.$fmt.err"
    echo "project $id $fmt rc=$?"
  done
done
for a in a b; do
  for p in p1 p2; do
    for fmt in md json; do
      "$GRIFT" align --actor-report "$OUT/actor-$a.json" --project-report "$OUT/project-$p.json" \
        --format "$fmt" --out "$OUT/align-$a-$p.$fmt" >/dev/null 2>"$OUT/align-$a-$p.$fmt.err"
      echo "align $a $p $fmt rc=$?"
    done
  done
done
"$GRIFT" verify "$OUT/actor-a.json" --repo "$WORK/synth/ledger-api" \
  --identity "$HERE/inputs/identity-a.toml"
echo "verify actor-a rc=$?"
"$GRIFT" verify "$OUT/actor-b.json" --repo "$WORK/synth/shop-front" \
  --identity "$HERE/inputs/identity-b.toml"
echo "verify actor-b rc=$?"
for r in ledger-api shop-front payments-api storefront; do
  echo "$r HEAD $(git -C "$WORK/synth/$r" rev-parse HEAD) commits $(git -C "$WORK/synth/$r" rev-list --count HEAD)"
done
