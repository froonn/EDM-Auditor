import { ChevronLeft, ChevronRight } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { useI18n } from "@/i18n";
import { cn } from "@/lib/utils";

export interface Column<T> {
  key: string;
  header: ReactNode;
  cell: (row: T) => ReactNode;
  className?: string;
}

export interface Pagination {
  limit: number;
  offset: number;
  total: number;
  onOffsetChange: (offset: number) => void;
}

interface DataTableProps<T> {
  columns: Column<T>[];
  rows: T[] | undefined;
  rowKey: (row: T) => string | number;
  isLoading?: boolean;
  emptyText?: string;
  pagination?: Pagination;
  onRowClick?: (row: T) => void;
}

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  isLoading = false,
  emptyText,
  pagination,
  onRowClick,
}: DataTableProps<T>) {
  const { t, formatNumber } = useI18n();
  const placeholder = isLoading && !rows ? t("table.loading") : (emptyText ?? t("table.empty"));

  return (
    <div className="overflow-hidden rounded-lg border bg-card">
      <table className="w-full text-sm" aria-busy={isLoading}>
        <thead className="bg-muted text-left text-muted-foreground">
          <tr>
            {columns.map((column) => (
              <th key={column.key} scope="col" className={cn("px-4 py-2 font-medium", column.className)}>
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows && rows.length > 0 ? (
            rows.map((row) => (
              <tr
                key={rowKey(row)}
                className={cn("border-t", onRowClick && "cursor-pointer hover:bg-accent")}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
              >
                {columns.map((column) => (
                  <td key={column.key} className={cn("px-4 py-2 align-top", column.className)}>
                    {column.cell(row)}
                  </td>
                ))}
              </tr>
            ))
          ) : (
            <tr className="border-t">
              <td colSpan={columns.length} className="px-4 py-6 text-center text-muted-foreground">
                {placeholder}
              </td>
            </tr>
          )}
        </tbody>
      </table>
      {pagination && pagination.total > 0 && <PaginationBar {...pagination} formatNumber={formatNumber} />}
    </div>
  );
}

function PaginationBar({
  limit,
  offset,
  total,
  onOffsetChange,
  formatNumber,
}: Pagination & { formatNumber: (value: number) => string }) {
  const { t } = useI18n();
  const from = Math.min(offset + 1, total);
  const to = Math.min(offset + limit, total);
  return (
    <div className="flex items-center justify-end gap-2 border-t px-4 py-2 text-sm text-muted-foreground">
      <span>{t("table.range", { from: formatNumber(from), to: formatNumber(to), total: formatNumber(total) })}</span>
      <Button
        variant="ghost"
        size="icon"
        aria-label={t("table.previous")}
        disabled={offset === 0}
        onClick={() => onOffsetChange(Math.max(0, offset - limit))}
      >
        <ChevronLeft aria-hidden />
      </Button>
      <Button
        variant="ghost"
        size="icon"
        aria-label={t("table.next")}
        disabled={offset + limit >= total}
        onClick={() => onOffsetChange(offset + limit)}
      >
        <ChevronRight aria-hidden />
      </Button>
    </div>
  );
}
