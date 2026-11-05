import { memo, useMemo } from "react";

import { useI18n } from "@/i18n";
import { cn } from "@/lib/utils";

import type { Segment } from "./highlight";
import { MARK_CLASSES } from "./severityStyles";
import { withParagraphBreaks } from "./textFormat";

interface DocumentTextProps {
  segments: Segment[];
  selectedIds: ReadonlySet<number>;
  onSelect: (findingIds: number[]) => void;
  /** Receives the first highlighted piece of each finding, for scrolling to it. */
  registerMark: (findingId: number, element: HTMLElement | null) => void;
}

/** The document text. It is rendered as React text, never as HTML. */
export const DocumentText = memo(function DocumentText({
  segments,
  selectedIds,
  onSelect,
  registerMark,
}: DocumentTextProps) {
  const { t } = useI18n();
  const firstSegment = useMemo(() => {
    const first = new Map<number, number>();
    segments.forEach((segment, index) => {
      for (const id of segment.findingIds) if (!first.has(id)) first.set(id, index);
    });
    return first;
  }, [segments]);

  return (
    <div className="text-[15px] leading-6 break-words whitespace-pre-wrap">
      {segments.map((segment, index) => {
        if (!segment.severity) return <span key={segment.start}>{withParagraphBreaks(segment.text)}</span>;
        const selected = segment.findingIds.some((id) => selectedIds.has(id));
        const owners = segment.findingIds.filter((id) => firstSegment.get(id) === index);
        return (
          <mark
            key={segment.start}
            ref={(element) => {
              for (const id of owners) registerMark(id, element);
            }}
            role="button"
            tabIndex={0}
            aria-pressed={selected}
            aria-label={t("audit.markLabel", { severity: t(`severity.${segment.severity}`) })}
            data-finding-ids={segment.findingIds.join(" ")}
            onClick={() => onSelect(segment.findingIds)}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                onSelect(segment.findingIds);
              }
            }}
            className={cn(
              "cursor-pointer rounded-sm border-b-2 text-foreground outline-none",
              "focus-visible:ring-2 focus-visible:ring-ring",
              MARK_CLASSES[segment.severity],
              selected && "ring-2 ring-ring",
            )}
          >
            {withParagraphBreaks(segment.text)}
          </mark>
        );
      })}
    </div>
  );
});
