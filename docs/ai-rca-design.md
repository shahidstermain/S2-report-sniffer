# Analyze in Glean — Incident Packet Handoff

**Status:** Implemented  
**Date:** 2026-07-12  
**Supersedes:** Cursor Agent CLI RCA and the earlier Glean MCP RCA designs

## Overview

S2 Report Sniffer does **not** call Glean (or any AI cloud) on the user's behalf. One click builds a curated Markdown **incident packet** from the local report, downloads it, copies a suggested prompt, and (in the Electron desktop app) opens the Glean macOS app so the engineer can attach the file in Glean Chat.

Glean Desktop cannot ingest arbitrary local files automatically. The honest product is a **handoff**, not auto-ingest. No customer data leaves the machine until the user explicitly attaches the packet in Glean.

## Architecture

```
Issues toolbar "Analyze in Glean"
        ↓
GET /api/reports/{id}/export/glean
        ↓
build_glean_packet()   ← backend/investigation.py
        ↓
{ filename, markdown, prompt }
        ↓
┌─────────────────────┬────────────────────────────┐
│ Electron desktop    │ Browser / Vite             │
│ save Downloads/     │ Blob download              │
│ clipboard prompt    │ clipboard prompt           │
│ open Glean.app      │ toast: open Glean manually │
└─────────────────────┴────────────────────────────┘
        ↓
User attaches .md in Glean Chat
```

## Packet contents (whole report)

- Header: report name/id, health score, risk, version, node count, log timeframe
- Suggested Glean prompt (also returned separately for clipboard)
- Top findings (severity-ranked) with evidence, remediation, grounding basis/criterion, doc links
- Incident clusters with member checkers and per-cluster `log_context` patterns/excerpts
- Report-wide `detected_log_patterns` and aggregated suspected log lines
- `node_events` timeline (node_down / failover / state_change)
- Known doc links from recommendations/grounding
- Local-generation footer

Size-bounded (`MAX_PACKET_CHARS` ≈ 900 KB) so the attachment stays practical.

## API

### `GET /api/reports/{report_id}/export/glean`

No `S2RS_ENABLE_CLOUD_EXTENSIONS` gate. Returns JSON:

```json
{
  "filename": "s2rs-incident-packet-<short_id>.md",
  "markdown": "# S2 Report Sniffer — Incident Packet\n...",
  "prompt": "I attached an S2 Report Sniffer incident packet ..."
}
```

## Desktop IPC

- `desktop/preload.js` exposes `window.s2rsDesktop.gleanHandoff(payload)`
- `desktop/main.js` handles `s2rs:glean-handoff`: sanitize filename, write under Downloads, copy prompt, reveal in Finder, `open -a Glean` (fallback `https://app.glean.com/chat`)

## Frontend

- Button: Issues toolbar (`Recommendations.jsx`, `data-testid="analyze-in-glean"`)
- Helpers: `getGleanPacket` in `frontend/src/lib/api.ts`, `handoffGleanPacket` in `frontend/src/lib/gleanHandoff.js`

## Removed (Cursor path)

- `backend/cursor_agent.py`, `/api/ai/*`, InvestigationDrawer, AiSetup tab, investigation brief cache dirs

## Policy / local-first

- Packet generation is fully local
- Egress happens only when the user attaches the file inside Glean
- Hostinger (and similar) remain behind `S2RS_ENABLE_CLOUD_EXTENSIONS`; this handoff does not

## Tests

- `backend/test_investigation.py` — packet content
- `backend/test_server_endpoints.py::TestGleanExport`
- `frontend/src/lib/gleanHandoff.test.js`
- `frontend/src/components/Recommendations.test.jsx` — button → fetch → handoff
