import { useEffect, useState } from "react";
import { Download } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";

export default function UpdatePreferences() {
  const updater = typeof window !== "undefined" ? window.s2rsDesktop?.updater : undefined;
  const [enabled, setEnabled] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    updater?.getAutoUpdateEnabled()
      .then((result) => setEnabled(Boolean(result?.enabled)))
      .catch(() => undefined);
  }, [updater]);

  if (!updater) return null;

  const toggle = async (next) => {
    setSaving(true);
    try {
      const result = await updater.setAutoUpdateEnabled(next);
      setEnabled(Boolean(result?.enabled));
      if (result?.forcedDisabled) toast.error("Updates are disabled by the administrator");
      else toast.success(next ? "Automatic update checks enabled" : "Automatic update checks disabled");
    } catch {
      toast.error("Could not save update preference");
    } finally {
      setSaving(false);
    }
  };

  const checkNow = async () => {
    try {
      const result = await updater.checkForUpdates();
      if (result?.status === "skipped-development") toast.info("Update checks run in packaged builds");
    } catch (error) {
      toast.error(error?.message || "Could not check for updates");
    }
  };

  return (
    <div className="flex items-start gap-3 md:max-w-md">
      <label className="flex flex-1 cursor-pointer items-start gap-3">
        <input type="checkbox" checked={enabled} disabled={saving} onChange={(event) => toggle(event.target.checked)} className="mt-1 size-4 accent-[var(--ss-purple)]" data-testid="auto-update-toggle" />
        <span>
          <span className="flex items-center gap-2 text-sm font-semibold"><Download className="size-4 text-primary" /> Desktop updates</span>
          <span className="mt-0.5 block text-xs text-muted-foreground">Opt in to contacting GitHub Releases for signed app updates. Report data is never sent.</span>
        </span>
      </label>
      <Button type="button" size="sm" variant="outline" onClick={checkNow}>Check now</Button>
    </div>
  );
}
