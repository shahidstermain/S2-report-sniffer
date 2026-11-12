"use strict";

/**
 * Ed25519 signatures for the macOS update manifest (latest-mac.yml).
 *
 * The release workflow signs the raw bytes of the manifest with a private key
 * held only in GitHub Actions secrets. The desktop app ships the matching
 * public key (desktop/update-signing.pub) and refuses any manifest whose
 * signature does not verify. This is the integrity check a Developer ID
 * signature would otherwise provide. Node built-ins only; no dependencies.
 */

const crypto = require("crypto");

const SIGNATURE_BYTES = 64;

/**
 * Signs `data` (a Buffer or string) and returns a base64 Ed25519 signature.
 * Throws if the key is not an Ed25519 private key.
 */
function signManifest(data, privateKeyPem) {
  const key = crypto.createPrivateKey(privateKeyPem);
  if (key.asymmetricKeyType !== "ed25519") {
    throw new Error("Update signing key must be an Ed25519 private key");
  }
  return crypto.sign(null, Buffer.from(data), key).toString("base64");
}

/**
 * Returns true only when `signatureBase64` is a valid Ed25519 signature of
 * `data` under `publicKeyPem`. Any malformed input fails closed (returns false).
 */
function verifyManifest(data, signatureBase64, publicKeyPem) {
  if (typeof signatureBase64 !== "string") return false;
  const signature = Buffer.from(signatureBase64.trim(), "base64");
  if (signature.length !== SIGNATURE_BYTES) return false;

  let key;
  try {
    key = crypto.createPublicKey(publicKeyPem);
  } catch {
    return false;
  }
  if (key.asymmetricKeyType !== "ed25519") return false;
  return crypto.verify(null, Buffer.from(data), key, signature);
}

module.exports = { signManifest, verifyManifest };
