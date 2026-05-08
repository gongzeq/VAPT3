// Trimmed substitute for shadcn block `dashboard-01/components/chart-area-interactive.tsx`
// — see the parent `page.tsx` header for rationale.
//
// The upstream version is a multi-control interactive chart that wraps
// shadcn's `chart` block (which itself wraps recharts) and exposes a
// timeframe toggle. For PR2 we render our Tremor `AreaChart` with a
// small fixture so the dashboard layout has a real chart while remaining
// scope-bounded (no extra deps, no shadcn `chart` registry dependency).
//
// PR4 swaps in a real reports-pipeline data source and may extend this
// component with timeframe controls.

import { Card, CardHeader, CardTitle } from "@/components/ui/card"
import { AreaChart } from "@/components/tremor/area-chart"

const fixtureData = [
  { month: "Jan", findings: 12, regressions: 1 },
  { month: "Feb", findings: 18, regressions: 2 },
  { month: "Mar", findings: 24, regressions: 1 },
  { month: "Apr", findings: 31, regressions: 4 },
  { month: "May", findings: 27, regressions: 3 },
  { month: "Jun", findings: 35, regressions: 2 },
]

export function ChartAreaInteractive() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Findings over time</CardTitle>
      </CardHeader>
      <div className="px-6 pb-6">
        <AreaChart
          data={fixtureData}
          index="month"
          categories={["findings", "regressions"]}
          colors={["primary", "critical"]}
          showLegend
        />
      </div>
    </Card>
  )
}
