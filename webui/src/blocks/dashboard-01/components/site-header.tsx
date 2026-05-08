// Adapted from shadcn block `dashboard-01/components/site-header.tsx`
// (https://ui.shadcn.com/blocks#dashboard-01) — copied 2026-05-07 for
// trellis task 05-07-ocean-tech-frontend (PR2). Verbatim aside from
// import path simplification (`@/components/ui/...` instead of the
// upstream `@/registry/new-york/ui/...`).

import { Separator } from "@/components/ui/separator"
import { SidebarTrigger } from "@/components/ui/sidebar"

export function SiteHeader() {
  return (
    <header className="flex h-12 shrink-0 items-center gap-2 border-b transition-[width,height] ease-linear">
      <div className="flex w-full items-center gap-1 px-4 lg:gap-2 lg:px-6">
        <SidebarTrigger className="-ml-1" />
        <Separator
          orientation="vertical"
          className="mx-2 data-[orientation=vertical]:h-4"
        />
        <h1 className="text-base font-medium">Documents</h1>
      </div>
    </header>
  )
}
