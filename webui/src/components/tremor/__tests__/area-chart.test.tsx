import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AreaChart } from "../area-chart";

describe("tremor/AreaChart", () => {
  it("renders the wrapper div for a small fixture", () => {
    const { container } = render(
      <AreaChart
        data={[
          { month: "Jan", findings: 3 },
          { month: "Feb", findings: 7 },
          { month: "Mar", findings: 5 },
        ]}
        index="month"
        categories={["findings"]}
        colors={["primary"]}
      />,
    );
    expect(container.firstChild).toMatchSnapshot();
  });
});
