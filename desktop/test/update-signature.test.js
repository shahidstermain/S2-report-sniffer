"use strict";

const { test } = require("node:test");
const assert = require("node:assert/strict");
const crypto = require("crypto");
const fs = require("fs");
const os = require("os");
const path = require("path");

const { signManifest, verifyManifest } = require("../update-signature.js");
const { run, PUBLIC_KEY_PATH } = require("../../scripts/sign-update-manifest.js");

const MANIFEST = "version: 1.2.16\nfiles:\n  - url: S2.zip\n    sha512: abc\n    size: 1\n";

function ed25519Pair() {
  return crypto.generateKeyPairSync("ed25519", {
    publicKeyEncoding: { type: "spki", format: "pem" },
    privateKeyEncoding: { type: "pkcs8", format: "pem" },
  });
}

test("a manifest signed with the private key verifies with the public key", () => {
  const { publicKey, privateKey } = ed25519Pair();
  const sig = signManifest(MANIFEST, privateKey);
  assert.equal(verifyManifest(MANIFEST, sig, publicKey), true);
});

test("any change to the manifest bytes invalidates the signature", () => {
  const { publicKey, privateKey } = ed25519Pair();
  const sig = signManifest(MANIFEST, privateKey);
  assert.equal(verifyManifest(MANIFEST.replace("1.2.16", "9.9.9"), sig, publicKey), false);
});

test("a signature from a different key is rejected", () => {
  const trusted = ed25519Pair();
  const attacker = ed25519Pair();
  const sig = signManifest(MANIFEST, attacker.privateKey);
  assert.equal(verifyManifest(MANIFEST, sig, trusted.publicKey), false);
});

test("malformed or missing signatures fail closed", () => {
  const { publicKey } = ed25519Pair();
  assert.equal(verifyManifest(MANIFEST, undefined, publicKey), false);
  assert.equal(verifyManifest(MANIFEST, "", publicKey), false);
  assert.equal(verifyManifest(MANIFEST, "not-base64!!", publicKey), false);
  assert.equal(verifyManifest(MANIFEST, Buffer.alloc(10).toString("base64"), publicKey), false);
  assert.equal(verifyManifest(MANIFEST, "AAAA", "not a pem"), false);
});

test("signing refuses non-Ed25519 keys", () => {
  const rsa = crypto.generateKeyPairSync("rsa", {
    modulusLength: 2048,
    privateKeyEncoding: { type: "pkcs8", format: "pem" },
    publicKeyEncoding: { type: "spki", format: "pem" },
  });
  assert.throws(() => signManifest(MANIFEST, rsa.privateKey), /Ed25519/);
});

test("the committed public key is a usable Ed25519 key", () => {
  const pem = fs.readFileSync(path.join(__dirname, "..", "update-signing.pub"), "utf8");
  const key = crypto.createPublicKey(pem);
  assert.equal(key.asymmetricKeyType, "ed25519");
});

test("sign CLI fails without a key and never writes a signature", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "s2rs-sign-"));
  const manifest = path.join(dir, "latest-mac.yml");
  fs.writeFileSync(manifest, MANIFEST);
  assert.throws(() => run(["node", "sign", manifest], {}), /not set/);
  assert.equal(fs.existsSync(`${manifest}.sig`), false);
});

test("sign CLI rejects a key that does not match the committed public key", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "s2rs-sign-"));
  const manifest = path.join(dir, "latest-mac.yml");
  fs.writeFileSync(manifest, MANIFEST);
  const other = ed25519Pair();
  assert.throws(
    () => run(["node", "sign", manifest], { S2RS_UPDATE_SIGNING_KEY: other.privateKey }),
    /does not match/
  );
  assert.equal(fs.existsSync(`${manifest}.sig`), false);
});

test("sign CLI writes a verifiable signature when the key matches", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "s2rs-sign-"));
  const manifest = path.join(dir, "latest-mac.yml");
  fs.writeFileSync(manifest, MANIFEST);
  const pair = ed25519Pair();
  const pubPath = path.join(dir, "update-signing.pub");
  fs.writeFileSync(pubPath, pair.publicKey);

  const sigPath = run(["node", "sign", manifest], { S2RS_UPDATE_SIGNING_KEY: pair.privateKey }, pubPath);
  const sig = fs.readFileSync(sigPath, "utf8");
  assert.equal(sigPath, `${manifest}.sig`);
  assert.equal(verifyManifest(fs.readFileSync(manifest), sig, pair.publicKey), true);
});

test("the production public key path points at the committed key file", () => {
  assert.equal(path.basename(PUBLIC_KEY_PATH), "update-signing.pub");
  assert.ok(fs.existsSync(PUBLIC_KEY_PATH));
});
