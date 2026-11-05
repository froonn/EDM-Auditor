import { TriangleAlert } from "lucide-react";

import { useI18n } from "@/i18n";

import { MessagePage } from "./MessagePage";

/** Shown when a screen throws while rendering, instead of a blank page. */
export function RouteErrorPage() {
  const { t } = useI18n();
  return <MessagePage icon={TriangleAlert} title={t("page.crash.title")} description={t("page.crash.description")} />;
}
