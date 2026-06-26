import { Badge } from "@/components/ui/badge";

const SEVERITY_VARIANT = {
  critical: "critical",
  warning: "warning",
  info: "info",
  healthy: "healthy",
};

export function severityBadgeVariant(severity) {
  return SEVERITY_VARIANT[(severity || "").toLowerCase()] || "outline";
}

export function SeverityBadge({ severity, className }) {
  return (
    <Badge variant={severityBadgeVariant(severity)} className={className}>
      {severity}
    </Badge>
  );
}
