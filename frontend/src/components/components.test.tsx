import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "@/i18n";

import { SeverityBadge, StatusBadge } from "./badges";
import { ConfirmDialog } from "./ConfirmDialog";
import { DataTable } from "./DataTable";
import { LongOperation } from "./LongOperation";

afterEach(() => vi.useRealTimers());

const wrap = (node: React.ReactNode) => render(<I18nProvider>{node}</I18nProvider>);

describe("badges", () => {
  it("writes severity and status as text", () => {
    wrap(
      <>
        <SeverityBadge severity="critical" />
        <StatusBadge kind="classification" status="needs_review" />
        <StatusBadge kind="document" status="something_new" />
      </>,
    );
    expect(screen.getByText("Критическая")).toHaveClass("bg-severity-critical-bg");
    expect(screen.getByText("Нужно подтвердить тип")).toBeInTheDocument();
    expect(screen.getByText("something_new")).toBeInTheDocument();
  });
});

describe("DataTable", () => {
  it("pages through rows", async () => {
    const onOffsetChange = vi.fn();
    wrap(
      <DataTable
        columns={[{ key: "name", header: "Name", cell: (row: { id: number }) => `row ${row.id}` }]}
        rows={[{ id: 1 }, { id: 2 }]}
        rowKey={(row) => row.id}
        pagination={{ limit: 2, offset: 0, total: 5, onOffsetChange }}
      />,
    );
    expect(screen.getByText("1–2 из 5")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Предыдущая страница" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Следующая страница" }));
    expect(onOffsetChange).toHaveBeenCalledWith(2);
  });

  it("shows the empty text", () => {
    wrap(<DataTable columns={[]} rows={[]} rowKey={() => 0} />);
    expect(screen.getByText("Записей нет")).toBeInTheDocument();
  });
});

describe("LongOperation", () => {
  it("counts elapsed seconds", () => {
    vi.useFakeTimers();
    wrap(<LongOperation label="Идёт аудит" />);
    expect(screen.getByRole("status")).toHaveTextContent("Прошло 0 с");
    act(() => vi.advanceTimersByTime(3000));
    expect(screen.getByRole("status")).toHaveTextContent("Прошло 3 с");
  });
});

describe("ConfirmDialog", () => {
  function Example({ onConfirm }: { onConfirm: () => void }) {
    const [open, setOpen] = useState(true);
    return (
      <ConfirmDialog
        open={open}
        onOpenChange={setOpen}
        title="Удалить документ?"
        description="Отчёты тоже удалятся."
        confirmLabel="Удалить"
        destructive
        onConfirm={onConfirm}
      />
    );
  }

  it("confirms and closes", async () => {
    const onConfirm = vi.fn();
    wrap(<Example onConfirm={onConfirm} />);
    await userEvent.click(screen.getByRole("button", { name: "Удалить" }));
    expect(onConfirm).toHaveBeenCalledOnce();
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("cancels without confirming", async () => {
    const onConfirm = vi.fn();
    wrap(<Example onConfirm={onConfirm} />);
    await userEvent.click(screen.getByRole("button", { name: "Отмена" }));
    expect(onConfirm).not.toHaveBeenCalled();
  });
});
