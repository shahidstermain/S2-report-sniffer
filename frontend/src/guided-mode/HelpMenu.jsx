import { useMemo, useState } from "react";
import { BookOpen, HelpCircle, Play, Sparkles, X } from "lucide-react";
import { useLocation } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { glossaryForPage } from "./metricGlossary";
import { pageKeyFromPath } from "./tourRegistry";
import { useGuidedMode } from "./GuidedModeProvider";

export default function HelpMenu({ compact = false, showDemoAction = false }) {
  const location = useLocation();
  const [open, setOpen] = useState(false);
  const {
    explainPage,
    launchingDemo,
    startTour,
    toggleExplainPage,
    launchDemoWorkspace,
  } = useGuidedMode();

  const pageKey = pageKeyFromPath(location.pathname);
  const glossary = useMemo(() => glossaryForPage(pageKey), [pageKey]);

  return (
    <div className="relative" data-guide-id="guided.help">
      <Button
        type="button"
        variant="outline"
        size={compact ? "sm" : "default"}
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-label="Open guided mode help"
      >
        <HelpCircle className="size-4" />
        {!compact && "Guided help"}
      </Button>
      {open && (
        <Card className="absolute right-0 top-full z-50 mt-2 w-[min(380px,calc(100vw-32px))] shadow-2xl">
          <CardHeader className="pb-3">
            <div className="flex items-start justify-between gap-3">
              <div>
                <CardTitle className="text-base">Guided mode</CardTitle>
                <p className="text-xs text-muted-foreground mt-1">
                  Learn the app with tours, page explanations, and metric definitions.
                </p>
              </div>
              <Button variant="ghost" size="icon" className="size-8" onClick={() => setOpen(false)} aria-label="Close guided help">
                <X className="size-4" />
              </Button>
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            {showDemoAction && (
              <Button className="w-full justify-start" onClick={launchDemoWorkspace} disabled={launchingDemo} data-guide-id="demo.launch">
                <Sparkles className="size-4" />
                {launchingDemo ? "Creating demo…" : "Launch Demo Workspace"}
              </Button>
            )}
            <Button variant="outline" className="w-full justify-start" onClick={() => startTour()}>
              <Play className="size-4" /> Start quick tour
            </Button>
            <Button variant={explainPage ? "default" : "outline"} className="w-full justify-start" onClick={toggleExplainPage}>
              <BookOpen className="size-4" /> {explainPage ? "Hide page explanation" : "Explain this page"}
            </Button>
            <div className="rounded-lg border bg-muted/30 p-3">
              <div className="flex items-center justify-between gap-2">
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Metric glossary</p>
                <Badge variant="outline" className="text-[10px]">{glossary.length}</Badge>
              </div>
              <div className="mt-2 space-y-2 max-h-72 overflow-auto pr-1">
                {glossary.map((item) => (
                  <div key={item.id} className="rounded-md bg-background/80 p-2 border">
                    <p className="text-sm font-semibold">{item.title}</p>
                    <p className="text-xs text-muted-foreground mt-1">{item.meaning}</p>
                    <p className="text-[11px] mt-1"><span className="font-semibold">Basis:</span> {item.basis}</p>
                    <p className="text-[11px]"><span className="font-semibold">Next:</span> {item.next}</p>
                  </div>
                ))}
              </div>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
