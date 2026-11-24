import { Check, Copy, Eye, EyeOff, RefreshCw } from "lucide-react";
import { useEffect, useRef, useState, type ComponentProps } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/form";
import { useI18n } from "@/i18n";
import { copyToClipboard } from "@/lib/password";
import { cn } from "@/lib/utils";

type PasswordInputProps = Omit<ComponentProps<"input">, "type">;

/** Standard password input with an integrated show/hide toggle button. */
export function PasswordInput({ className, disabled, ...props }: PasswordInputProps) {
  const { t } = useI18n();
  const [visible, setVisible] = useState(false);

  return (
    <div className="relative">
      <Input
        {...props}
        type={visible ? "text" : "password"}
        disabled={disabled}
        className={cn("pr-10", className)}
      />
      <button
        type="button"
        disabled={disabled}
        aria-label={visible ? t("auth.hidePassword") : t("auth.showPassword")}
        aria-pressed={visible}
        title={visible ? t("auth.hidePassword") : t("auth.showPassword")}
        onClick={() => setVisible((curr) => !curr)}
        className="absolute inset-y-0 right-0 flex w-9 items-center justify-center rounded-r-md text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50"
      >
        {visible ? <EyeOff aria-hidden className="size-4" /> : <Eye aria-hidden className="size-4" />}
      </button>
    </div>
  );
}

interface TemporaryPasswordFieldProps {
  id: string;
  value: string;
  onRegenerate?: () => void;
  disabled?: boolean;
}

/**
 * Read-only auto-generated temporary password field with show/hide,
 * copy-to-clipboard, and optional regenerate controls.
 */
export function TemporaryPasswordField({
  id,
  value,
  onRegenerate,
  disabled,
}: TemporaryPasswordFieldProps) {
  const { t } = useI18n();
  const [visible, setVisible] = useState(false);
  const [copied, setCopied] = useState(false);
  const resetTimerRef = useRef<number | null>(null);

  useEffect(() => {
    setCopied(false);
  }, [value]);

  useEffect(() => {
    return () => {
      if (resetTimerRef.current !== null) {
        window.clearTimeout(resetTimerRef.current);
      }
    };
  }, []);

  async function handleCopy() {
    const ok = await copyToClipboard(value);
    if (!ok) return;
    setCopied(true);
    if (resetTimerRef.current !== null) {
      window.clearTimeout(resetTimerRef.current);
    }
    resetTimerRef.current = window.setTimeout(() => {
      setCopied(false);
      resetTimerRef.current = null;
    }, 2000);
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="relative min-w-52 flex-1">
        <Input
          id={id}
          type={visible ? "text" : "password"}
          value={value}
          readOnly
          aria-readonly="true"
          disabled={disabled}
          autoComplete="off"
          spellCheck={false}
          className="bg-muted/30 pr-10 font-mono"
        />
        <button
          type="button"
          disabled={disabled}
          aria-label={visible ? t("auth.hidePassword") : t("auth.showPassword")}
          aria-pressed={visible}
          title={visible ? t("auth.hidePassword") : t("auth.showPassword")}
          onClick={() => setVisible((curr) => !curr)}
          className="absolute inset-y-0 right-0 flex w-9 items-center justify-center rounded-r-md text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50"
        >
          {visible ? <EyeOff aria-hidden className="size-4" /> : <Eye aria-hidden className="size-4" />}
        </button>
      </div>

      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={disabled}
        onClick={() => void handleCopy()}
      >
        {copied ? <Check aria-hidden className="size-3.5 text-success" /> : <Copy aria-hidden className="size-3.5" />}
        {copied ? t("users.passwordCopied") : t("users.copyPassword")}
      </Button>

      {onRegenerate && (
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={disabled}
          onClick={() => {
            setCopied(false);
            onRegenerate();
          }}
        >
          <RefreshCw aria-hidden className="size-3.5" />
          {t("users.regeneratePassword")}
        </Button>
      )}
    </div>
  );
}
