#!/usr/bin/env python3
"""
Convert s2rs-icon-v2.png to an Apple .icns file.
Uses sips to generate all required sizes, then iconutil to bundle.
"""
import subprocess, os, shutil

SRC_PNG = "/Users/shahidster/S2-report-sniffer/docs/s2rs-icon-v2.png"
ICNS_OUT = "/Users/shahidster/S2-report-sniffer/desktop/assets/icon.icns"
WORK_DIR = "/tmp/s2rs-icon-icns"

SIZES = [16, 32, 64, 128, 256, 512, 1024]

os.makedirs(WORK_DIR, exist_ok=True)

iconset = os.path.join(WORK_DIR, "S2ReportSniffer.iconset")

for sz in SIZES:
    out_dir = os.path.join(WORK_DIR, f"{sz}x{sz}.png")
    if sz <= 512:
        subprocess.run([
            "sips", "-z", str(sz), str(sz),
            SRC_PNG, "--out", out_dir
        ], check=True, capture_output=True)
    else:
        subprocess.run([
            "sips", "-z", str(sz), str(sz),
            SRC_PNG, "--out", out_dir
        ], check=True, capture_output=True)

iconset_contents = os.listdir(WORK_DIR)
print(f"Generated sizes: {[f for f in iconset_contents if f.endswith('.png')]}")

subprocess.run(["mkdir", "-p", iconset], check=True)
for sz in SIZES:
    src = os.path.join(WORK_DIR, f"{sz}x{sz}.png")
    dst = os.path.join(iconset, f"icon_{sz}x{sz}.png")
    if os.path.exists(src):
        shutil.copy2(src, dst)
        print(f"  copied {sz}x{sz}")

    if sz > 16:
        half = sz // 2
        src2 = os.path.join(WORK_DIR, f"{half}x{half}.png")
        dst2 = os.path.join(iconset, f"icon_{sz}x{sz}@2x.png")
        if os.path.exists(src2):
            shutil.copy2(src2, dst2)
            print(f"  copied {sz}x{sz}@2x")

os.makedirs(os.path.dirname(ICNS_OUT), exist_ok=True)
subprocess.run(["iconutil", "-c", "icns", "-o", ICNS_OUT, iconset], check=True, capture_output=True)
print(f"\n.icns generated: {ICNS_OUT}")
print(f"Size: {os.path.getsize(ICNS_OUT)/1024:.1f} KB")
shutil.rmtree(WORK_DIR)
print("Work dir cleaned up.")