import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ChevronLeft, Loader2 } from "lucide-react";
import { listVpsVirtualMachines } from "@/lib/api";

function statusClass(state) {
  const s = String(state || "").toLowerCase();
  if (["running", "active", "started"].includes(s)) return "badge-success";
  if (["stopped", "paused"].includes(s)) return "badge-muted";
  if (["error", "failed", "suspended"].includes(s)) return "badge-critical";
  return "badge-warning";
}

function VpsVmList() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [data, setData] = useState(null);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError("");
    listVpsVirtualMachines({ page: 1 })
      .then((r) => {
        if (!alive) return;
        setData(r.data);
      })
      .catch((e) => {
        if (!alive) return;
        const msg = e?.parsedData?.detail || e?.message || "Failed to load VPS list";
        setError(String(msg));
      })
      .finally(() => {
        if (!alive) return;
        setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, []);

  const items = Array.isArray(data?.data) ? data.data : Array.isArray(data) ? data : [];

  return (
    <div className="min-h-screen" style={{ background: "var(--ss-light-gray)" }}>
      <div className="max-w-6xl mx-auto px-4 sm:px-6 py-4 sm:py-6">
        <div className="flex flex-col sm:flex-row sm:items-center gap-3 mb-4">
          <button
            onClick={() => navigate("/")}
            className="flex items-center gap-2 text-xs border px-3 py-2 rounded bg-white"
            style={{ borderColor: "var(--ss-divider)" }}
          >
            <ChevronLeft size={14} /> Back
          </button>
          <div className="min-w-0">
            <h1 className="text-lg sm:text-xl font-bold tracking-tight" style={{ fontFamily: "Chivo, sans-serif" }}>
              Hostinger VPS / VM List
            </h1>
            <p className="text-xs" style={{ color: "var(--ss-mid-gray)" }}>
              Live inventory from Hostinger VPS API.
            </p>
          </div>
        </div>

        {loading && (
          <div className="ss-card p-6 flex items-center gap-3">
            <Loader2 className="animate-spin" size={16} />
            <span className="text-sm">Loading virtual machines…</span>
          </div>
        )}

        {!loading && error && (
          <div className="ss-card p-6">
            <div className="text-sm font-bold mb-1">Cannot load VPS list</div>
            <div className="text-xs font-mono whitespace-pre-wrap" style={{ color: "var(--ss-critical)" }}>
              {error}
            </div>
            <div className="text-xs mt-3" style={{ color: "var(--ss-mid-gray)" }}>
              Ensure the backend has HOSTINGER_API_TOKEN configured.
            </div>
          </div>
        )}

        {!loading && !error && (
          <div className="ss-card overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full dense-table min-w-[900px]">
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>Hostname</th>
                    <th>State</th>
                    <th>Location</th>
                    <th>Plan</th>
                    <th>IPv4</th>
                    <th>Created</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((vm) => {
                    const id = vm.id ?? vm.virtualMachineId ?? vm.virtual_machine_id ?? "—";
                    const hostname = vm.hostname ?? vm.name ?? "—";
                    const state = vm.state ?? vm.status ?? "unknown";
                    const location = vm.data_center?.name ?? vm.dataCenter?.name ?? vm.location ?? "—";
                    const plan = vm.plan?.name ?? vm.catalog_item?.name ?? vm.package?.name ?? "—";
                    const ipv4 =
                      (Array.isArray(vm.ipv4) && vm.ipv4[0]?.address) ||
                      vm.ipv4?.address ||
                      vm.ip_address ||
                      "—";
                    const created = vm.created_at ?? vm.createdAt ?? vm.created ?? "—";
                    return (
                      <tr key={String(id)}>
                        <td className="font-mono text-[12px]">{id}</td>
                        <td className="font-mono text-[12px]">{hostname}</td>
                        <td>
                          <span className={`${statusClass(state)} text-[11px] font-bold px-2 py-0.5`}>
                            {String(state)}
                          </span>
                        </td>
                        <td className="text-[12px]">{location}</td>
                        <td className="text-[12px]">{plan}</td>
                        <td className="font-mono text-[12px]">{ipv4}</td>
                        <td className="font-mono text-[12px]">{created}</td>
                      </tr>
                    );
                  })}
                  {items.length === 0 && (
                    <tr>
                      <td colSpan={7} className="text-center py-10" style={{ color: "var(--ss-mid-gray)" }}>
                        No virtual machines returned.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default VpsVmList;

