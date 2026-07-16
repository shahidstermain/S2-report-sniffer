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
    return true;
  } catch {
    return false;
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
    if (!codesignVerify(appPath)) {
      throw new Error(`afterSign: Developer ID build failed codesign --verify for ${appPath}`);
    }
    console.log(`afterSign: Developer ID signature verified for ${appPath}`);
    return;
  }

  // Unsigned / internal distribution: always reseal with ad-hoc identity.
  console.log('afterSign: applying ad-hoc app-bundle signature (unsigned distribution build)');

  if (fs.existsSync(backendPath)) {
    execFileSync('/usr/bin/codesign', ['--force', '--sign', '-', backendPath], { stdio: 'inherit' });
  }

  const args = ['--force', '--deep', '--sign', '-'];
  if (fs.existsSync(entitlements)) {
    args.push('--entitlements', entitlements);
  }
  args.push(appPath);
  execFileSync('/usr/bin/codesign', args, { stdio: 'inherit' });

  if (!codesignVerify(appPath) || !hasSealedResources(appPath)) {
    throw new Error(
      `afterSign: ad-hoc reseal failed verification for ${appPath}. ` +
        'The DMG would be rejected by Gatekeeper as "damaged".'
    );
  }
  console.log(`afterSign: ad-hoc sealed signature verified for ${appPath}`);
};
