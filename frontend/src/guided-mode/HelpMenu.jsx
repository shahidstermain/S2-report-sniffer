import { useMemo, useState } from "react";
import { BookOpen, HelpCircle, Play } from "lucide-react";
import { useLocation } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { glossaryForPage } from "./metricGlossary";
import { pageKeyFromPath } from "./tourRegistry";
import { useGuidedMode } from "./GuidedModeProvider";

export default function HelpMenu({ compact = false }) {
  const location = useLocation();
  const [open, setOpen] = useState(false);
  const {
    explainPage,
    startTour,
    toggleExplainPage,
  } = useGuidedMode();

  const pageKey = pageKeyFromPath(location.pathname);
  const glossary = useMemo(() => glossaryForPage(pageKey), [pageKey]);

  return (
    <div data-guide-id="guided.help">
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogTrigger asChild>
          <Button
            type="button"
            variant="outline"
            size={compact ? "sm" : "default"}
            aria-label="Open guided mode help"
          >
            <HelpCircle className="size-4" />
            {!compact && "Guided help"}
          </Button>
        </DialogTrigger>
        <DialogContent className="max-h-[calc(100dvh-2rem)] w-[calc(100vw-2rem)] max-w-md grid-rows-[auto_minmax(0,1fr)] gap-0 overflow-hidden p-0">
          <DialogHeader className="border-b px-6 py-5 pr-12">
            <DialogTitle className="text-base">Guided mode</DialogTitle>
            <DialogDescription className="text-xs">
              Learn the app with tours, page explanations, and metric definitions.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 overflow-y-auto px-6 py-5">
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
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
