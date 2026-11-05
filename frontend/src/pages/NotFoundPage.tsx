import { FileSearch } from "lucide-react";

import { useI18n } from "@/i18n";

import { MessagePage } from "./MessagePage";

export function NotFoundPage() {
  const { t } = useI18n();
  return <MessagePage icon={FileSearch} title={t("page.notFound.title")} description={t("page.notFound.description")} />;
}
