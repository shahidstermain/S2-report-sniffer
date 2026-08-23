const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');

/**
 * electron-builder afterPack hook.
 * Runs before code signing. Ensures the packed PyInstaller backend is executable
 * and that quarantine attrs from the build host do not ride into the bundle.
 */
function resolveAppBundle(appOutDir, productName) {
  const nested = path.join(appOutDir, `${productName}.app`);
  if (fs.existsSync(nested)) return nested;
  if (appOutDir.endsWith('.app') && fs.existsSync(appOutDir)) return appOutDir;
  if (!fs.existsSync(appOutDir)) return null;
  const hit = fs.readdirSync(appOutDir).find((name) => name.endsWith('.app'));
  return hit ? path.join(appOutDir, hit) : null;
}

exports.default = async function afterPack(context) {
  const productName = context.packager.appInfo.productFilename || 'S2 Report Sniffer';
  const isMac = context.electronPlatformName === 'darwin';
  const appPath = isMac ? resolveAppBundle(context.appOutDir, productName) : context.appOutDir;
  if (!appPath) {
    console.warn(`afterPack: could not locate packaged application under ${context.appOutDir}`);
    return;
  }

  const resourcesDir = isMac
    ? path.join(appPath, 'Contents', 'Resources')
    : path.join(appPath, 'resources');
  const backendDir = path.join(resourcesDir, 'backend');
  const backendName = context.electronPlatformName === 'win32' ? 's2rs-backend.exe' : 's2rs-backend';
  const backendPath = path.join(backendDir, backendName);

  if (fs.existsSync(backendPath)) {
    try {
      if (context.electronPlatformName !== 'win32') {
        fs.chmodSync(backendPath, 0o755);
        console.log(`afterPack: chmod 755 ${backendPath}`);
      } else {
        console.log(`afterPack: backend executable found at ${backendPath}`);
      }
    } catch (e) {
      console.error(`afterPack: chmod failed: ${e.message}`);
      throw e;
    }
  } else {
    console.warn(`afterPack: backend executable not found at ${backendPath}`);
  }

  if (isMac) {
    // Quarantine on nested build artifacts causes Gatekeeper "damaged" on open.
    for (const target of [backendDir, appPath]) {
      if (!fs.existsSync(target)) continue;
      try {
        execFileSync('/usr/bin/xattr', ['-cr', target]);
        console.log(`afterPack: cleared xattrs on ${target}`);
      } catch (e) {
        console.warn(`afterPack: xattr clear failed (non-fatal): ${e.message}`);
      }
    }
  }
};
