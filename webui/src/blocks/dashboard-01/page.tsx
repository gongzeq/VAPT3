// Source: shadcn block `dashboard-01` (https://ui.shadcn.com/blocks#dashboard-01)
// Adapted 2026-05-07 for trellis task 05-07-ocean-tech-frontend (PR2).
//
// Adaptation rationale (deviation from a verbatim shadcn copy):
//   The upstream `dashboard-01` ships with an interactive `DataTable`
//   (drag-sort, pagination, column toggles via `@tanstack/react-table` +
//   the four `@dnd-kit/*` packages + `zod` + `sonner`) and a custom
//   `ChartAreaInteractive` that wraps shadcn's `chart` block. None of
//   those deps are in our tree and bringing them in doubles PR2's
//   bundle delta and adds 7+ runtime packages — out of scope.
//
//   Instead, this scaffold preserves the LAYOUT pattern from upstream
//   (sidebar + site header + section cards row + chart strip + data
//   table strip) using primitives we already have:
//     - `AppSidebar` from `../sidebar-07/components/app-sidebar`
//     - `SectionCards` (this directory) — reuses our shadcn `Card` /
//       `Badge` and `lucide-react` icons we already ship.
//     - Tremor `AreaChart` (PR2 copy) instead of upstream's
//       `ChartAreaInteractive`.
//     - A simple `<table>` placeholder where `DataTable` was; PR4 swaps
//       it in when `@tanstack/react-table` lands as a deliberate
//       addition.

import { AppSidebar } from "../sidebar-07/components/app-sidebar"
import { ChartAreaInteractive } from "./components/chart-area-interactive"
import { DataTablePlaceholder } from "./components/data-table-placeholder"
import { SectionCards } from "./components/section-cards"
import { SiteHeader } from "./components/site-header"
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar"

export default function Page() {
  return (
    <SidebarProvider>
      <AppSidebar />
      <SidebarInset>
        <SiteHeader />
        <div className="flex flex-1 flex-col">
          <div className="flex flex-1 flex-col gap-2">
            <div className="flex flex-col gap-4 py-4 md:gap-6 md:py-6">
              <SectionCards />
              <div className="px-4 lg:px-6">
                <ChartAreaInteractive />
              </div>
              <DataTablePlaceholder />
            </div>
          </div>
        </div>
      </SidebarInset>
    </SidebarProvider>
  )
}
