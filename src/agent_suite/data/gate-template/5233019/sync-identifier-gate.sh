#!/usr/bin/env bash
# Sync the canonical fail-closed identifier gate into a repo.
#
# The gate is a COPIED script, not a dependency. Eleven copies drifted apart
# because each was hand-edited in place; this script exists so that never
# happens again. It renders from ~/.config/agent-suite/gate-template and
# overwrites -- it never merges, and it never edits a repo copy in situ.
#
# The one thing it must not do is guess the denylist variable name. An earlier
# version hardcoded the shared org name FORBIDDEN_IDENTIFIERS; had it run, it
# would have pointed 13 user-account repos at a secret that does not exist
# there, disarming every gate while looking migrated. So the name is RESOLVED
# from two independent sources that must agree:
#
#   1. the name the repo's existing gate already reads, and
#   2. the *_FORBIDDEN_IDENTIFIERS secret actually present on the remote.
#
# Disagreement, absence, or ambiguity is a hard refusal. Refusing costs a
# minute; arming a gate against a secret that resolves to empty costs the
# property the gate exists to protect.
#
# Usage:
#   sync-identifier-gate.sh --check <repo-dir>    audit only, no writes
#   sync-identifier-gate.sh --apply <repo-dir>    render and overwrite
set -euo pipefail

TEMPLATE_DIR="${GATE_TEMPLATE_DIR:-$HOME/.config/agent-suite/gate-template}"
MODE=""; REPO_DIR=""; FORCE=0

die() { echo "REFUSED: $*" >&2; exit 2; }
note() { echo "  $*"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --check) MODE=check; shift ;;
    --apply) MODE=apply; shift ;;
    --force) FORCE=1; shift ;;
    -*) die "unknown flag $1" ;;
    *) REPO_DIR="$1"; shift ;;
  esac
done
[ -n "$MODE" ] || die "need --check or --apply"
[ -n "$REPO_DIR" ] || die "need a repo directory"
[ -d "$REPO_DIR/.git" ] || die "$REPO_DIR is not a git repository"
[ -d "$TEMPLATE_DIR" ] || die "template dir $TEMPLATE_DIR not found"

# -- the template itself must be a committed, pinned revision -----------------
# Checking only the DESTINATION gate is not enough: rendering from a template
# with uncommitted (unreviewed) edits copies them into every repo synced, which
# is the drift this script exists to prevent, at the source (AOS BR-50). So the
# template must be a clean git checkout, and its own gate must hash to a line
# marked "current canonical" in KNOWN_GATE_HASHES -- a revision is pinned there
# only once it has been reviewed.
git -C "$TEMPLATE_DIR" rev-parse --git-dir >/dev/null 2>&1 \
  || die "template dir $TEMPLATE_DIR is not a git repository; cannot prove what would be rendered"
[ -z "$(git -C "$TEMPLATE_DIR" status --porcelain --untracked-files=all)" ] \
  || die "template $TEMPLATE_DIR has uncommitted changes; review and commit them, then pin the gate hash in KNOWN_GATE_HASHES, before syncing"
TEMPLATE_REV="$(git -C "$TEMPLATE_DIR" rev-parse HEAD)"
TEMPLATE_GATE_HASH="$(sed -e 's/@@DENYLIST_VAR@@/PIN_FORBIDDEN_IDENTIFIERS/g' "$TEMPLATE_DIR/check_committed_identifiers.py" \
  | sed -E 's/[A-Z][A-Z0-9_]*_FORBIDDEN_IDENTIFIERS/XX/g' | sha256sum | cut -c1-16)"
grep -qE "^${TEMPLATE_GATE_HASH}[[:space:]].*current canonical" "$TEMPLATE_DIR/KNOWN_GATE_HASHES" \
  || die "template gate hash $TEMPLATE_GATE_HASH (rev ${TEMPLATE_REV:0:12}) is not pinned as \"current canonical\" in KNOWN_GATE_HASHES; an unpinned template is unreviewed"
echo "template: rev ${TEMPLATE_REV:0:12}, gate $TEMPLATE_GATE_HASH (pinned)"

cd "$REPO_DIR"
REPO_SLUG="$(git remote get-url origin 2>/dev/null | sed -E 's#.*github\.com[:/]##; s#\.git$##')" \
  || die "no origin remote"
[ -n "$REPO_SLUG" ] || die "could not read origin remote"
echo "repo: $REPO_SLUG"

# -- the hook's display name is NOT the repo name --------------------------
# Several repos call themselves by a project short name in operator-facing
# output: agent-capability-broker says "acb", agent-provenance says "cairn".
# Deriving this from the remote slug silently renames them. So it is read from
# the hook already in the repo, and only falls back to the slug when there is
# no hook to read -- the same resolve-don't-guess rule the denylist gets.
if [ -f githooks/pre-push ]; then
  REPO_NAME="$(sed -nE 's/^# ([A-Za-z0-9_.-]+) pre-push publication guard.*/\1/p' githooks/pre-push | head -1)"
fi
if [ -z "${REPO_NAME:-}" ]; then
  REPO_NAME="${REPO_SLUG##*/}"
  note "display name:      $REPO_NAME (from remote slug -- no existing hook to read)"
else
  note "display name:      $REPO_NAME (read from existing githooks/pre-push)"
fi

# -- source 1: the name the repo's existing gate reads ------------------------
GATE=scripts/check_committed_identifiers.py
[ -f "$GATE" ] || die "$REPO_SLUG has no $GATE -- this script upgrades an existing gate, it does not introduce one"
# Read from the environ.get(...) call, not any mention: the bare org name
# FORBIDDEN_IDENTIFIERS has no prefix, and comments may name other variables.
mapfile -t FROM_CODE < <(grep -oE 'environ\.get\(\s*["'"'"'][A-Z0-9_]*FORBIDDEN_IDENTIFIERS["'"'"']' "$GATE" \
  | grep -oE '[A-Z0-9_]*FORBIDDEN_IDENTIFIERS' | sort -u)
[ "${#FROM_CODE[@]}" -eq 1 ] \
  || die "expected exactly one denylist variable in $GATE, found ${#FROM_CODE[@]}: ${FROM_CODE[*]:-<none>}"
CODE_VAR="${FROM_CODE[0]}"
note "declared in code:  $CODE_VAR"

# -- source 2: the secret that actually exists on the remote ------------------
# Repo-level secrets, plus org-level secrets this repo can see (the org family
# uses one shared FORBIDDEN_IDENTIFIERS org secret, which `gh secret list -R`
# does not show).
mapfile -t FROM_REMOTE < <( { gh secret list -R "$REPO_SLUG" --json name --jq '.[].name' 2>/dev/null;
    gh api "repos/$REPO_SLUG/actions/organization-secrets" --jq '.secrets[].name' 2>/dev/null; } \
  | grep -E '^[A-Z0-9_]*FORBIDDEN_IDENTIFIERS$' | sort -u)
[ "${#FROM_REMOTE[@]}" -ge 1 ] \
  || die "no *FORBIDDEN_IDENTIFIERS secret visible to $REPO_SLUG (repo or org level)"
# -- the two must agree -------------------------------------------------------
# A user repo normally sees exactly one secret. An org repo sees every org-level
# secret (the shared FORBIDDEN_IDENTIFIERS plus per-repo prefixed ones), so the
# rule is membership: the name the code reads must be a secret that exists.
REMOTE_VAR=""
for s in "${FROM_REMOTE[@]}"; do [ "$s" = "$CODE_VAR" ] && REMOTE_VAR="$s"; done
[ -n "$REMOTE_VAR" ] \
  || die "name mismatch -- code reads $CODE_VAR but no secret of that name is visible
         (found: ${FROM_REMOTE[*]}). Arming the gate now would scan against an
         unset variable and pass everything. Reconcile the names first (create
         the secret, or move the repo into the org), then re-run."
note "secret on remote:  $REMOTE_VAR (of ${#FROM_REMOTE[@]} visible)"
DENYLIST_VAR="$CODE_VAR"

# -- publication declaration must say public, or the gate stays a no-op -------
if [ -f publication.toml ]; then
  VIS="$(grep -ioE 'visibility[[:space:]]*=[[:space:]]*"[^"]*"' publication.toml | head -1 | sed -E 's/^[^"]*"//; s/"$//' | tr '[:upper:]' '[:lower:]' | xargs)"
  note "visibility:        ${VIS:-<unparseable>}"
  [ "$VIS" = "public" ] || note "NOTE: visibility is '${VIS:-?}' -- gate installs but stays a no-op until public"
else
  note "visibility:        <no publication.toml> -- gate installs but stays a no-op"
fi

# -- refuse to overwrite a locally-modified gate ------------------------------
# The gate is copied, so a repo can legitimately harden its own copy. Blindly
# rendering over that drops the hardening silently -- exactly the failure this
# script exists to prevent, pointed the other way. A gate whose hash is not a
# known canonical version is treated as locally modified.
CURRENT_HASH="$(sed -E 's/[A-Z][A-Z0-9_]*_FORBIDDEN_IDENTIFIERS/XX/g' "$GATE" | sha256sum | cut -c1-16)"
if grep -qE "^${CURRENT_HASH}[[:space:]]" "$TEMPLATE_DIR/KNOWN_GATE_HASHES" 2>/dev/null; then
  note "existing gate:     $CURRENT_HASH (known canonical)"
  LOCALLY_MODIFIED=0
else
  note "existing gate:     $CURRENT_HASH (NOT a known canonical version)"
  LOCALLY_MODIFIED=1
fi

if [ "$MODE" = check ]; then
  echo "  would render with DENYLIST_VAR=$DENYLIST_VAR REPO_NAME=$REPO_NAME"
  while read -r src dst mode; do
    case "$src" in ''|\#*) continue ;; esac
    if [ -f "$dst" ] && diff -q <(sed -e "s/@@DENYLIST_VAR@@/$DENYLIST_VAR/g" -e "s/@@REPO_NAME@@/$REPO_NAME/g" "$TEMPLATE_DIR/$src") "$dst" >/dev/null 2>&1; then
      note "up-to-date  $dst"
    elif [ -f "$dst" ]; then
      note "WOULD UPDATE $dst"
    else
      note "WOULD CREATE $dst"
    fi
  done < "$TEMPLATE_DIR/MANIFEST"
  exit 0
fi

# -- apply --------------------------------------------------------------------
if [ "$LOCALLY_MODIFIED" -eq 1 ] && [ "$FORCE" -ne 1 ]; then
  die "this repo's gate is not a known canonical version, so it carries local
         edits. Rendering over it would drop them without a word. Diff it against
         the template, decide what to keep, then re-run with --force and port the
         local rules back by hand.
         (touchstone's deploy/k8s/secret-*.yaml rule is the worked example.)"
fi

while read -r src dst mode; do
  case "$src" in ''|\#*) continue ;; esac
  mkdir -p "$(dirname "$dst")"
  sed -e "s/@@DENYLIST_VAR@@/$DENYLIST_VAR/g" -e "s/@@REPO_NAME@@/$REPO_NAME/g" "$TEMPLATE_DIR/$src" > "$dst"
  chmod "$mode" "$dst"
  note "wrote $dst"
done < "$TEMPLATE_DIR/MANIFEST"

# A rendered template must never still carry a placeholder.
if grep -rn '@@[A-Z_]*@@' scripts/check_committed_identifiers.py scripts/check_publication_plumbing.py \
     tests/test_identifier_gate.py tests/test_identifier_gate_visibility.py githooks/pre-push 2>/dev/null; then
  die "unrendered placeholder survived -- refusing to leave this repo in that state"
fi
echo "  synced $REPO_SLUG at $DENYLIST_VAR"
