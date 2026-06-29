# sdb-report standalone extraction

Use this when you need the **diagnostic collector** (`sdb-report`) on local or air-gapped machines without installing the full SingleStore Toolbox (`sdb-deploy`, `sdb-admin`, `sdb-toolbox-config`, etc.).

## Important: client vs toolbox

| Package | Contains | Use for |
|---------|----------|---------|
| `singlestore-client-*.tar.gz` | `singlestore` SQL client only | Connecting to a database |
| `singlestoredb-toolbox-*.tar.gz` | `sdb-report`, `sdb-deploy`, `sdb-admin`, … | Cluster ops and diagnostics |

The file `singlestore-client-1.0.8-bc03126480.x86_64.tar.gz` is the **SQL client**. It does **not** include `sdb-report`.

`sdb-report` ships inside **`singlestoredb-toolbox`**. In current releases it is a single statically linked binary named `sdb-report` (some older internal docs call it `sdb-report.bin`).

## Quick start

```bash
cd tools/sdb-report-standalone

# Option A: you already have a toolbox tarball
./extract-sdb-report.sh /path/to/singlestoredb-toolbox-1.18.13-49526b32b4.x86_64.tar.gz

# Option B: download the latest toolbox release, then extract
./extract-sdb-report.sh --latest
```

Output:

```
dist/sdb-report-standalone/
  bin/sdb-report          # diagnostic binary (~60 MB, static Go build)
  bin/memsql-report       # symlink for legacy scripts
  sdb-report.sh           # PATH-friendly launcher
  README.txt              # version + usage hints
```

## Using on a local device

### Local host only (no SSH / no toolbox config)

Works on a machine that already runs SingleStore:

```bash
export PATH="$(pwd)/dist/sdb-report-standalone/bin:$PATH"
sdb-report collect-local -o /tmp/local-report.tar.gz
```

### Full cluster collection

Still needs toolbox configuration and SSH access from a deployment host that manages the cluster:

```bash
sdb-report collect --validate-env --include-infra -o /tmp/cluster-report.tar.gz
```

Typical config locations (from `sdb-report env`):

- `~/.config/singlestoredb-toolbox/toolbox.hcl`
- `~/.local/share/singlestoredb-toolbox/toolbox-state.hcl`

Copy the standalone `bin/sdb-report` onto that host (or add it to `PATH`) instead of installing the entire toolbox package.

## Analyze the bundle in S2 Report Sniffer

Upload the generated `.tar.gz` / `.zip` archive through the S2 Report Sniffer UI or API (`POST /api/reports/upload`).

## Download toolbox manually (air-gapped)

```bash
curl -sf https://release.memsql.com/production/index/memsqltoolbox/latest.json
# Use packages.memsql-toolbox-tar.Path, then:
wget "https://release.memsql.com/<path-from-json>"
```

Transfer the tarball to the target machine and run `extract-sdb-report.sh` there.

## Verify

```bash
dist/sdb-report-standalone/bin/sdb-report version
dist/sdb-report-standalone/bin/sdb-report collect-local --help
```
