import { useState, useEffect } from "react";
import { Settings, Check, X, RefreshCw, AlertCircle, ExternalLink } from "lucide-react";
import { getGleanConfig, saveGleanConfig, testGleanConnection } from "@/lib/api";
import { toast } from "sonner";

export default function GleanSetup() {
  const [config, setConfig] = useState({
    glean_url: "https://singlestore-be.glean.com/mcp/default",
    mcp_port: 3000,
    enabled: false
  });
  const [connectionStatus, setConnectionStatus] = useState("idle");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);

  useEffect(() => {
    loadConfig();
  }, []);

  const loadConfig = async () => {
    try {
      setLoading(true);
      const res = await getGleanConfig();
      setConfig(prev => ({
        ...prev,
        glean_url: res.data.glean_url || "https://singlestore-be.glean.com/mcp/default",
        mcp_port: res.data.mcp_port || 3000,
        enabled: res.data.enabled || false
      }));
    } catch (err) {
      console.error("Failed to load Glean config:", err);
      toast.error("Failed to load Glean configuration");
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async () => {
    try {
      setSaving(true);
      await saveGleanConfig(config);
      toast.success("Glean configuration saved");
      setConnectionStatus("idle");
    } catch (err) {
      console.error("Failed to save Glean config:", err);
      const errorData = err.response?.data;
      const errorMsg = errorData?.message || errorData?.error || err.message || "Failed to save configuration";
      toast.error(errorMsg, { duration: 5000 });
    } finally {
      setSaving(false);
    }
  };

  const handleTestConnection = async () => {
    try {
      setTesting(true);
      setConnectionStatus("testing");
      const res = await testGleanConnection();
      if (res.data.status === "ok") {
        setConnectionStatus("success");
        toast.success("Glean connection successful");
      } else {
        setConnectionStatus("error");
        const errorMsg = res.data.message || "Connection failed";
        toast.error(errorMsg, { duration: 5000 });
      }
    } catch (err) {
      console.error("Connection test failed:", err);
      setConnectionStatus("error");
      const errorMsg = err.response?.data?.message || err.message || "Connection test failed";
      toast.error(errorMsg, { duration: 5000 });
    } finally {
      setTesting(false);
    }
  };

  const handleDisconnect = async () => {
    try {
      setSaving(true);
      await saveGleanConfig({
        ...config,
        enabled: false
      });
      toast.success("Glean disconnected");
      setConnectionStatus("idle");
    } catch (err) {
      console.error("Failed to disconnect Glean:", err);
      toast.error("Failed to disconnect Glean");
    } finally {
      setSaving(false);
    }
  };

  const handleOpenGleanSettings = () => {
    window.open("https://app.glean.com/settings/install?mcpConfigure&mcpHost=windsurf&mcpServer=default", "_blank");
  };

  if (loading) {
    return (
      <div className="ss-card p-6">
        <div className="flex items-center gap-2 mb-4">
          <Settings size={20} style={{ color: "var(--ss-purple)" }} />
          <h3 className="text-sm font-bold uppercase tracking-wider">Glean Setup</h3>
        </div>
        <div className="flex items-center justify-center py-8">
          <RefreshCw size={24} className="animate-spin" style={{ color: "var(--ss-mid-gray)" }} />
        </div>
      </div>
    );
  }

  return (
    <div className="ss-card p-6" data-testid="glean-setup">
      <div className="flex items-center gap-2 mb-6 pb-3 border-b" style={{ borderColor: "var(--ss-divider)" }}>
        <Settings size={20} style={{ color: "var(--ss-purple)" }} />
        <h3 className="text-sm font-bold uppercase tracking-wider">Glean Integration</h3>
      </div>

      <div className="space-y-4">
        {/* Enable Toggle */}
        <div className="flex items-center justify-between">
          <div>
            <label className="text-sm font-semibold">Enable Glean Integration</label>
            <p className="text-xs mt-1" style={{ color: "var(--ss-mid-gray)" }}>
              Connect to Glean MCP server for contextual insights
            </p>
          </div>
          <button
            onClick={() => setConfig(prev => ({ ...prev, enabled: !prev.enabled }))}
            className={`p-2 rounded-full transition-colors ${
              config.enabled ? "bg-[#002FA7]" : "bg-zinc-200"
            }`}
            data-testid="enable-toggle"
          >
            {config.enabled ? <Check size={16} className="text-white" /> : <X size={16} style={{ color: "var(--ss-mid-gray)" }} />}
          </button>
        </div>

        {config.enabled && (
          <>
            {/* Connection Info Display */}
            <div className="p-3 rounded bg-zinc-50 border" style={{ borderColor: "var(--ss-divider)" }}>
              <div className="flex items-center gap-2 mb-2">
                <span className="text-xs font-semibold" style={{ color: "var(--ss-mid-gray)" }}>MCP Connection</span>
              </div>
              <div className="space-y-1">
                <div className="flex items-center justify-between">
                  <span className="text-xs">Local Port:</span>
                  <span className="text-xs font-mono font-bold text-[#002FA7]">localhost:{config.mcp_port}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-xs">Glean Endpoint:</span>
                  <span className="text-xs font-mono truncate max-w-[200px]" title={config.glean_url}>{config.glean_url || "Not set"}</span>
                </div>
              </div>
            </div>

            <div className="space-y-3">
              <div>
                <label className="block text-xs font-medium mb-1">Glean Instance URL</label>
                <input
                  type="text"
                  value={config.glean_url}
                  onChange={(e) => setConfig(prev => ({ ...prev, glean_url: e.target.value }))}
                  placeholder="https://singlestore-be.glean.com/mcp/default"
                  className="w-full px-3 py-2 text-sm border rounded focus:outline-none focus:ring-2 focus:ring-[#002FA7]"
                  style={{ borderColor: "var(--ss-divider)" }}
                  data-testid="glean-url-input"
                />
                <p className="text-xs mt-1" style={{ color: "var(--ss-mid-gray)" }}>
                  Default: SingleStore Glean MCP endpoint. Configure in Glean settings first.
                </p>
              </div>
              <div>
                <label className="block text-xs font-medium mb-1">MCP Server Port</label>
                <input
                  type="number"
                  value={config.mcp_port}
                  onChange={(e) => setConfig(prev => ({ ...prev, mcp_port: parseInt(e.target.value) || 3000 }))}
                  className="w-full px-3 py-2 text-sm border rounded focus:outline-none focus:ring-2 focus:ring-[#002FA7]"
                  style={{ borderColor: "var(--ss-divider)" }}
                  data-testid="mcp-port-input"
                />
                <p className="text-xs mt-1" style={{ color: "var(--ss-mid-gray)" }}>
                  Local MCP server port (default: 3000). This is where Glean MCP server runs.
                </p>
              </div>
            </div>

            {/* Setup Instructions */}
            <div className="p-3 rounded bg-blue-50 border border-blue-200">
              <p className="text-xs font-medium text-blue-800 mb-2">Setup Instructions:</p>
              <ol className="text-xs text-blue-700 space-y-1 list-decimal list-inside">
                <li>Click "Open Glean MCP Settings" to get your npx command</li>
                <li>Run the npx command in your terminal to start the MCP server</li>
                <li>Click "Test Connection" to verify the server is running</li>
                <li>Click "Save Configuration" to save settings</li>
              </ol>
            </div>

            {/* Open Glean Settings Button */}
            <button
              onClick={handleOpenGleanSettings}
              className="w-full p-2 text-sm font-medium rounded border hover:bg-zinc-50 transition-colors flex items-center justify-center gap-2"
              style={{ borderColor: "var(--ss-divider)" }}
              data-testid="open-glean-settings-button"
            >
              <ExternalLink size={16} />
              Open Glean MCP Settings
            </button>

            {/* Connection Status */}
            <div className="flex items-center justify-between p-3 rounded border" style={{ borderColor: "var(--ss-divider)" }}>
              <div className="flex items-center gap-2">
                {connectionStatus === "success" && <Check size={16} className="text-green-600" />}
                {connectionStatus === "error" && <AlertCircle size={16} className="text-red-600" />}
                {connectionStatus === "testing" && <RefreshCw size={16} className="animate-spin" style={{ color: "var(--ss-mid-gray)" }} />}
                <span className="text-xs font-medium">
                  {connectionStatus === "success" ? "Connected" : connectionStatus === "error" ? "Connection Failed" : connectionStatus === "testing" ? "Testing..." : "Not tested"}
                </span>
              </div>
              <button
                onClick={handleTestConnection}
                disabled={testing}
                className="px-3 py-1.5 text-xs font-medium rounded border hover:bg-zinc-50 transition-colors"
                style={{ borderColor: "var(--ss-divider)", opacity: testing ? 0.5 : 1 }}
                data-testid="test-connection-button"
              >
                {testing ? "Testing..." : "Test Connection"}
              </button>
            </div>

            {/* Action Buttons */}
            <div className="flex gap-2">
              <button
                onClick={handleSave}
                disabled={saving}
                className="flex-1 p-2 text-sm font-medium rounded bg-[#002FA7] text-white hover:bg-[#002FA7]/90 transition-colors"
                data-testid="save-config-button"
              >
                {saving ? "Saving..." : "Save Configuration"}
              </button>
              <button
                onClick={handleDisconnect}
                disabled={saving}
                className="px-4 py-2 text-sm font-medium rounded border hover:bg-zinc-50 transition-colors"
                style={{ borderColor: "var(--ss-divider)", opacity: saving ? 0.5 : 1 }}
                data-testid="disconnect-button"
              >
                Disconnect
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
