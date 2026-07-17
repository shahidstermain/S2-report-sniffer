import { Download, RefreshCw, X } from "lucide-react";
import { useUpdater } from "@/hooks/useUpdater";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";

function notesText(notes) {
  if (typeof notes === "string") return notes;
  if (Array.isArray(notes)) return notes.map((item) => item?.note || item).filter(Boolean).join("\n");
  return "";
}

export default function UpdateBanner() {
  const updater = useUpdater();
  if (!updater.available || !["available", "downloading", "ready", "error"].includes(updater.status)) {
    return null;
  }

  const downloading = updater.status === "downloading";
  const ready = updater.status === "ready";
  return (
    <aside className="fixed bottom-4 left-1/2 z-50 w-[min(680px,calc(100%-2rem))] -translate-x-1/2 rounded-xl border border-primary/30 bg-card p-4 text-card-foreground shadow-2xl" role="status" aria-live="polite">
      <div className="flex items-start gap-3">
        <div className="mt-0.5 rounded-lg bg-primary/10 p-2 text-primary">
          {ready ? <RefreshCw className="size-5" /> : <Download className="size-5" />}
        </div>
        <div className="min-w-0 flex-1">
          <p className="font-semibold">
            {updater.status === "error" ? "Update could not be completed" : ready ? `Version ${updater.version} is ready` : `Version ${updater.version} is available`}
          </p>
          {updater.status === "error" ? (
            <p className="mt-1 text-sm text-destructive">{updater.error}</p>
          ) : downloading ? (
            <div className="mt-3 flex items-center gap-3"><Progress value={updater.downloadPercent} /><span className="text-xs tabular-nums">{updater.downloadPercent}%</span></div>
          ) : (
            <p className="mt-1 line-clamp-2 whitespace-pre-line text-sm text-muted-foreground">
              {ready ? "Restart to install the complete app update, including the local backend." : notesText(updater.releaseNotes) || "A new signed desktop release is ready to download."}
            </p>
          )}
          {!downloading && (
            <div className="mt-3 flex gap-2">
              {ready ? <Button size="sm" onClick={updater.install}>Restart and install</Button> : updater.status !== "error" && <Button size="sm" onClick={updater.download}>Download update</Button>}
              <Button size="sm" variant="ghost" onClick={updater.dismiss}>Later</Button>
            </div>
          )}
        </div>
        {!downloading && <button type="button" onClick={updater.dismiss} aria-label="Dismiss update" className="text-muted-foreground hover:text-foreground"><X className="size-4" /></button>}
      </div>
    </aside>
  );
}
