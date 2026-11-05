import type { ClassificationStatus, DocumentStatus, LegalActStatus, Severity } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { useI18n } from "@/i18n";
import { cn } from "@/lib/utils";

const SEVERITY_CLASSES: Record<Severity, string> = {
  critical: "border-severity-critical-border bg-severity-critical-bg text-severity-critical",
  high: "border-severity-high-border bg-severity-high-bg text-severity-high",
  medium: "border-severity-medium-border bg-severity-medium-bg text-severity-medium",
  low: "border-severity-low-border bg-severity-low-bg text-severity-low",
};

/** Severity is written out as text, not shown by color alone. */
export function SeverityBadge({ severity }: { severity: string }) {
  const { t } = useI18n();
  if (!(severity in SEVERITY_CLASSES)) return <Badge className={TONE_CLASSES.neutral}>{severity}</Badge>;
  const known = severity as Severity;
  return <Badge className={SEVERITY_CLASSES[known]}>{t(`severity.${known}`)}</Badge>;
}

type Tone = "neutral" | "progress" | "success" | "warning" | "danger";

const TONE_CLASSES: Record<Tone, string> = {
  neutral: "bg-muted text-muted-foreground",
  progress: "border-primary/30 bg-accent text-primary",
  success: "border-success/30 bg-success-muted text-success",
  warning: "border-warning/40 bg-warning-muted text-warning",
  danger: "border-destructive/30 bg-danger-muted text-destructive",
};

const STATUS_TONES = {
  document: {
    uploaded: "neutral",
    processing: "progress",
    audited: "success",
    error: "danger",
  } satisfies Record<DocumentStatus, Tone>,
  classification: {
    pending: "neutral",
    classified: "success",
    needs_review: "warning",
    unknown: "warning",
  } satisfies Record<ClassificationStatus, Tone>,
  legalAct: {
    uploaded: "neutral",
    processing: "progress",
    completed: "success",
    partial: "warning",
    failed: "danger",
    needs_reprocessing: "warning",
  } satisfies Record<LegalActStatus, Tone>,
};

export type StatusKind = keyof typeof STATUS_TONES;

export function StatusBadge({ kind, status }: { kind: StatusKind; status: string }) {
  const { tOptional } = useI18n();
  const tone: Tone = (STATUS_TONES[kind] as Record<string, Tone>)[status] ?? "neutral";
  // An unknown status from a newer backend is shown as is instead of being hidden.
  return <Badge className={cn(TONE_CLASSES[tone])}>{tOptional(`status.${kind}.${status}`) ?? status}</Badge>;
}
