const fs = require('fs');
const path = require('path');
const { execFileSync, spawnSync } = require('child_process');

/**
 * electron-builder afterSign hook.
 *
 * Unsigned internal builds must receive a real ad-hoc app-bundle signature
 * (sealed resources). electron-builder often leaves only a linker-signed stub
 * when identity="-" is rejected against other keychain identities — macOS then
 * reports: "S2 Report Sniffer is damaged and can't be opened."
 *
 * When CSC_LINK / --signed Developer ID signing is in use, we only verify.
 */
function resolveAppBundle(appOutDir, productName) {
  const nested = path.join(appOutDir, `${productName}.app`);
  if (fs.existsSync(nested)) return nested;
  if (appOutDir.endsWith('.app') && fs.existsSync(appOutDir)) return appOutDir;
  if (!fs.existsSync(appOutDir)) return null;
  const hit = fs.readdirSync(appOutDir).find((name) => name.endsWith('.app'));
  return hit ? path.join(appOutDir, hit) : null;
}

function codesignVerify(appPath) {
  try {
    execFileSync('/usr/bin/codesign', ['--verify', '--deep', '--strict', appPath], {
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    return { ok: true, detail: '' };
  } catch (e) {
    const detail = `${e.stderr || e.stdout || e.message || ''}`.trim();
    return { ok: false, detail };
  }
}

function hasSealedResources(appPath) {
  const result = spawnSync('/usr/bin/codesign', ['-d', '--verbose=4', appPath], {
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  const output = `${result.stdout || ''}${result.stderr || ''}${result.error || ''}`;
  return /Sealed Resources version=\d+/i.test(output);
}

function isDeveloperIdBuild() {
  return Boolean(process.env.CSC_LINK || process.env.APPLE_TEAM_ID);
}

function adHocSign(targetPath, { deep = false, entitlements = null } = {}) {
  const args = ['--force', '--sign', '-', '--timestamp=none'];
  if (deep) args.splice(1, 0, '--deep');
  if (entitlements && fs.existsSync(entitlements)) {
    args.push('--entitlements', entitlements);
  }
  args.push(targetPath);
  execFileSync('/usr/bin/codesign', args, { stdio: 'inherit' });
}

exports.default = async function afterSign(context) {
  if (context.electronPlatformName !== 'darwin') return;

  const productName = context.packager.appInfo.productFilename || 'S2 Report Sniffer';
  const appPath = resolveAppBundle(context.appOutDir, productName);
  if (!appPath) {
    console.warn(`afterSign: could not locate .app under ${context.appOutDir}`);
    return;
  }

  const entitlements = path.join(__dirname, 'assets', 'entitlements.mac.plist');
  const backendPath = path.join(appPath, 'Contents', 'Resources', 'backend', 's2rs-backend');

  try {
    execFileSync('/usr/bin/xattr', ['-cr', appPath]);
  } catch (e) {
    console.warn(`afterSign: xattr clear failed (non-fatal): ${e.message}`);
  }

  if (isDeveloperIdBuild()) {
    const verified = codesignVerify(appPath);
    if (!verified.ok) {
      throw new Error(
        `afterSign: Developer ID build failed codesign --verify for ${appPath}: ${verified.detail}`
      );
    }
    console.log(`afterSign: Developer ID signature verified for ${appPath}`);
    return;
  }

  // Unsigned / internal distribution: always reseal with ad-hoc identity.
  console.log('afterSign: applying ad-hoc app-bundle signature (unsigned distribution build)');

  if (fs.existsSync(backendPath)) {
    adHocSign(backendPath);
  }

  adHocSign(appPath, { deep: true, entitlements });

  // codesign can briefly report "internal error" right after a deep reseal; retry once.
  let verified = codesignVerify(appPath);
  if (!verified.ok) {
    Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 500);
    verified = codesignVerify(appPath);
  }
  const sealed = hasSealedResources(appPath);
  if (!verified.ok || !sealed) {
    throw new Error(
      `afterSign: ad-hoc reseal failed verification for ${appPath}. ` +
        `The DMG would be rejected by Gatekeeper as "damaged". ` +
        `codesign: ${verified.detail || (sealed ? 'verify failed' : 'no sealed resources')}`
    );
  }
  console.log(`afterSign: ad-hoc sealed signature verified for ${appPath}`);
};
