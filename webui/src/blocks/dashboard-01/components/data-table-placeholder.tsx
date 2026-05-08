// Trimmed substitute for shadcn block `dashboard-01/components/data-table.tsx`
// — see the parent `page.tsx` header for rationale.
//
// The upstream version is a 700-line `@tanstack/react-table` + `@dnd-kit`
// implementation with drag-sort, column visibility, and pagination.
// PR4 will swap in a real implementation (likely keeping the same
// component name once `@tanstack/react-table` is wired up). For PR2 we
// render a static `<table>` with the same column headers so the layout
// flows correctly and the snapshot test has something to pin.

import {
  Card,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"

const columns = ["Header", "Type", "Status", "Target", "Limit", "Reviewer"]

const fixtureRows: ReadonlyArray<readonly string[]> = [
  ["Cover page", "Cover page", "In Process", "18", "5", "Eddie Lake"],
  ["Table of contents", "Table of contents", "Done", "29", "24", "Eddie Lake"],
  ["Executive summary", "Narrative", "Done", "10", "13", "Eddie Lake"],
  ["Technical approach", "Narrative", "Done", "27", "23", "Jamik Tashpulatov"],
] as const

export function DataTablePlaceholder() {
  return (
    <Card className="mx-4 lg:mx-6">
      <CardHeader>
        <CardTitle className="text-base">Recent reports</CardTitle>
      </CardHeader>
      <div className="overflow-x-auto px-6 pb-6">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-muted-foreground">
              {columns.map((col) => (
                <th
                  key={col}
                  className="px-3 py-2 text-left font-medium tracking-tight"
                  scope="col"
                >
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {fixtureRows.map((row, rowIndex) => (
              <tr key={rowIndex} className="border-b last:border-0">
                {row.map((cell, cellIndex) => (
                  <td
                    key={cellIndex}
                    className="px-3 py-2 align-middle text-foreground"
                  >
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}
