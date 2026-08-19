#!/usr/bin/env bash
set -u

set -o pipefail

MARKER="# streamcontroller-github-deployment-watcher"
DEFAULT_BRANCHES="main master github-pages"

usage() {
    cat >&2 <<'EOF'
Usage:
  install-deployment-pre-push-hook.sh install --repo PATH --owner OWNER --github-repo REPO \
    --environment ENV [--cli PATH] [--branches "main master github-pages"]
  install-deployment-pre-push-hook.sh uninstall --repo PATH [--yes]
EOF
}

quote() {
    printf "%q" "$1"
}

install_hook() {
    local repo="" owner="" github_repo="" environment=""
    local cli="/home/gb/Documents/GitHub/streamcontroller-fork/main.py" branches="$DEFAULT_BRANCHES"
    while (($#)); do
        case "$1" in
            --repo) repo=$2; shift 2 ;;
            --owner) owner=$2; shift 2 ;;
            --github-repo) github_repo=$2; shift 2 ;;
            --environment) environment=$2; shift 2 ;;
            --cli) cli=$2; shift 2 ;;
            --branches) branches=$2; shift 2 ;;
            *) echo "Unknown option: $1" >&2; usage; return 2 ;;
        esac
    done
    if [[ -z "$repo" || -z "$owner" || -z "$github_repo" || -z "$environment" ]]; then
        echo "Missing required install option." >&2
        usage
        return 2
    fi

    repo=$(cd "$repo" 2>/dev/null && pwd) || {
        echo "Repository does not exist: $repo" >&2
        return 2
    }
    local git_dir
    git_dir=$(git -C "$repo" rev-parse --git-dir 2>/dev/null) || {
        echo "Not a Git repository: $repo" >&2
        return 2
    }
    [[ "$git_dir" = /* ]] || git_dir="$repo/$git_dir"
    local hook="$git_dir/hooks/pre-push"
    mkdir -p "$git_dir/hooks"

    if [[ -e "$hook" ]] && ! grep -qF "$MARKER" "$hook"; then
        echo "Refusing to overwrite existing hook: $hook" >&2
        echo "Inspect it and chain it manually, or uninstall the existing hook first." >&2
        return 1
    fi

    cat > "$hook" <<EOF
#!/usr/bin/env bash
# $MARKER
# owner=$(quote "$owner") repo=$(quote "$github_repo") environment=$(quote "$environment")
set -u
while read -r local_ref local_sha remote_ref remote_sha; do
    case "\$remote_ref" in
        refs/heads/*)
            branch="\${remote_ref#refs/heads/}"
        nohup python3 "$(quote "$cli")" --trigger-deployment "$(quote "$owner")" "$(quote "$github_repo")" "$(quote "$environment")" >/dev/null 2>&1 </dev/null &
            ;;
    esac
done
exit 0
EOF
    chmod 700 "$hook"
    echo "Installed local deployment watcher pre-push hook: $hook"
}

uninstall_hook() {
    local repo="" confirm=0
    while (($#)); do
        case "$1" in
            --repo) repo=$2; shift 2 ;;
            --yes) confirm=1; shift ;;
            *) echo "Unknown option: $1" >&2; usage; return 2 ;;
        esac
    done
    [[ -n "$repo" ]] || { echo "--repo is required." >&2; return 2; }
    repo=$(cd "$repo" 2>/dev/null && pwd) || { echo "Repository does not exist: $repo" >&2; return 2; }
    local git_dir hook
    git_dir=$(git -C "$repo" rev-parse --git-dir 2>/dev/null) || { echo "Not a Git repository: $repo" >&2; return 2; }
    [[ "$git_dir" = /* ]] || git_dir="$repo/$git_dir"
    hook="$git_dir/hooks/pre-push"
    [[ -e "$hook" ]] || { echo "No pre-push hook installed."; return 0; }
    if ! grep -qF "$MARKER" "$hook"; then
        echo "Existing hook is not owned by StreamController; refusing to remove it: $hook" >&2
        return 1
    fi
    answer=n
    if [[ "$confirm" -eq 1 ]]; then
        answer=y
    else
        echo "Remove the StreamController hook at $hook? [y/N]"
        read -r answer
    fi
    [[ "$answer" = y || "$answer" = Y ]] || { echo "Cancelled."; return 0; }
    rm "$hook"
    echo "Removed $hook"
}

case "${1:-}" in
    install) shift; install_hook "$@" ;;
    uninstall) shift; uninstall_hook "$@" ;;
    *) usage; exit 2 ;;
esac
