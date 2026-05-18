#!/usr/bin/env bash
set -eo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

MIN_NODE="20.0.0"
MIN_NPM="10.0.0"
MIN_PYTHON="3.11.0"
MIN_PIP="21.0.0"

check_command() {
    command -v "$1" >/dev/null 2>&1
}

get_version() {
    local cmd="$1"
    if [[ "$cmd" == "node" ]]; then
        "$cmd" --version 2>/dev/null | sed 's/v//' | tr -d '\n'
    elif [[ "$cmd" == "npm" ]]; then
        "$cmd" --version 2>/dev/null | tr -d '\n'
    elif [[ "$cmd" == "python" || "$cmd" == "python3" ]]; then
        "$cmd" --version 2>/dev/null | sed 's/Python //' | tr -d '\n'
    elif [[ "$cmd" == "pip" || "$cmd" == "pip3" ]]; then
        "$cmd" --version 2>/dev/null | sed 's/pip //' | sed 's/(.*//' | tr -d '\n'
    fi
}

version_lte() {
    printf '%s\n%s\n' "$1" "$2" | sort -V -C
}

check_dependency() {
    local dep="$1"
    local cmd="$2"

    local min_ver
    case "$dep" in
        Node.js)  min_ver="$MIN_NODE" ;;
        npm)      min_ver="$MIN_NPM" ;;
        Python)   min_ver="$MIN_PYTHON" ;;
        pip)      min_ver="$MIN_PIP" ;;
        *)        min_ver="0.0.0" ;;
    esac

    if ! check_command "$cmd"; then
        echo -e "${RED}x${RESET} ${BOLD}$dep${RESET} — not found"
        return 1
    fi

    local installed
    installed=$(get_version "$cmd")

    if [[ -z "$installed" ]]; then
        echo -e "${YELLOW}?${RESET} ${BOLD}$dep${RESET} — could not determine version (command found)"
        return 0
    fi

    if version_lte "$min_ver" "$installed"; then
        echo -e "${GREEN}✓${RESET} ${BOLD}$dep${RESET} ${CYAN}$installed${RESET} (>= $min_ver required)"
        return 0
    else
        echo -e "${RED}x${RESET} ${BOLD}$dep${RESET} ${CYAN}$installed${RESET} — $min_ver or higher required"
        return 1
    fi
}

run_check() {
    echo ""
    echo -e "${BOLD}S2 Report Sniffer — Dependency Check${RESET}"
    echo "=============================================="
    echo ""

    local all_ok=true

    check_dependency "Node.js" "node" && echo "" || { all_ok=false; echo ""; }
    check_dependency "npm" "npm" && echo "" || { all_ok=false; echo ""; }
    check_dependency "Python" "python3" && echo "" || { all_ok=false; echo ""; }

    if check_command "python3"; then
        if check_command "pip3" || check_command "pip"; then
            local pip_cmd
            pip_cmd=$(check_command "pip3" && echo "pip3" || echo "pip")
            check_dependency "pip" "$pip_cmd" && echo "" || { all_ok=false; echo ""; }
        else
            echo -e "${RED}x${RESET} ${BOLD}pip${RESET} — not found"
            all_ok=false
            echo ""
        fi
    else
        all_ok=false
    fi

    if [[ "$all_ok" == "true" ]]; then
        echo -e "${GREEN}${BOLD}All dependencies satisfied. Ready to build.${RESET}"
        echo ""
        return 0
    fi

    echo ""
    echo -e "${YELLOW}${BOLD}Missing or outdated dependencies detected.${RESET}"
    echo ""
    echo "To install the required dependencies on macOS, install Homebrew first"
    echo "and then run the commands below."
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo -e "${BOLD}Step 1: Install Homebrew (if not already installed)${RESET}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "    /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo -e "${BOLD}Step 2: Install dependencies via Homebrew${RESET}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "    brew install node python@3.11"
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo -e "${BOLD}Step 3: Verify installation${RESET}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "    bash scripts/pre_install_check.sh"
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo -e "${BOLD}Step 4: Build the app${RESET}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "    ./scripts/build-macos-arm64-dmg.sh"
    echo ""
    echo "For more details, see PACKAGING.md"
    echo ""

    if [[ "${INTERACTIVE_MODE:-true}" == "true" ]]; then
        read -rp "Open the Homebrew installation page in your browser? [Y/n] " answer
        case "${answer,,}" in
            ""|y|yes) open "https://brew.sh" ;;
            *) echo "Please install Homebrew manually and re-run this script." ;;
        esac
    fi

    return 1
}

run_check