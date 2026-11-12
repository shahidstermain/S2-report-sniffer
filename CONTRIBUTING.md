# Contributing to S2 Report Sniffer

Thank you for improving the local-first SingleStore Cluster Report analyzer.

## Development workflow

1. Create a branch from `main`: `feat/...`, `fix/...`, `perf/...`, `security/...`, `test/...`, or `docs/...`.
2. Enable hooks with `git config core.hooksPath .githooks`.
3. Keep each commit to one logical change and use Conventional Commits, for example `fix(parser): reject zip symlink entries`.
4. Run the focused tests while developing and the full relevant gates before opening a pull request.

Never commit customer Cluster Reports, customer tracelogs, secrets, generated `.build/` content, or local `S2RS_DATA_DIR` data.

## Required gates

`scripts/ci-local.sh` is the merge gate. It runs the same commands as `.github/workflows/ci.yml` and `mcp-security.yml`, plus `git diff --check`. Pass `--backend`, `--frontend`, `--security`, `--mcp`, or `--whitespace` to run one slice. The hosted workflows stay in the repo and run when GitHub Actions can start jobs.

```bash
scripts/ci-local.sh
```

## Pull request checklist

- [ ] User-facing terminology follows `docs/TERMINOLOGY.md`.
- [ ] Stable checker IDs, routes, serialized keys, and database columns remain compatible.
- [ ] New findings include grounding in `backend/grounding.py`.
- [ ] Archive and parser changes preserve configurable bounded memory and disk usage.
- [ ] Customer data remains local by default; optional egress is explicit and disabled by default.
- [ ] Report payload changes are synchronized across validators, monitoring, storage, API models, and frontend types.
- [ ] Storage columns update migration, write allowlist, and read allowlist.
- [ ] Tests cover success, partial/corrupt input, and failure/recovery behavior.
- [ ] UI changes include accessible keyboard behavior and screenshots when visually material.
- [ ] Packaging changes are verified against `backend/test_packaging_spec.py` and `backend/test_build_scripts.py`.
- [ ] Rollback and saved-report compatibility have been considered.
