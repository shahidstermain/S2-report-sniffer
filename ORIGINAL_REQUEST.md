# Original User Request

## Initial Request — 2026-07-12T03:16:53+05:30

Implement all three roadmap improvements: frontend TypeScript migration, advanced SingleStore backend diagnostic checks, and desktop release/updater hardening.

Working directory: /Users/shahidster-macmini/S2-report-sniffer
Integrity mode: development

## Requirements

### R1. Frontend Refinement (100% TypeScript Conversion)
Convert all remaining React components and pages in `frontend/src/` from `.jsx` to `.tsx`. Resolve all TypeScript compiler issues and ensure that `yarn build` (or `npm run build`) runs successfully and all vitest unit tests pass.

### R2. Advanced Backend Diagnostics
Add the following SingleStore performance and configuration checkers to `backend/parsers.py` and `backend/superchecker.py`:
1. **Disk Mount Configuration**: Audit mounts (`mount_stdout` or `/etc/fstab`) for S2 data/redo directories. Warn if partitions lack `noatime` or if SSDs are missing `nodiscard` where recommended.
2. **CPU Scaling Governor**: Check governor configs. Alert as warning if any node CPU governor is set to `powersave` or `ondemand` instead of `performance`.
3. **Partition-to-Core Ratio**: Alert as warning if database partition counts exceed 8x the host's CPU core count.
4. **TCP & Keepalive Tuning**: Check TCP buffer and keepalive values in sysctl configurations (`tcp_keepalive_time` etc.), warning if they deviate from recommended values.
Ensure these are verified via pytest.

### R3. Desktop Hardening & Auto-Update
1. **Code-Signing Setup**: Add support/scripts in the packaging process (`desktop/` and build scripts) for macOS Developer ID signing (`codesign` + `notarytool`) and Windows Authenticode signing.
2. **Auto-Updater Integration**: Integrate `electron-updater` in `desktop/main.js` to automatically verify update checks on startup from GitHub releases, log update check states, and handle silent updates.

## Acceptance Criteria

### Frontend TS & Build
- [ ] No remaining `.jsx` files in `frontend/src/components/` or `frontend/src/pages/`.
- [ ] Frontend compiles and builds cleanly: `npm run build` completes successfully.
- [ ] All frontend unit tests (`npm test`) pass.

### Backend Diagnostic Checks
- [ ] Advanced checks (Disk Mounts, CPU Governor, Partition/Core Ratio, TCP Keepalives) are active in `superchecker.py` and `parsers.py`.
- [ ] Backend test suite passes fully (`python -m pytest`) with unit tests covering each new checker.

### Desktop Hardening
- [ ] `desktop/main.js` correctly loads and initializes `electron-updater` checking on startup.
- [ ] Code signing script configurations exist and package scripts are updated to support macOS/Windows certificates.
