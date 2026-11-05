import { useDocumentTypes } from "@/features/queries";
import { useI18n } from "@/i18n";

interface TypeChecklistProps {
  label: string;
  value: readonly string[];
  onChange: (codes: string[]) => void;
  disabled?: boolean;
}

/**
 * Checkboxes for the active document types, which are the only ones the API accepts. A deactivated
 * type that is still selected is listed too, so that it can be unchecked.
 */
export function TypeChecklist({ label, value, onChange, disabled = false }: TypeChecklistProps) {
  const { t } = useI18n();
  const types = useDocumentTypes();
  const toggle = (code: string) =>
    onChange(value.includes(code) ? value.filter((item) => item !== code) : [...value, code]);
  return (
    <fieldset className="space-y-1 text-sm" disabled={disabled}>
      <legend className="mb-1 font-medium">{label}</legend>
      {types.isPending && <p>{t("table.loading")}</p>}
      <div className="grid grid-cols-2 gap-x-4 gap-y-1">
        {(types.data ?? []).map((type) => (
          <label key={type.code} className="flex items-center gap-2" title={type.description}>
            <input type="checkbox" checked={value.includes(type.code)} onChange={() => toggle(type.code)} />
            {type.name}
          </label>
        ))}
        {value.filter(types.isInactive).map((code) => (
          <label key={code} className="flex items-center gap-2 text-warning" title={t("types.inactiveSelected")}>
            <input type="checkbox" checked onChange={() => toggle(code)} />
            {types.typeName(code)}
          </label>
        ))}
      </div>
    </fieldset>
  );
}
