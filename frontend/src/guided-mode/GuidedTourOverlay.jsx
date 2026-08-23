import { useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { ChevronLeft, ChevronRight, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { useGuidedMode } from "./GuidedModeProvider";

function findTarget(target) {
  if (typeof document === "undefined" || !target) return null;
  return document.querySelector(`[data-guide-id="${target}"]`);
}

export default function GuidedTourOverlay() {
  const { activeTour, setTourIndex, stopTour } = useGuidedMode();
  const location = useLocation();
  const navigate = useNavigate();
  const { reportId: routeReportId } = useParams();
  const reportId = routeReportId || location.pathname.match(/\/report\/([^/]+)/)?.[1] || null;
  const [rect, setRect] = useState(null);
  const cardRef = useRef(null);

  const step = activeTour?.steps?.[activeTour.index] || null;
  const total = activeTour?.steps?.length || 0;
  const tourOpen = Boolean(activeTour);

  useEffect(() => {
    if (!step?.tabId || !reportId) return;
    navigate(`/report/${reportId}/${step.tabId}`);
  }, [step?.tabId, reportId, navigate]);

  useEffect(() => {
    if (!step) return;
    let cancelled = false;
    const update = () => {
      const target = findTarget(step.target);
      if (target) {
        target.scrollIntoView({ block: "center", inline: "nearest", behavior: "smooth" });
        const next = target.getBoundingClientRect();
        if (!cancelled) setRect(next);
      } else if (!cancelled) {
        setRect(null);
      }
    };
    const timer = setTimeout(update, step.tabId ? 350 : 50);
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    return () => {
      cancelled = true;
      clearTimeout(timer);
      window.removeEventListener("resize", update);
      window.removeEventListener("scroll", update, true);
    };
  }, [step]);

  useEffect(() => {
    if (!tourOpen) return undefined;
    const previousFocus = document.activeElement;
    const focusTimer = window.setTimeout(() => cardRef.current?.focus(), 0);
    const handleKeyDown = (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        stopTour(false);
        return;
      }
      if (event.key !== "Tab" || !cardRef.current) return;
      const controls = Array.from(
        cardRef.current.querySelectorAll(
          'button:not([disabled]), [href], input:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ),
      );
      if (controls.length === 0) {
        event.preventDefault();
        cardRef.current.focus();
        return;
      }
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      window.clearTimeout(focusTimer);
      document.removeEventListener("keydown", handleKeyDown);
      if (previousFocus instanceof HTMLElement && previousFocus.isConnected) {
        previousFocus.focus();
      }
    };
  }, [tourOpen, stopTour]);

  const cardStyle = useMemo(() => {
    if (!rect) return { right: 24, bottom: 24 };
    const spaceRight = window.innerWidth - rect.right;
    const preferRight = spaceRight > 380;
    const top = Math.min(Math.max(rect.top, 80), window.innerHeight - 280);
    return preferRight
      ? { top, left: Math.min(rect.right + 18, window.innerWidth - 380) }
      : { top, right: 24 };
  }, [rect]);

  if (!step) return null;

  const pct = Math.round(((activeTour.index + 1) / total) * 100);
  const canGoBack = activeTour.index > 0;
  const isLast = activeTour.index >= total - 1;

  return (
    <div className="fixed inset-0 z-[100] pointer-events-auto">
      <div className="absolute inset-0 bg-black/25" aria-hidden="true" />
      {rect && (
        <div
          className="pointer-events-none absolute rounded-xl border-2 border-primary shadow-[0_0_0_9999px_rgba(0,0,0,0.30)] transition-all"
          style={{
            top: Math.max(8, rect.top - 8),
            left: Math.max(8, rect.left - 8),
            width: rect.width + 16,
            height: rect.height + 16,
          }}
        />
      )}
      <Card
        ref={cardRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="guided-tour-title"
        aria-describedby="guided-tour-description"
        tabIndex={-1}
        className="pointer-events-auto fixed w-[min(360px,calc(100vw-32px))] shadow-2xl"
        style={cardStyle}
      >
        <CardHeader className="pb-2">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-[11px] uppercase tracking-wide text-muted-foreground">
                Guided mode · {activeTour.index + 1}/{total}
              </p>
              <CardTitle id="guided-tour-title" className="text-base">{step.title}</CardTitle>
            </div>
            <Button variant="ghost" size="icon" className="size-8" onClick={() => stopTour(false)} aria-label="Close guided tour">
              <X className="size-4" />
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <p id="guided-tour-description" className="text-sm text-muted-foreground">{step.body}</p>
          <Progress value={pct} className="h-1.5" />
          <div className="flex items-center justify-between gap-2">
            <Button variant="outline" size="sm" disabled={!canGoBack} onClick={() => setTourIndex(activeTour.index - 1)}>
              <ChevronLeft className="size-4" /> Back
            </Button>
            <Button size="sm" onClick={() => isLast ? stopTour(true) : setTourIndex(activeTour.index + 1)}>
              {isLast ? "Finish" : "Next"} {!isLast && <ChevronRight className="size-4" />}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
