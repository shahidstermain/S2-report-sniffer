"use strict";

const { test } = require("node:test");
const assert = require("node:assert/strict");
const crypto = require("crypto");
const fs = require("fs");
const http = require("http");
const os = require("os");
const path = require("path");

const updater = require("../mac-self-updater.js");
const { signManifest } = require("../update-signature.js");

const SAMPLE_YML = [
  "version: 1.2.16",
  "files:",
  "  - url: S2.Report.Sniffer-1.2.16-x64-mac.zip",
  "    sha512: X64SHA==",
  "    size: 200",
  "  - url: S2.Report.Sniffer-1.2.16-arm64-mac.zip",
  "    sha512: ARMSHA==",
  "    size: 190",
  "  - url: S2.Report.Sniffer-1.2.16-arm64.dmg",
  "    sha512: DMGSHA==",
  "    size: 300",
  "path: S2.Report.Sniffer-1.2.16-arm64-mac.zip",
  "sha512: ARMSHA==",
  "releaseDate: '2026-11-12T12:00:00.000Z'",
  "",
].join("\n");

function tmpDir(prefix) {
  return fs.mkdtempSync(path.join(os.tmpdir(), prefix));
}

function sha512Base64(buffer) {
  return crypto.createHash("sha512").update(buffer).digest("base64");
}

function ed25519Pair() {
  return crypto.generateKeyPairSync("ed25519", {
    publicKeyEncoding: { type: "spki", format: "pem" },
    privateKeyEncoding: { type: "pkcs8", format: "pem" },
  });
}

test("parses the merged latest-mac.yml written by the release merge script", () => {
  const parsed = updater.parseLatestMacYml(SAMPLE_YML);
  assert.equal(parsed.version, "1.2.16");
  assert.equal(parsed.files.length, 3);
  assert.deepEqual(parsed.files[1], {
    url: "S2.Report.Sniffer-1.2.16-arm64-mac.zip",
    sha512: "ARMSHA==",
    size: 190,
  });
  assert.equal(parsed.path, "S2.Report.Sniffer-1.2.16-arm64-mac.zip");
  assert.equal(parsed.sha512, "ARMSHA==");
});

test("rejects manifests with a bad version, missing files, or bad sizes", () => {
  assert.throws(
    () => updater.parseLatestMacYml(SAMPLE_YML.replace("version: 1.2.16", "version: ../../evil")),
    /invalid version/
  );
  assert.throws(() => updater.parseLatestMacYml("version: 1.2.16\nfiles:\n"), /no files/);
  assert.throws(
    () => updater.parseLatestMacYml(SAMPLE_YML.replace("size: 190", "size: abc")),
    /invalid file size/
  );
  assert.throws(
    () => updater.parseLatestMacYml(SAMPLE_YML.replace("    sha512: ARMSHA==\n", "")),
    /incomplete file entry/
  );
});

test("a manifest with a valid signature is accepted; a tampered one is refused", () => {
  const { publicKey, privateKey } = ed25519Pair();
  const ymlBuffer = Buffer.from(SAMPLE_YML);
  const sigText = signManifest(ymlBuffer, privateKey);

  const parsed = updater.verifyAndParseManifest({ ymlBuffer, sigText, publicKeyPem: publicKey });
  assert.equal(parsed.version, "1.2.16");

  const tampered = Buffer.from(SAMPLE_YML.replace("sha512: ARMSHA==", "sha512: EVILSHA=="));
  assert.throws(
    () => updater.verifyAndParseManifest({ ymlBuffer: tampered, sigText, publicKeyPem: publicKey }),
    /signature is invalid/
  );
});

test("Apple silicon, Rosetta and Intel hosts each get the right ZIP", () => {
  const files = updater.parseLatestMacYml(SAMPLE_YML).files;
  assert.equal(
    updater.selectZip(files, { isArm64Mac: true }).url,
    "S2.Report.Sniffer-1.2.16-arm64-mac.zip"
  );
  assert.equal(
    updater.selectZip(files, { isArm64Mac: false }).url,
    "S2.Report.Sniffer-1.2.16-x64-mac.zip"
  );
});

test("an arm64 host falls back to the x64 ZIP when no arm64 ZIP is published", () => {
  const files = [{ url: "S2-1.2.16-x64-mac.zip", sha512: "a", size: 1 }];
  assert.equal(updater.selectZip(files, { isArm64Mac: true }).url, "S2-1.2.16-x64-mac.zip");
});

test("selectZip returns null when no ZIP is listed", () => {
  const files = [{ url: "S2-1.2.16-arm64.dmg", sha512: "a", size: 1 }];
  assert.equal(updater.selectZip(files, { isArm64Mac: true }), null);
});

test("isArm64Host detects native Apple silicon and Rosetta translation", () => {
  assert.equal(updater.isArm64Host({ sysctlOutput: "sysctl.proc_translated: 1", arch: "x64" }), true);
  assert.equal(updater.isArm64Host({ unameOutput: "Darwin mac 25.6.0 arm64 ARM64", arch: "x64" }), true);
  assert.equal(updater.isArm64Host({ sysctlOutput: "sysctl.proc_translated: 0", unameOutput: "x86_64", arch: "x64" }), false);
  assert.equal(updater.isArm64Host({ arch: "arm64" }), true);
});

test("feed URLs must be HTTPS, or HTTP to loopback for local testing", () => {
  assert.equal(
    updater.resolveFeedUrl("https://github.com/o/r/releases/latest/download/", "a.zip"),
    "https://github.com/o/r/releases/latest/download/a.zip"
  );
  assert.equal(updater.resolveFeedUrl("http://127.0.0.1:8080/", "a.zip"), "http://127.0.0.1:8080/a.zip");
  assert.throws(() => updater.resolveFeedUrl("http://example.com/", "a.zip"), /non-HTTPS/);
  assert.throws(() => updater.resolveFeedUrl("file:///etc/", "passwd"), /non-HTTPS/);
});

test("ZIP names cannot escape the download directory", () => {
  assert.equal(updater.fileNameFromUrl("https://h/x/S2 Report Sniffer-1.2.16-arm64-mac.zip"), "S2 Report Sniffer-1.2.16-arm64-mac.zip");
  assert.throws(() => updater.fileNameFromUrl("https://h/a%2F..%2Fevil.zip"), /plain ZIP/);
  assert.throws(() => updater.fileNameFromUrl("https://h/app.dmg"), /plain ZIP/);
});

test("downloadVerified keeps a file only when size and SHA-512 match", async (t) => {
  const payload = Buffer.from("fake app zip contents ".repeat(500));
  const server = http.createServer((req, res) => {
    if (req.url === "/broken.zip") {
      res.statusCode = 500;
      return res.end("nope");
    }
    return res.end(payload);
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  t.after(() => server.close());
  const base = `http://127.0.0.1:${server.address().port}`;
  const destDir = tmpDir("s2rs-dl-");

  const progress = [];
  const saved = await updater.downloadVerified({
    url: `${base}/ok.zip`,
    sha512: sha512Base64(payload),
    size: payload.length,
    destDir,
    onProgress: (p) => progress.push(p.percent),
  });
  assert.equal(fs.readFileSync(saved).equals(payload), true);
  assert.equal(progress.at(-1), 100);
  assert.equal(fs.existsSync(`${saved}.part`), false);

  await assert.rejects(
    updater.downloadVerified({
      url: `${base}/ok.zip`,
      sha512: sha512Base64(Buffer.from("different")),
      size: payload.length,
      destDir: tmpDir("s2rs-dl-"),
    }),
    /checksum mismatch/
  );

  await assert.rejects(
    updater.downloadVerified({ url: `${base}/ok.zip`, sha512: sha512Base64(payload), size: 5, destDir: tmpDir("s2rs-dl-") }),
    /size mismatch/
  );

  const badDir = tmpDir("s2rs-dl-");
  await assert.rejects(
    updater.downloadVerified({ url: `${base}/broken.zip`, sha512: "x", size: 1, destDir: badDir }),
    /HTTP 500/
  );
  assert.deepEqual(fs.readdirSync(badDir), []);
});

function fakeBundle(root, { bundleId = "com.s2reportsniffer.app", version = "1.2.16" } = {}) {
  const app = path.join(root, "S2 Report Sniffer.app");
  fs.mkdirSync(path.join(app, "Contents", "MacOS"), { recursive: true });
  fs.mkdirSync(path.join(app, "Contents", "Resources", "backend"), { recursive: true });
  fs.writeFileSync(path.join(app, "Contents", "MacOS", "S2 Report Sniffer"), "");
  fs.writeFileSync(path.join(app, "Contents", "Resources", "backend", "s2rs-backend"), "");
  const plist = { CFBundleIdentifier: bundleId, CFBundleShortVersionString: version };
  fs.writeFileSync(path.join(app, "Contents", "Info.plist"), JSON.stringify(plist));
  return { app };
}

function fakeExec({ archs = "arm64", codesignFails = false } = {}) {
  return (file, args) => {
    if (file.endsWith("codesign")) {
      if (codesignFails) throw new Error("a sealed resource is missing or invalid");
      return "";
    }
    if (file.endsWith("plutil")) {
      const info = JSON.parse(fs.readFileSync(args[args.length - 1], "utf8"));
      return info[args[1]] ?? "";
    }
    if (file.endsWith("lipo")) return `${archs}\n`;
    throw new Error(`unexpected command ${file}`);
  };
}

test("stageBundle accepts a matching arm64 bundle and returns its path", () => {
  const root = tmpDir("s2rs-stage-");
  const stagingDir = path.join(root, "staged");
  const exec = fakeExec({ archs: "arm64" });
  const extract = (_zip, dest) => fakeBundle(dest);
  const app = updater.stageBundle({
    zipPath: "unused.zip",
    stagingDir,
    expectedVersion: "1.2.16",
    expectedArch: "arm64",
    extract,
    exec,
  });
  assert.equal(path.basename(app), "S2 Report Sniffer.app");
});

test("stageBundle rejects wrong identifier, version, architecture, or a failed seal", () => {
  const cases = [
    { name: "bundle id", exec: fakeExec(), bundleId: "com.evil.app", version: "1.2.16", arch: "arm64", pattern: /bundle identifier/ },
    { name: "version", exec: fakeExec(), bundleId: undefined, version: "9.9.9", arch: "arm64", pattern: /does not match manifest/ },
    { name: "arch", exec: fakeExec({ archs: "x86_64" }), bundleId: undefined, version: "1.2.16", arch: "arm64", pattern: /not built for arm64/ },
    { name: "seal", exec: fakeExec({ codesignFails: true }), bundleId: undefined, version: "1.2.16", arch: "arm64", pattern: /sealed resource/ },
  ];
  for (const c of cases) {
    const root = tmpDir("s2rs-stage-");
    const extract = (_zip, dest) => fakeBundle(dest, { bundleId: c.bundleId || "com.s2reportsniffer.app" });
    assert.throws(
      () => updater.stageBundle({
        zipPath: "unused.zip",
        stagingDir: path.join(root, "staged"),
        expectedVersion: c.version,
        expectedArch: c.arch,
        extract,
        exec: c.exec,
      }),
      c.pattern,
      c.name
    );
  }
});

test("stageBundle refuses an archive with no app bundle or a missing backend", () => {
  const root = tmpDir("s2rs-stage-");
  assert.throws(
    () => updater.stageBundle({ zipPath: "x", stagingDir: path.join(root, "a"), expectedVersion: "1.2.16", expectedArch: "arm64", extract: () => {}, exec: fakeExec() }),
    /does not contain an app bundle/
  );
  const extract = (_zip, dest) => {
    const { app } = fakeBundle(dest);
    fs.rmSync(path.join(app, "Contents", "Resources", "backend", "s2rs-backend"));
  };
  assert.throws(
    () => updater.stageBundle({ zipPath: "x", stagingDir: path.join(root, "b"), expectedVersion: "1.2.16", expectedArch: "arm64", extract, exec: fakeExec() }),
    /missing Contents\/Resources\/backend\/s2rs-backend/
  );
});

test("isInstallableLocation refuses DMG and translocated paths", () => {
  assert.equal(updater.isInstallableLocation("/Applications/S2 Report Sniffer.app").ok, true);
  assert.equal(updater.isInstallableLocation("/Volumes/S2/S2 Report Sniffer.app").ok, false);
  assert.equal(
    updater.isInstallableLocation("/private/var/folders/x/AppTranslocation/ABC/d/S2 Report Sniffer.app").ok,
    false
  );
  assert.equal(updater.isInstallableLocation("/Applications/notes.txt").ok, false);
});

test("canSelfUpdate only enables for packaged, ad-hoc signed macOS builds", () => {
  const adhoc = "Signature=adhoc\nTeamIdentifier=not set\n";
  const devId = "Authority=Developer ID Application: Example (ABCDE12345)\nTeamIdentifier=ABCDE12345\n";
  const app = "/Applications/S2 Report Sniffer.app";
  assert.equal(updater.canSelfUpdate({ platform: "darwin", isPackaged: true, appPath: app, codesignOutput: adhoc }).ok, true);
  assert.equal(updater.canSelfUpdate({ platform: "darwin", isPackaged: true, appPath: app, codesignOutput: devId }).ok, false);
  assert.equal(updater.canSelfUpdate({ platform: "darwin", isPackaged: false, appPath: app, codesignOutput: adhoc }).ok, false);
  assert.equal(updater.canSelfUpdate({ platform: "linux", isPackaged: true, appPath: app, codesignOutput: adhoc }).ok, false);
  assert.equal(updater.canSelfUpdate({ platform: "darwin", isPackaged: true, appPath: "/Volumes/S2/S2 Report Sniffer.app", codesignOutput: adhoc }).ok, false);
});
