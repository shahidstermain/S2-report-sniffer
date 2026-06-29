#!/usr/bin/env bash
# Extract the sdb-report diagnostic binary from a SingleStore Toolbox package.
#
# sdb-report is shipped inside singlestoredb-toolbox (not singlestore-client).
# Modern toolbox releases ship it as a statically linked Go binary named "sdb-report".
# Older docs sometimes refer to it as sdb-report.bin; the tarball layout uses sdb-report.
#
# Usage:
#   ./extract-sdb-report.sh /path/to/singlestoredb-toolbox-*.tar.gz
#   ./extract-sdb-report.sh --latest
#   ./extract-sdb-report.sh --rpm /path/to/singlestoredb-toolbox-*.rpm
#
# Output lands in ./dist/sdb-report-standalone/ by default (override with -o).

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
DEFAULT_OUT="${SCRIPT_DIR}/dist/sdb-report-standalone"
RELEASE_INDEX="https://release.memsql.com/production/index/memsqltoolbox/latest.json"
RELEASE_BASE="https://release.memsql.com"

usage() {
  cat <<'EOF'
Extract sdb-report from SingleStore Toolbox for local / air-gapped use.

Usage:
  extract-sdb-report.sh [OPTIONS] [PACKAGE]

Options:
  --latest              Download the latest singlestoredb-toolbox tarball, then extract
  --rpm PATH            Extract from an RPM package instead of a tarball
  --deb PATH            Extract from a Debian package instead of a tarball
  -o, --output DIR      Output directory (default: tools/sdb-report-standalone/dist/sdb-report-standalone)
  -h, --help            Show this help

PACKAGE:
  Path to singlestoredb-toolbox-*.x86_64.tar.gz

Examples:
  ./extract-sdb-report.sh singlestoredb-toolbox-1.18.13-49526b32b4.x86_64.tar.gz
  ./extract-sdb-report.sh --latest
  ./extract-sdb-report.sh --rpm singlestoredb-toolbox-1.18.13-49526b32b4.x86_64.rpm
  ./extract-sdb-report.sh --deb singlestoredb-toolbox_1.18.13_49526b32b4_amd64.deb

Notes:
  - singlestore-client tarballs do NOT contain sdb-report.
  - Cluster-wide collection (sdb-report collect) still needs toolbox config/state on a
    deployment host; local-only collection (sdb-report collect-local) works with just
    this binary on a machine that already runs SingleStore.
EOF
}

log() {
  printf '[extract-sdb-report] %s\n' "$*" >&2
}

die() {
  printf '[extract-sdb-report] ERROR: %s\n' "$*" >&2
  exit 1
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"
}

fetch_latest_tarball() {
  need_cmd curl
  need_cmd python3
  local json path dest
  json=$(curl -sfL "$RELEASE_INDEX") || die "Failed to fetch toolbox release index"
  path=$(printf '%s' "$json" | python3 -c '
import json, sys
data = json.load(sys.stdin)
print(data["packages"]["memsql-toolbox-tar"]["Path"])
')
  dest=$(mktemp "${TMPDIR:-/tmp}/singlestoredb-toolbox.XXXXXX")
  CLEANUP_PATHS+=("$dest")
  log "Downloading ${RELEASE_BASE}/${path}"
  curl -sfL -o "$dest" "${RELEASE_BASE}/${path}"
  printf '%s' "$dest"
}

find_sdb_report_binary() {
  local search_root="$1"
  local candidate
  candidate=$(find "$search_root" -type f -name sdb-report -perm -111 2>/dev/null | head -n 1 || true)
  [[ -n "$candidate" ]] || die "Could not find sdb-report binary under ${search_root}"
  printf '%s' "$candidate"
}

find_bash_completion() {
  local search_root="$1"
  local candidate
  for candidate in \
    "$search_root"/sdb-autocomplete/bash-completion-sdb-tools \
    "$search_root"/*/sdb-autocomplete/bash-completion-sdb-tools \
    "$search_root"/etc/bash_completion.d/bash-completion-sdb-tools \
    "$search_root"/*/etc/bash_completion.d/bash-completion-sdb-tools; do
    if [[ -f "$candidate" ]]; then
      printf '%s' "$candidate"
      return 0
    fi
  done
  return 1
}

write_launcher() {
  local out_dir="$1"
  cat >"${out_dir}/sdb-report.sh" <<'EOF'
#!/usr/bin/env bash
# Thin launcher so this directory can be added to PATH without installing the full toolbox.
set -euo pipefail
DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
exec "${DIR}/bin/sdb-report" "$@"
EOF
  chmod +x "${out_dir}/sdb-report.sh"
}

write_env_hint() {
  local out_dir="$1"
  local version_line
  version_line=$("${out_dir}/bin/sdb-report" version 2>/dev/null | tr '\n' ' ' || true)
  cat >"${out_dir}/README.txt" <<EOF
SingleStore sdb-report standalone bundle
${version_line}

Add to PATH:
  export PATH="${out_dir}/bin:\$PATH"

Or use the launcher:
  ${out_dir}/sdb-report.sh collect-local -o /tmp/local-report.tar.gz

Cluster collection still requires toolbox config on a deployment host:
  sdb-report collect -o /tmp/cluster-report.tar.gz

Upload the resulting archive into S2 Report Sniffer for analysis.
EOF
}

install_standalone() {
  local sdb_report_bin="$1"
  local package_root="$2"
  local out_dir="$3"
  local completion_file=""

  rm -rf "$out_dir"
  mkdir -p "${out_dir}/bin"

  install -m 0755 "$sdb_report_bin" "${out_dir}/bin/sdb-report"
  ln -sf sdb-report "${out_dir}/bin/memsql-report"

  if completion_file=$(find_bash_completion "$package_root"); then
    mkdir -p "${out_dir}/share/bash-completion/completions"
    install -m 0644 "$completion_file" "${out_dir}/share/bash-completion/completions/sdb-report"
  fi

  write_launcher "$out_dir"
  write_env_hint "$out_dir"

  log "Installed standalone bundle to ${out_dir}"
  log "Version: $("${out_dir}/bin/sdb-report" version 2>/dev/null | tr '\n' ' ')"
  log "Try: ${out_dir}/bin/sdb-report collect-local --help"
}

main() {
  local output_dir="$DEFAULT_OUT"
  local mode="tarball"
  local package_path=""
  local downloaded=""

  while [[ $# -gt 0 ]]; do
    case "$1" in
      -h|--help)
        usage
        exit 0
        ;;
      --latest)
        downloaded=$(fetch_latest_tarball)
        package_path="$downloaded"
        shift
        ;;
      --rpm)
        mode="rpm"
        package_path="${2:-}"
        [[ -n "$package_path" ]] || die "--rpm requires a path"
        shift 2
        ;;
      --deb)
        mode="deb"
        package_path="${2:-}"
        [[ -n "$package_path" ]] || die "--deb requires a path"
        shift 2
        ;;
      -o|--output)
        output_dir="${2:-}"
        [[ -n "$output_dir" ]] || die "--output requires a directory"
        shift 2
        ;;
      --)
        shift
        package_path="${1:-}"
        break
        ;;
      -*)
        die "Unknown option: $1"
        ;;
      *)
        package_path="$1"
        shift
        ;;
    esac
  done

  if [[ -z "$package_path" ]]; then
    usage >&2
    die "Provide a toolbox package path or use --latest"
  fi

  [[ -f "$package_path" ]] || die "Package not found: ${package_path}"

  local sdb_report_bin=""
  local package_root=""
  case "$mode" in
    tarball)
      package_root=$(mktemp -d "${TMPDIR:-/tmp}/sdb-report-root.XXXXXX")
      log "Unpacking tarball ${package_path}"
      tar -xzf "$package_path" -C "$package_root"
      sdb_report_bin=$(find_sdb_report_binary "$package_root")
      ;;
    rpm)
      package_root=$(mktemp -d "${TMPDIR:-/tmp}/sdb-report-root.XXXXXX")
      need_cmd rpm2cpio
      need_cmd cpio
      log "Unpacking RPM ${package_path}"
      (cd "$package_root" && rpm2cpio "$package_path" | cpio -idm >/dev/null 2>&1)
      sdb_report_bin=$(find_sdb_report_binary "$package_root")
      ;;
    deb)
      package_root=$(mktemp -d "${TMPDIR:-/tmp}/sdb-report-root.XXXXXX")
      need_cmd dpkg-deb
      log "Unpacking DEB ${package_path}"
      dpkg-deb -x "$package_path" "$package_root"
      sdb_report_bin=$(find_sdb_report_binary "$package_root")
      ;;
  esac

  install_standalone "$sdb_report_bin" "$package_root" "$output_dir"
  rm -rf "$package_root"

  if [[ -n "$downloaded" ]]; then
    rm -f "$downloaded"
  fi
}

main "$@"
