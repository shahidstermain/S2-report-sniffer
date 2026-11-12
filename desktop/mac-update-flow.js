"use strict";

/**
 * macOS self-update flow around mac-self-updater.js.
 *
 * electron-updater can check GitHub Releases, but Squirrel.Mac refuses to
 * install an ad-hoc signed bundle. For those builds this module downloads the
 * ZIP itself, and a detached script (paths only ever arrive as arguments)
 * replaces the app after this process exits. Developer ID builds keep using
 * Squirrel.Mac; usesMacSelfUpdate() is how main.js chooses.
 */

const fs = require("fs");
const path = require("path");
const { spawnSync } = require("child_process");

const {
  isArm64Host,
  isInstallableLocation,
  resolveFeedUrl,
  selectAsset,
  selectZip,
  verifyAndParseManifest,
} = require("./mac-self-updater");

const DEFAULT_MANIFEST_URL =
  "https://github.com/shahidstermain/S2-report-sniffer/releases/latest/download/latest-mac.yml";
const RELEASE_PAGE_URL = "https://github.com/shahidstermain/S2-report-sniffer/releases/latest";

// Fixed text. Callers pass the pid, app path, staged app, and fallback as
// arguments, so a path can never change what the script does. S2RS_UPDATE_NO_OPEN
// skips Finder launches so tests can run the swap without opening windows.
const APPLY_UPDATE_SCRIPT = `#!/bin/bash
set -u
PID="$1"
APP="$2"
STAGED="$3"
FALLBACK="\${4:-}"

deadline=60
while /bin/kill -0 "$PID" 2>/dev/null; do
  if [ "$deadline" -le 0 ]; then
    echo "update: timed out waiting for pid $PID" >&2
    exit 1
  fi
  deadline=$((deadline - 1))
  sleep 1
done

open_target() {
  if [ "\${S2RS_UPDATE_NO_OPEN:-}" = "1" ]; then
    return 0
  fi
  if [ -n "$1" ]; then
    /usr/bin/open "$1" || true
  fi
}

fail() {
  echo "update: $1" >&2
  open_target "$FALLBACK"
  exit 1
}

BACKUP="\${APP}.previous"
/bin/rm -rf "$BACKUP" || fail "could not clear the previous backup"
/usr/bin/ditto "$APP" "$BACKUP" || fail "could not back up the installed app"
/bin/rm -rf "$APP" || fail "could not remove the installed app"
if ! /usr/bin/ditto "$STAGED" "$APP"; then
  /bin/rm -rf "$APP"
  /usr/bin/ditto "$BACKUP" "$APP" || true
  fail "could not copy the new app; restored the previous one"
fi
/usr/bin/xattr -cr "$APP" || true
if [ "\${S2RS_UPDATE_NO_OPEN:-}" != "1" ]; then
  /usr/bin/open -n "$APP" || fail "could not relaunch the updated app"
fi
echo "update: installed $APP"
exit 0
`;

const ADMIN_INSTALL_SCRIPT = `on run argv
  set cmd to quoted form of (item 1 of argv)
  repeat with i from 2 to (count of argv)
    set cmd to cmd & " " & quoted form of (item i of argv)
  end repeat
  do shell script cmd with administrator privileges
end run`;

function manifestUrl(env = process.env) {
  const override = String(env.S2RS_UPDATE_FEED_URL || "").trim();
  if (!override) return resolveFeedUrl(DEFAULT_MANIFEST_URL, "");
  const target = override.endsWith(".yml")
    ? override
    : `${override.replace(/\/+$/, "")}/latest-mac.yml`;
  return resolveFeedUrl(target, "");
}

function isNewerVersion(remote, current) {
  const parse = (value) =>
    String(value).split("-")[0].split(".").map((part) => Number(part) || 0);
  const next = parse(remote);
  const installed = parse(current);
  for (let index = 0; index < 3; index += 1) {
    if (next[index] !== installed[index]) return next[index] > installed[index];
  }
  return false;
}

function appBundleFromExec(execPath) {
  const marker = ".app/";
  const index = String(execPath).indexOf(marker);
  if (index === -1) return null;
  return execPath.slice(0, index + marker.length - 1);
}

function usesMacSelfUpdate({ platform, isPackaged, codesignOutput = "" }) {
  if (platform !== "darwin" || !isPackaged) return false;
  return !/TeamIdentifier=[A-Z0-9]{10}/.test(codesignOutput);
}

function readCodesign(appPath) {
  const result = spawnSync("/usr/bin/codesign", ["-dv", "--verbose=2", appPath], {
    encoding: "utf8",
  });
  return `${result.stdout || ""}${result.stderr || ""}`;
}

function detectArm64Mac() {
  const sysctl = spawnSync("/usr/sbin/sysctl", ["sysctl.proc_translated"], { encoding: "utf8" });
  const uname = spawnSync("/usr/bin/uname", ["-a"], { encoding: "utf8" });
  return isArm64Host({
    sysctlOutput: `${sysctl.stdout || ""}${sysctl.stderr || ""}`,
    unameOutput: `${uname.stdout || ""}${uname.stderr || ""}`,
    arch: process.arch,
  });
}

function needsAdmin(appPath, { uid = process.getuid(), stat = fs.statSync, access = fs.accessSync } = {}) {
  if (stat(appPath).uid !== uid) return true;
  try {
    access(path.dirname(appPath), fs.constants.W_OK);
    return false;
  } catch (error) {
    if (error && error.code === "EACCES") return true;
    throw error;
  }
}

function fallbackFor(manifestFiles, { isArm64Mac, manifest }) {
  const dmg = selectAsset(manifestFiles, { isArm64Mac, extension: ".dmg" });
  if (!dmg) return RELEASE_PAGE_URL;
  return resolveFeedUrl(manifest, dmg.url);
}

async function readBody(response) {
  if (typeof response.arrayBuffer === "function") return Buffer.from(await response.arrayBuffer());
  return Buffer.from(await response.text());
}

/**
 * Fetches and verifies the signed manifest. Returns one of:
 *   { status: "up-to-date", version }
 *   { status: "manual", version, fallbackUrl, message }
 *   { status: "available", version, zip, zipUrl, fallbackUrl }
 */
async function checkMacUpdate({
  currentVersion,
  appPath,
  publicKeyPem,
  isArm64Mac,
  env = process.env,
  fetchImpl = globalThis.fetch,
}) {
  const manifest = manifestUrl(env);
  const ymlResponse = await fetchImpl(manifest);
  if (!ymlResponse.ok) throw new Error(`Update feed failed (HTTP ${ymlResponse.status})`);
  const sigResponse = await fetchImpl(`${manifest}.sig`);
  if (!sigResponse.ok) throw new Error(`Update signature missing (HTTP ${sigResponse.status})`);

  const parsed = verifyAndParseManifest({
    ymlBuffer: await readBody(ymlResponse),
    sigText: typeof sigResponse.text === "function" ? await sigResponse.text() : String(sigResponse.body),
    publicKeyPem,
  });
  if (!isNewerVersion(parsed.version, currentVersion)) {
    return { status: "up-to-date", version: parsed.version };
  }

  const fallbackUrl = fallbackFor(parsed.files, { isArm64Mac, manifest });
  const location = isInstallableLocation(appPath);
  if (!location.ok) {
    return { status: "manual", version: parsed.version, fallbackUrl, message: location.reason };
  }

  const zip = selectZip(parsed.files, { isArm64Mac });
  if (!zip) throw new Error("No macOS update package is published for this Mac");
  return {
    status: "available",
    version: parsed.version,
    zip,
    zipUrl: resolveFeedUrl(manifest, zip.url),
    fallbackUrl,
  };
}

function writeApplyScript(directory) {
  fs.mkdirSync(directory, { recursive: true });
  const scriptPath = path.join(directory, "apply-update.sh");
  fs.writeFileSync(scriptPath, APPLY_UPDATE_SCRIPT, { mode: 0o700 });
  return scriptPath;
}

function applyCommand({ scriptPath, pid, appPath, stagedApp, fallback, useAdmin }) {
  const args = [String(pid), appPath, stagedApp, fallback || ""];
  if (!useAdmin) return { file: "/bin/bash", args: [scriptPath, ...args] };
  return { file: "/usr/bin/osascript", args: ["-e", ADMIN_INSTALL_SCRIPT, "--", scriptPath, ...args] };
}

function removePreviousBundle(appPath) {
  fs.rmSync(`${appPath}.previous`, { recursive: true, force: true });
}

function pruneUpdateCache(directory) {
  fs.rmSync(directory, { recursive: true, force: true });
}

module.exports = {
  APPLY_UPDATE_SCRIPT,
  DEFAULT_MANIFEST_URL,
  RELEASE_PAGE_URL,
  manifestUrl,
  isNewerVersion,
  appBundleFromExec,
  usesMacSelfUpdate,
  readCodesign,
  detectArm64Mac,
  needsAdmin,
  checkMacUpdate,
  writeApplyScript,
  applyCommand,
  removePreviousBundle,
  pruneUpdateCache,
};
