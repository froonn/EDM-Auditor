import { FileUp } from "lucide-react";
import { useRef, useState, type DragEvent } from "react";

import { Button } from "@/components/ui/button";
import { useI18n } from "@/i18n";
import { cn } from "@/lib/utils";

interface FileDropZoneProps {
  /** Extensions with a dot, for the file dialog. A dropped file is checked by the caller. */
  accept: readonly string[];
  /** Formats and limits shown under the prompt. */
  hint: string;
  file: File | null;
  onSelect: (file: File | undefined) => void;
  disabled?: boolean;
  /** Accessible name of the hidden file input. */
  inputLabel?: string;
}

/** Drag and drop or a file dialog, for documents and legal acts alike. */
export function FileDropZone({ accept, hint, file, onSelect, disabled = false, inputLabel }: FileDropZoneProps) {
  const { t } = useI18n();
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  const onDrop = (event: DragEvent) => {
    event.preventDefault();
    setDragging(false);
    if (!disabled) onSelect(event.dataTransfer.files[0]);
  };

  return (
    <div
      onDragOver={(event) => {
        event.preventDefault();
        if (!disabled) setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={onDrop}
      className={cn(
        "flex items-center gap-4 rounded-md border-2 border-dashed p-4",
        dragging ? "border-primary bg-accent" : "border-border",
      )}
    >
      <FileUp aria-hidden className="size-8 text-muted-foreground" />
      <div className="flex-1 text-sm">
        <p>{file ? t("upload.selected", { name: file.name }) : t("upload.drop")}</p>
        <p className="text-muted-foreground">{hint}</p>
      </div>
      <Button variant="outline" onClick={() => inputRef.current?.click()} disabled={disabled}>
        {t("upload.choose")}
      </Button>
      <input
        ref={inputRef}
        type="file"
        accept={accept.join(",")}
        aria-label={inputLabel ?? t("upload.choose")}
        className="hidden"
        data-testid="upload-input"
        onChange={(event) => {
          onSelect(event.target.files?.[0]);
          // The same file can be chosen again after an error.
          event.target.value = "";
        }}
      />
    </div>
  );
}
