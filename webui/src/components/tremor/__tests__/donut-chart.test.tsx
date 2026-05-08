import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DonutChart } from "../donut-chart";

describe("tremor/DonutChart", () => {
  it("renders the responsive donut wrapper for severity distribution", () => {
    const { container } = render(
      <DonutChart
        data={[
          { severity: "Critical", count: 3 },
          { severity: "High", count: 7 },
          { severity: "Medium", count: 12 },
          { severity: "Low", count: 5 },
        ]}
        category="severity"
        value="count"
        colors={["critical", "high", "medium", "low"]}
        showLabel
      />,
    );
    // recharts renders dimension-dependent SVG asynchronously; we snapshot
    // only the wrapper div (`tremor-id` removed in our copy) so the test
    // stays stable in happy-dom (which has no real layout).
    expect(container.firstChild).toMatchSnapshot();
  });
});
