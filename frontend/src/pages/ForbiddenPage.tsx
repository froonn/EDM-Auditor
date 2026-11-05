import { ShieldAlert } from "lucide-react";

import { useI18n } from "@/i18n";

import { MessagePage } from "./MessagePage";

export function ForbiddenPage() {
  const { t } = useI18n();
  return (
    <MessagePage icon={ShieldAlert} title={t("page.forbidden.title")} description={t("page.forbidden.description")} />
  );
}
