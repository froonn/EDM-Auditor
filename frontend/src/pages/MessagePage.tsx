import type { LucideIcon } from "lucide-react";
import { Link } from "react-router";

import { Button } from "@/components/ui/button";
import { useI18n } from "@/i18n";

interface MessagePageProps {
  icon: LucideIcon;
  title: string;
  description: string;
}

export function MessagePage({ icon: Icon, title, description }: MessagePageProps) {
  const { t } = useI18n();
  return (
    <div className="mx-auto flex max-w-lg flex-col items-center gap-4 py-16 text-center">
      <Icon aria-hidden className="size-10 text-muted-foreground" />
      <h1 className="text-xl font-semibold">{title}</h1>
      <p className="text-muted-foreground">{description}</p>
      <Button asChild variant="outline">
        <Link to="/">{t("page.backHome")}</Link>
      </Button>
    </div>
  );
}
