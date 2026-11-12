"use strict";

const { test } = require("node:test");
const assert = require("node:assert/strict");
const crypto = require("crypto");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { spawnSync } = require("child_process");

const flow = require("../mac-update-flow");
const { signManifest } = require("../update-signature");

const YML = [
  "version: 1.2.16",
  "files:",
  "  - url: S2-1.2.16-arm64-mac.zip",
  "    sha512: a",
  "    size: 10",
  "  - url: S2-1.2.16-arm64.dmg",
  "    sha512: b",
  "    size: 12",
  "  - url: S2-1.2.16-x64-mac.zip",
  "    sha512: c",
  "    size: 11",
  "path: S2-1.2.16-arm64-mac.zip",
  "sha512: a",
  "",
].join("\n");

function keyPair() {
  return crypto.generateKeyPairSync("ed25519", {
    publicKeyEncoding: { type: "spki", format: "pem" },
    privateKeyEncoding: { type: "pkcs8", format: "pem" },
  });
}

function signedFeed(body = YML) {
  const pair = keyPair();
  const signature = signManifest(body, pair.privateKey);
  const fetchImpl = async (url) => {
    if (String(url).endsWith(".sig")) return { ok: true, text: async () => signature };
    return { ok: true, arrayBuffer: async () => Buffer.from(body) };
  };
  return { publicKeyPem: pair.publicKey, fetchImpl };
}

test("manifest URL stays on the GitHub feed unless an override is set", () => {
  assert.equal(flow.manifestUrl({}), flow.DEFAULT_MANIFEST_URL);
  assert.equal(
    flow.manifestUrl({ S2RS_UPDATE_FEED_URL: "http://127.0.0.1:9/feed/" }),
    "http://127.0.0.1:9/feed/latest-mac.yml"
  );
  assert.throws(() => flow.manifestUrl({ S2RS_UPDATE_FEED_URL: "http://example.com/feed/" }), /non-HTTPS/);
});

test("version comparison ignores a prerelease suffix and refuses downgrades", () => {
  assert.equal(flow.isNewerVersion("1.2.16", "1.2.15"), true);
  assert.equal(flow.isNewerVersion("1.3.0", "1.2.16"), true);
  assert.equal(flow.isNewerVersion("1.2.15", "1.2.16"), false);
  assert.equal(flow.isNewerVersion("1.2.16", "1.2.16"), false);
  assert.equal(flow.isNewerVersion("1.2.16-beta", "1.2.15"), true);
});

test("the running bundle path is the .app that contains the executable", () => {
  assert.equal(
    flow.appBundleFromExec("/Applications/S2 Report Sniffer.app/Contents/MacOS/S2 Report Sniffer"),
    "/Applications/S2 Report Sniffer.app"
  );
  assert.equal(flow.appBundleFromExec("/usr/local/bin/node"), null);
});

test("self-update is only for packaged macOS builds without a Developer ID team", () => {
  const adhoc = "TeamIdentifier=not set";
  const signed = "TeamIdentifier=ABCDE12345";
  assert.equal(flow.usesMacSelfUpdate({ platform: "darwin", isPackaged: true, codesignOutput: adhoc }), true);
  assert.equal(flow.usesMacSelfUpdate({ platform: "darwin", isPackaged: true, codesignOutput: signed }), false);
  assert.equal(flow.usesMacSelfUpdate({ platform: "darwin", isPackaged: false, codesignOutput: adhoc }), false);
  assert.equal(flow.usesMacSelfUpdate({ platform: "win32", isPackaged: true, codesignOutput: adhoc }), false);
});

test("an admin prompt is required when the app is owned by another user", () => {
  const stat = () => ({ uid: 0 });
  assert.equal(flow.needsAdmin("/Applications/S2 Report Sniffer.app", { uid: 501, stat }), true);
  const own = () => ({ uid: 501 });
  assert.equal(
    flow.needsAdmin("/Users/me/Applications/S2 Report Sniffer.app", { uid: 501, stat: own, access: () => {} }),
    false
  );
  assert.equal(
    flow.needsAdmin("/Applications/S2 Report Sniffer.app", {
      uid: 501,
      stat: own,
      access: () => { const error = new Error("denied"); error.code = "EACCES"; throw error; },
    }),
    true
  );
});

test("check reports an available arm64 zip and the matching dmg as the fallback", async () => {
  const feed = signedFeed();
  const result = await flow.checkMacUpdate({
    currentVersion: "1.2.15",
    appPath: "/Applications/S2 Report Sniffer.app",
    isArm64Mac: true,
    ...feed,
  });
  assert.equal(result.status, "available");
  assert.equal(result.version, "1.2.16");
  assert.equal(result.zip.url, "S2-1.2.16-arm64-mac.zip");
  assert.equal(
    result.zipUrl,
    "https://github.com/shahidstermain/S2-report-sniffer/releases/latest/download/S2-1.2.16-arm64-mac.zip"
  );
  assert.equal(
    result.fallbackUrl,
    "https://github.com/shahidstermain/S2-report-sniffer/releases/latest/download/S2-1.2.16-arm64.dmg"
  );
});

test("check reports up to date, and a DMG install as a manual update", async () => {
  const feed = signedFeed();
  const current = await flow.checkMacUpdate({
    currentVersion: "1.2.16",
    appPath: "/Applications/S2 Report Sniffer.app",
    isArm64Mac: true,
    ...feed,
  });
  assert.equal(current.status, "up-to-date");

  const fromDmg = await flow.checkMacUpdate({
    currentVersion: "1.2.15",
    appPath: "/Volumes/S2/S2 Report Sniffer.app",
    isArm64Mac: false,
    ...feed,
  });
  assert.equal(fromDmg.status, "manual");
  assert.match(fromDmg.message, /Applications/);
  // The fixture publishes no Intel DMG, so the fallback is the release page.
  assert.equal(fromDmg.fallbackUrl, flow.RELEASE_PAGE_URL);
});

test("check rejects a manifest whose signature does not match the trusted key", async () => {
  const feed = signedFeed(YML.replace("version: 1.2.16", "version: 9.9.9"));
  const trusted = keyPair();
  await assert.rejects(
    flow.checkMacUpdate({
      currentVersion: "1.2.15",
      appPath: "/Applications/S2 Report Sniffer.app",
      isArm64Mac: true,
      publicKeyPem: trusted.publicKey,
      fetchImpl: feed.fetchImpl,
    }),
    /signature is invalid/
  );
});

test("the apply command passes paths only as arguments", () => {
  const plain = flow.applyCommand({
    scriptPath: "/tmp/apply-update.sh",
    pid: 42,
    appPath: "/Applications/S2 Report Sniffer.app",
    stagedApp: "/tmp/staged/S2 Report Sniffer.app",
    fallback: "https://example.test/app.dmg",
    useAdmin: false,
  });
  assert.deepEqual(plain, {
    file: "/bin/bash",
    args: [
      "/tmp/apply-update.sh",
      "42",
      "/Applications/S2 Report Sniffer.app",
      "/tmp/staged/S2 Report Sniffer.app",
      "https://example.test/app.dmg",
    ],
  });
  const admin = flow.applyCommand({ ...plain, scriptPath: "/tmp/apply-update.sh", pid: 42, appPath: "/Applications/App.app", stagedApp: "/tmp/staged/App.app", fallback: "", useAdmin: true });
  assert.equal(admin.file, "/usr/bin/osascript");
  assert.equal(admin.args[0], "-e");
  assert.match(admin.args[1], /with administrator privileges/);
  assert.equal(admin.args[2], "--");
  assert.equal(flow.APPLY_UPDATE_SCRIPT.includes("/Applications"), false);
});

test("the apply script swaps the bundle and restores it when the new copy fails", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "s2rs-apply-"));
  const app = path.join(root, "S2 Report Sniffer.app");
  const staged = path.join(root, "staged", "S2 Report Sniffer.app");
  fs.mkdirSync(path.join(app, "Contents"), { recursive: true });
  fs.writeFileSync(path.join(app, "Contents", "marker"), "old");
  fs.mkdirSync(path.join(staged, "Contents"), { recursive: true });
  fs.writeFileSync(path.join(staged, "Contents", "marker"), "new");

  const script = flow.writeApplyScript(root);
  const run = (stagedPath) => spawnSync("/bin/bash", [script, "999999", app, stagedPath, path.join(root, "missing-fallback")], {
    encoding: "utf8",
    env: { ...process.env, S2RS_UPDATE_NO_OPEN: "1" },
  });

  const ok = run(staged);
  assert.equal(ok.status, 0, ok.stderr);
  assert.equal(fs.readFileSync(path.join(app, "Contents", "marker"), "utf8"), "new");
  assert.equal(fs.readFileSync(path.join(`${app}.previous`, "Contents", "marker"), "utf8"), "old");

  fs.writeFileSync(path.join(app, "Contents", "marker"), "current");
  const broken = run(path.join(root, "does-not-exist.app"));
  assert.notEqual(broken.status, 0);
  assert.equal(fs.readFileSync(path.join(app, "Contents", "marker"), "utf8"), "current");
});
