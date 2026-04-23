const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');

exports.default = async function(context) {
  const { appOutDir } = context;

  const backendPath = path.join(appOutDir, 'S2 Report Sniffer.app', 'Contents', 'Resources', 'backend', 's2rs-backend');
  const backendDir  = path.join(appOutDir, 'S2 Report Sniffer.app', 'Contents', 'Resources', 'backend');

  if (!fs.existsSync(backendPath)) {
    console.warn(`Backend executable not found at: ${backendPath}`);
    return;
  }

  try {
    execFileSync('/bin/chmod', ['755', backendPath]);
    console.log(`chmod 755 applied: ${backendPath}`);
  } catch (e) {
    console.error(`chmod failed: ${e.message}`);
    throw e;
  }

  try {
    execFileSync('/usr/bin/xattr', ['-dr', 'com.apple.quarantine', backendDir]);
    console.log(`Quarantine stripped from backend dir`);
  } catch (e) {
    console.warn(`xattr strip failed (non-fatal): ${e.message}`);
  }
};
