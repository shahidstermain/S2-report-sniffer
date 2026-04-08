import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ChevronLeft, Loader2 } from "lucide-react";
import { getSupabaseClient } from "@/lib/supabase";

export default function SupabaseTodos() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [todos, setTodos] = useState([]);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError("");

    (async () => {
      try {
        const supabase = getSupabaseClient();
        const { data, error: qErr } = await supabase.from("todos").select("*").limit(100);
        if (qErr) throw qErr;
        if (!alive) return;
        setTodos(Array.isArray(data) ? data : []);
      } catch (e) {
        if (!alive) return;
        setError(String(e?.message || e));
      } finally {
        if (!alive) return;
        setLoading(false);
      }
    })();

    return () => {
      alive = false;
    };
  }, []);

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
              Supabase Todos
            </h1>
            <p className="text-xs" style={{ color: "var(--ss-mid-gray)" }}>
              Reads from table: todos
            </p>
          </div>
        </div>

        {loading && (
          <div className="ss-card p-6 flex items-center gap-3">
            <Loader2 className="animate-spin" size={16} />
            <span className="text-sm">Loading…</span>
          </div>
        )}

        {!loading && error && (
          <div className="ss-card p-6">
            <div className="text-sm font-bold mb-1">Supabase error</div>
            <div className="text-xs font-mono whitespace-pre-wrap" style={{ color: "var(--ss-critical)" }}>
              {error}
            </div>
            <div className="text-xs mt-3" style={{ color: "var(--ss-mid-gray)" }}>
              Set REACT_APP_SUPABASE_URL and REACT_APP_SUPABASE_ANON_KEY in frontend/.env.local, then restart the UI.
            </div>
          </div>
        )}

        {!loading && !error && (
          <div className="ss-card overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full dense-table min-w-[640px]">
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>Name</th>
                    <th>Created</th>
                  </tr>
                </thead>
                <tbody>
                  {todos.map((t) => (
                    <tr key={String(t.id ?? t.name)}>
                      <td className="font-mono text-[12px]">{t.id ?? "—"}</td>
                      <td className="text-[12px]">{t.name ?? t.title ?? "—"}</td>
                      <td className="font-mono text-[12px]">{t.created_at ?? "—"}</td>
                    </tr>
                  ))}
                  {todos.length === 0 && (
                    <tr>
                      <td colSpan={3} className="text-center py-10" style={{ color: "var(--ss-mid-gray)" }}>
                        No rows returned.
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

