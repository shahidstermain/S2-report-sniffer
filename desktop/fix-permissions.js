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
  const appPath = resolveAppBundle(context.appOutDir, productName);
  if (!appPath) {
    console.warn(`afterPack: could not locate .app under ${context.appOutDir}`);
    return;
  }

  const backendPath = path.join(appPath, 'Contents', 'Resources', 'backend', 's2rs-backend');
  const backendDir = path.join(appPath, 'Contents', 'Resources', 'backend');

  if (fs.existsSync(backendPath)) {
    try {
      execFileSync('/bin/chmod', ['755', backendPath]);
      console.log(`afterPack: chmod 755 ${backendPath}`);
    } catch (e) {
      console.error(`afterPack: chmod failed: ${e.message}`);
      throw e;
    }
  } else {
    console.warn(`afterPack: backend executable not found at ${backendPath}`);
  }

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
};
