import { describe, it, expect } from "vitest";
import { pickDataDisk } from "./NodeHealth";

// Mirror getMaxDiskPct's pickDataDisk dependency for sort-by-disk consistency checks.
function sortDiskPct(node) {
  const picked = pickDataDisk(node.metrics?.disk || []);
  if (picked?.use_pct != null && Number.isFinite(Number(picked.use_pct))) {
    return Number(picked.use_pct);
  }
  return -1;
}

describe("pickDataDisk", () => {
  it("prefers memsql/data mount over root filesystem", () => {
    const disk = pickDataDisk([
      { mounted_on: "/", use_pct: 66, used: "7.5G", size: "12G" },
      { mounted_on: "/media/hdisk0", use_pct: 81, used: "966G", size: "1.3T" },
    ]);

    expect(disk.mounted_on).toBe("/media/hdisk0");
    expect(disk.use_pct).toBe(81);
  });

  it("falls back to highest-use mount when no data path is present", () => {
    const disk = pickDataDisk([
      { mounted_on: "/", use_pct: 40, used: "4G", size: "10G" },
      { mounted_on: "/var", use_pct: 55, used: "5G", size: "9G" },
    ]);

    expect(disk.mounted_on).toBe("/var");
  });

  it("selects the highest use memsql mount when multiple are present", () => {
    const disk = pickDataDisk([
      { mounted_on: "/var/lib/memsql", use_pct: 60, used: "60G", size: "100G" },
      { mounted_on: "/var/lib/memsql-data", use_pct: 80, used: "80G", size: "100G" },
      { mounted_on: "/", use_pct: 90, used: "90G", size: "100G" },
    ]);
    expect(disk.mounted_on).toBe("/var/lib/memsql-data");
    expect(disk.use_pct).toBe(80);
  });

  it("selects / if it is the only option and ranked low", () => {
    const disk = pickDataDisk([
      { mounted_on: "/", use_pct: 40, used: "4G", size: "10G" },
      { mounted_on: "/boot", use_pct: 10, used: "1G", size: "10G" },
    ]);
    expect(disk.mounted_on).toBe("/");
    expect(disk.use_pct).toBe(40);
  });

  it("sort-by-disk uses the same pickDataDisk mount as the Disk bar", () => {
    const node = {
      metrics: {
        disk: [
          { mounted_on: "/", use_pct: 95, used: "9G", size: "10G" },
          { mounted_on: "/media/hdisk0", use_pct: 70, used: "700G", size: "1T" },
        ],
      },
    };
    const displayed = pickDataDisk(node.metrics.disk);
    expect(displayed.mounted_on).toBe("/media/hdisk0");
    expect(sortDiskPct(node)).toBe(70);
  });
});
