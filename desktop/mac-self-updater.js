"use strict";

/**
 * Pure logic for the macOS self-updater. Nothing here imports Electron, so it
 * runs under `node --test`. main.js wires it to the update UI in a later step.
 *
 * Why this exists: Squirrel.Mac (used by electron-updater) checks the code
 * signature of the new bundle against the installed one. Ad-hoc signed builds
 * cannot satisfy that check, so on macOS this module downloads, verifies and
 * stages the update itself. Every step fails closed.
 *
 * Trust chain:
 *   latest-mac.yml  --Ed25519 signature (update-signing.pub)-->  trusted manifest
 *   trusted manifest --SHA-512 + size-->                        trusted ZIP
 *   trusted ZIP     --ditto + codesign + plist + lipo checks--> staged app bundle
 */

const crypto = require("crypto");
const fs = require("fs");
const path = require("path");
const { Readable, Transform } = require("stream");
const { pipeline } = require("stream/promises");
const { execFileSync } = require("child_process");
const { verifyManifest } = require("./update-signature.js");

const BUNDLE_ID = "com.s2reportsniffer.app";
const DEFAULT_PRODUCT_NAME = "S2 Report Sniffer";
const VERSION_PATTERN = /^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$/;
const ZIP_NAME_PATTERN = /^[A-Za-z0-9._ -]+\.zip$/;
const LOOPBACK_HOSTS = new Set(["127.0.0.1", "localhost"]);
const LIPO_ARCH_BY_TARGET = { arm64: "arm64", x64: "x86_64" };

function unquote(value) {
  return value.trim().replace(/^['"]|['"]$/g, "");
}

function splitKeyValue(body) {
  const index = body.indexOf(":");
  if (index === -1) return [body.trim(), ""];
  return [body.slice(0, index).trim(), unquote(body.slice(index + 1))];
}

/**
 * Parses the electron-builder style latest-mac.yml produced by
 * scripts/merge_mac_update_manifests.py. Throws on anything unexpected.
 */
function parseLatestMacYml(text) {
  let version = "";
  let topPath = "";
  let topSha512 = "";
  const files = [];
  let inFiles = false;
  let current = null;

  for (const raw of String(text).split(/\r?\n/)) {
    const line = raw.trimEnd();
    if (!line.trim()) continue;
    const indent = line.length - line.trimStart().length;
    const body = line.trimStart();

    if (indent === 0) {
      inFiles = body === "files:";
      current = null;
      const [key, value] = splitKeyValue(body);
      if (key === "version") version = value;
      else if (key === "path") topPath = value;
      else if (key === "sha512") topSha512 = value;
      continue;
    }
    if (!inFiles) continue;
    if (body.startsWith("- url:")) {
      current = { url: unquote(body.slice("- url:".length)) };
      files.push(current);
      continue;
    }
    if (current && indent >= 4) {
      const [key, value] = splitKeyValue(body);
      current[key] = value;
    }
  }

  if (!VERSION_PATTERN.test(version)) {
    throw new Error("Update manifest has a missing or invalid version");
  }
  if (files.length === 0) {
    throw new Error("Update manifest lists no files");
  }
  const normalized = files.map((file) => {
    if (!file.url || !file.sha512 || file.size === undefined) {
      throw new Error("Update manifest has an incomplete file entry");
    }
    const size = Number(file.size);
    if (!Number.isSafeInteger(size) || size <= 0) {
      throw new Error("Update manifest has an invalid file size");
    }
    return { url: file.url, sha512: file.sha512, size };
  });

  return { version, files: normalized, path: topPath, sha512: topSha512 };
}

/**
 * Verifies the Ed25519 signature over the raw manifest bytes, then parses it.
 * The signature is checked before any field is trusted.
 */
function verifyAndParseManifest({ ymlBuffer, sigText, publicKeyPem }) {
  if (!verifyManifest(ymlBuffer, sigText, publicKeyPem)) {
    throw new Error("Update manifest signature is invalid; refusing to update");
  }
  return parseLatestMacYml(Buffer.from(ymlBuffer).toString("utf8"));
}

/**
 * Detects Apple silicon, including an Intel build running under Rosetta.
 * Mirrors electron-updater: sysctl.proc_translated, then uname, then process.arch.
 */
function isArm64Host({ sysctlOutput = "", unameOutput = "", arch = process.arch } = {}) {
  return (
    /sysctl\.proc_translated:\s*1/.test(sysctlOutput) ||
    /ARM/.test(unameOutput) ||
    arch === "arm64"
  );
}

/**
 * Chooses the ZIP for this Mac, using the same rule as electron-updater's
 * MacUpdater.filterFilesForArch: on Apple silicon prefer arm64 files when any
 * exist; otherwise use the non-arm64 files. Returns null when no ZIP matches.
 */
function selectZip(files, { isArm64Mac }) {
  const isArm64File = (file) => file.url.includes("arm64");
  const hasArm64 = files.some(isArm64File);
  const candidates = hasArm64
    ? files.filter((file) => isArm64File(file) === isArm64Mac)
    : files.filter((file) => !isArm64File(file));
  return candidates.find((file) => file.url.endsWith(".zip")) || null;
}

/**
 * Resolves a manifest URL against the feed base. Only HTTPS is accepted, or
 * plain HTTP to loopback for local testing and mirrors.
 */
function resolveFeedUrl(feedBase, relativeUrl) {
  const url = new URL(relativeUrl, feedBase);
  const loopbackHttp = url.protocol === "http:" && LOOPBACK_HOSTS.has(url.hostname);
  if (url.protocol !== "https:" && !loopbackHttp) {
    throw new Error(`Refusing non-HTTPS update URL (${url.protocol})`);
  }
  return url.toString();
}

/** Takes the ZIP file name from a URL, rejecting anything that could escape the directory. */
function fileNameFromUrl(url) {
  const name = decodeURIComponent(path.posix.basename(new URL(url).pathname));
  if (!ZIP_NAME_PATTERN.test(name) || name.includes("..")) {
    throw new Error("Update URL does not point to a plain ZIP file name");
  }
  return name;
}

/**
 * Streams the ZIP to `<destDir>/<name>.part`, hashing as it goes. The file is
 * renamed into place only if the size and SHA-512 match the signed manifest.
 */
async function downloadVerified({
  url,
  sha512,
  size,
  destDir,
  fetchImpl = globalThis.fetch,
  onProgress,
}) {
  const destPath = path.join(destDir, fileNameFromUrl(url));
  const partPath = `${destPath}.part`;
  fs.mkdirSync(destDir, { recursive: true });

  const response = await fetchImpl(url);
  if (!response.ok || !response.body) {
    throw new Error(`Update download failed (HTTP ${response.status})`);
  }

  const hash = crypto.createHash("sha512");
  let received = 0;
  const meter = new Transform({
    transform(chunk, _encoding, callback) {
      hash.update(chunk);
      received += chunk.length;
      if (onProgress) {
        onProgress({
          transferred: received,
          total: size,
          percent: Math.min(100, Math.round((received * 100) / size)),
        });
      }
      callback(null, chunk);
    },
  });

  try {
    await pipeline(Readable.fromWeb(response.body), meter, fs.createWriteStream(partPath));
    if (received !== size) {
      throw new Error(`Update size mismatch (expected ${size} bytes, got ${received})`);
    }
    if (hash.digest("base64") !== sha512) {
      throw new Error("Update checksum mismatch; download discarded");
    }
    fs.renameSync(partPath, destPath);
    return destPath;
  } catch (error) {
    fs.rmSync(partPath, { force: true });
    throw error;
  }
}

function defaultExtract(zipPath, destDir) {
  fs.mkdirSync(destDir, { recursive: true });
  execFileSync("/usr/bin/ditto", ["-x", "-k", zipPath, destDir]);
}

function defaultExec(file, args) {
  return execFileSync(file, args, { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] });
}

/**
 * Unpacks the verified ZIP into `stagingDir` and checks that it is the app we
 * expect: sealed signature, bundle identifier, version, and architecture of the
 * Electron binary and the bundled backend. Returns the staged .app path.
 */
function stageBundle({
  zipPath,
  stagingDir,
  expectedVersion,
  expectedArch,
  productName = DEFAULT_PRODUCT_NAME,
  extract = defaultExtract,
  exec = defaultExec,
}) {
  const want = LIPO_ARCH_BY_TARGET[expectedArch];
  if (!want) throw new Error(`Unsupported update architecture: ${expectedArch}`);

  extract(zipPath, stagingDir);
  const entries = fs.existsSync(stagingDir) ? fs.readdirSync(stagingDir) : [];
  const appName = entries.find((name) => name.endsWith(".app"));
  if (!appName) throw new Error("Update archive does not contain an app bundle");
  const appPath = path.join(stagingDir, appName);

  exec("/usr/bin/codesign", ["--verify", "--deep", "--strict", appPath]);

  const infoPlist = path.join(appPath, "Contents", "Info.plist");
  const readPlist = (key) =>
    exec("/usr/bin/plutil", ["-extract", key, "raw", "-o", "-", infoPlist]).trim();

  if (readPlist("CFBundleIdentifier") !== BUNDLE_ID) {
    throw new Error("Update bundle identifier does not match this app");
  }
  if (readPlist("CFBundleShortVersionString") !== expectedVersion) {
    throw new Error(`Update bundle version does not match manifest (${expectedVersion})`);
  }

  const binaries = [
    path.join(appPath, "Contents", "MacOS", productName),
    path.join(appPath, "Contents", "Resources", "backend", "s2rs-backend"),
  ];
  for (const binary of binaries) {
    const label = path.relative(appPath, binary);
    if (!fs.existsSync(binary)) throw new Error(`Update is missing ${label}`);
    const archs = exec("/usr/bin/lipo", ["-archs", binary]).trim().split(/\s+/);
    if (!archs.includes(want)) {
      throw new Error(`Update ${label} is not built for ${expectedArch}`);
    }
  }
  return appPath;
}

/** Refuses locations where an in-place swap cannot work safely. */
function isInstallableLocation(appPath) {
  const resolved = path.resolve(appPath);
  if (!resolved.endsWith(".app")) {
    return { ok: false, reason: "The app is not running from an app bundle" };
  }
  if (resolved.startsWith("/Volumes/")) {
    return { ok: false, reason: "Move the app to Applications before updating" };
  }
  if (resolved.includes("/AppTranslocation/")) {
    return { ok: false, reason: "Move the app to Applications before updating" };
  }
  return { ok: true, reason: "" };
}

/**
 * Self-update applies only to ad-hoc signed macOS builds. Developer ID builds
 * keep the standard Squirrel.Mac path, which is correct for them.
 * `codesignOutput` is the stderr of `codesign -dv --verbose=2 <app>`.
 */
function canSelfUpdate({ platform, isPackaged, appPath, codesignOutput = "" }) {
  if (platform !== "darwin") return { ok: false, reason: "Not macOS" };
  if (!isPackaged) return { ok: false, reason: "Development build" };
  const location = isInstallableLocation(appPath);
  if (!location.ok) return { ok: false, reason: location.reason };
  if (!/TeamIdentifier=not set/.test(codesignOutput)) {
    return { ok: false, reason: "Developer ID build uses the standard updater" };
  }
  return { ok: true, reason: "" };
}

module.exports = {
  BUNDLE_ID,
  parseLatestMacYml,
  verifyAndParseManifest,
  isArm64Host,
  selectZip,
  resolveFeedUrl,
  fileNameFromUrl,
  downloadVerified,
  stageBundle,
  isInstallableLocation,
  canSelfUpdate,
};
