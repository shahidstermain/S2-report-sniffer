#!/usr/bin/env node
"use strict";

/**
 * Signs the merged macOS update manifest for the desktop-release workflow.
 *
 *   S2RS_UPDATE_SIGNING_KEY="$(cat private-key.pem)" \
 *     node scripts/sign-update-manifest.js release-artifacts/latest-mac.yml
 *
 * Writes `<manifest>.sig` next to the manifest. Before writing, it verifies the
 * signature against desktop/update-signing.pub, so a mismatched secret fails the
 * release here instead of producing updates that installed apps reject.
 */

const fs = require("fs");
const path = require("path");
const { signManifest, verifyManifest } = require("../desktop/update-signature.js");

const PUBLIC_KEY_PATH = path.join(__dirname, "..", "desktop", "update-signing.pub");

function run(argv, env, publicKeyPath = PUBLIC_KEY_PATH) {
  const manifestPath = argv[2];
  if (!manifestPath) {
    throw new Error("usage: sign-update-manifest.js <latest-mac.yml>");
  }
  const privateKey = env.S2RS_UPDATE_SIGNING_KEY;
  if (!privateKey) {
    throw new Error(
      "S2RS_UPDATE_SIGNING_KEY is not set; refusing to publish an unsigned macOS update manifest"
    );
  }

  const data = fs.readFileSync(manifestPath);
  const signature = signManifest(data, privateKey);

  const publicKey = fs.readFileSync(publicKeyPath, "utf8");
  if (!verifyManifest(data, signature, publicKey)) {
    throw new Error("Signing key does not match desktop/update-signing.pub");
  }

  const sigPath = `${manifestPath}.sig`;
  fs.writeFileSync(sigPath, `${signature}\n`, { mode: 0o644 });
  return sigPath;
}

if (require.main === module) {
  try {
    const sigPath = run(process.argv, process.env);
    console.log(`signed ${process.argv[2]} -> ${sigPath}`);
  } catch (e) {
    console.error(e.message);
    process.exit(1);
  }
}

module.exports = { run, PUBLIC_KEY_PATH };
