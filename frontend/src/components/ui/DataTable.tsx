"use client";

import { type ReactNode, useState } from "react";
import {
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type RowSelectionState,
  type SortingState,
} from "@tanstack/react-table";
import { ArrowDown, ArrowUp, ChevronsUpDown } from "lucide-react";
import { cn } from "@/lib/cn";
import { MicroLabel } from "./MicroLabel";
import { Skeleton } from "./Skeleton";

/**
 * Column-def meta extension. `mobilePriority` controls which columns survive on
 * narrow viewports: columns with priority "low" are hidden below `lg`, "medium"
 * below `sm`. "high" (default) always shows.
 */
export type MobilePriority = "high" | "medium" | "low";

declare module "@tanstack/react-table" {
  // TData/TValue are required by the base interface signature but unused here.
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  interface ColumnMeta<TData, TValue> {
    mobilePriority?: MobilePriority;
    align?: "left" | "right" | "center";
    /** Render header text through MicroLabel voice (default true). */
    mono?: boolean;
  }
}

const PRIORITY_CLASS: Record<MobilePriority, string> = {
  high: "",
  medium: "hidden sm:table-cell",
  low: "hidden lg:table-cell",
};

interface DataTableProps<TData> {
  columns: ColumnDef<TData, unknown>[];
  data: TData[];
  loading?: boolean;
  /** Rendered when data is empty and not loading. */
  emptyState?: ReactNode;
  /** Enable row selection with a floating bulk bar. */
  enableSelection?: boolean;
  /** Actions rendered in the floating bulk bar (receives selected rows). */
  bulkActions?: (selected: TData[]) => ReactNode;
  getRowId?: (row: TData, index: number) => string;
  onRowClick?: (row: TData) => void;
  /** Skeleton row count while loading. */
  skeletonRows?: number;
  className?: string;
}

export function DataTable<TData>({
  columns,
  data,
  loading = false,
  emptyState,
  enableSelection = false,
  bulkActions,
  getRowId,
  onRowClick,
  skeletonRows = 6,
  className,
}: DataTableProps<TData>) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});

  const table = useReactTable({
    data,
    columns,
    state: { sorting, rowSelection },
    onSortingChange: setSorting,
    onRowSelectionChange: setRowSelection,
    enableRowSelection: enableSelection,
    getRowId,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  const selectedRows = table.getSelectedRowModel().rows.map((r) => r.original);
  const showEmpty = !loading && data.length === 0;

  return (
    <div className={cn("relative", className)}>
      <div className="overflow-x-auto lm-scroll">
        <table className="w-full border-collapse text-sm">
          <thead className="sticky top-0 z-10">
            {table.getHeaderGroups().map((hg) => (
              <tr key={hg.id} className="border-b border-border bg-[var(--color-surface-1)]">
                {enableSelection && (
                  <th className="w-9 px-3 py-2.5 text-left">
                    <input
                      type="checkbox"
                      aria-label="Select all rows"
                      className="lm-checkbox"
                      checked={table.getIsAllRowsSelected()}
                      ref={(el) => {
                        if (el) el.indeterminate = table.getIsSomeRowsSelected();
                      }}
                      onChange={table.getToggleAllRowsSelectedHandler()}
                    />
                  </th>
                )}
                {hg.headers.map((header) => {
                  const meta = header.column.columnDef.meta;
                  const canSort = header.column.getCanSort();
                  const sortDir = header.column.getIsSorted();
                  const align = meta?.align ?? "left";
                  return (
                    <th
                      key={header.id}
                      className={cn(
                        "px-3 py-2.5 font-normal",
                        align === "right" && "text-right",
                        align === "center" && "text-center",
                        PRIORITY_CLASS[meta?.mobilePriority ?? "high"],
                      )}
                    >
                      {header.isPlaceholder ? null : (
                        <button
                          type="button"
                          disabled={!canSort}
                          onClick={header.column.getToggleSortingHandler()}
                          className={cn(
                            "inline-flex items-center gap-1",
                            canSort && "cursor-pointer hover:text-ink",
                            align === "right" && "flex-row-reverse",
                          )}
                        >
                          <MicroLabel as="span">
                            {flexRender(header.column.columnDef.header, header.getContext())}
                          </MicroLabel>
                          {canSort &&
                            (sortDir === "asc" ? (
                              <ArrowUp className="size-3 text-accent" />
                            ) : sortDir === "desc" ? (
                              <ArrowDown className="size-3 text-accent" />
                            ) : (
                              <ChevronsUpDown className="size-3 text-muted/50" />
                            ))}
                        </button>
                      )}
                    </th>
                  );
                })}
              </tr>
            ))}
          </thead>

          <tbody>
            {loading ? (
              Array.from({ length: skeletonRows }).map((_, i) => (
                <tr key={i} className="border-b border-border/60">
                  {enableSelection && (
                    <td className="px-3 py-3">
                      <Skeleton className="size-4" />
                    </td>
                  )}
                  {columns.map((_, ci) => (
                    <td
                      key={ci}
                      className={cn("px-3 py-3", PRIORITY_CLASS[columns[ci]?.meta?.mobilePriority ?? "high"])}
                    >
                      <Skeleton className="h-4 w-full max-w-[140px]" />
                    </td>
                  ))}
                </tr>
              ))
            ) : showEmpty ? (
              <tr>
                <td colSpan={columns.length + (enableSelection ? 1 : 0)}>
                  {emptyState ?? (
                    <div className="py-12 text-center text-sm text-muted">No records.</div>
                  )}
                </td>
              </tr>
            ) : (
              table.getRowModel().rows.map((row) => (
                <tr
                  key={row.id}
                  onClick={onRowClick ? () => onRowClick(row.original) : undefined}
                  className={cn(
                    "border-b border-border/60 transition-colors",
                    onRowClick && "cursor-pointer",
                    "hover:bg-[var(--color-panel)]",
                    row.getIsSelected() && "bg-[color-mix(in_srgb,var(--color-accent)_8%,transparent)]",
                  )}
                >
                  {enableSelection && (
                    <td className="px-3 py-3" onClick={(e) => e.stopPropagation()}>
                      <input
                        type="checkbox"
                        aria-label="Select row"
                        className="lm-checkbox"
                        checked={row.getIsSelected()}
                        onChange={row.getToggleSelectedHandler()}
                      />
                    </td>
                  )}
                  {row.getVisibleCells().map((cell) => {
                    const meta = cell.column.columnDef.meta;
                    const align = meta?.align ?? "left";
                    return (
                      <td
                        key={cell.id}
                        className={cn(
                          "px-3 py-3 text-ink/90",
                          align === "right" && "text-right",
                          align === "center" && "text-center",
                          PRIORITY_CLASS[meta?.mobilePriority ?? "high"],
                        )}
                      >
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </td>
                    );
                  })}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {enableSelection && selectedRows.length > 0 && bulkActions && (
        <div className="pointer-events-none sticky bottom-4 z-20 flex justify-center">
          <div className="pointer-events-auto flex items-center gap-3 rounded-full border border-border bg-[var(--color-surface-2)] px-4 py-2 shadow-[0_20px_50px_-20px_rgba(0,0,0,0.9)]">
            <MicroLabel className="text-accent">{selectedRows.length} selected</MicroLabel>
            <span className="h-4 w-px bg-border" />
            {bulkActions(selectedRows)}
            <button
              type="button"
              onClick={() => setRowSelection({})}
              className="font-mono text-[11px] uppercase tracking-wider text-muted hover:text-ink"
            >
              Clear
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
