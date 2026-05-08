import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { BarChart } from "../bar-chart";

describe("tremor/BarChart", () => {
  it("renders the wrapper div for a small risk-by-asset fixture", () => {
    const { container } = render(
      <BarChart
        data={[
          { asset: "host-a", risk: 9 },
          { asset: "host-b", risk: 5 },
          { asset: "host-c", risk: 2 },
        ]}
        index="asset"
        categories={["risk"]}
        colors={["primary"]}
      />,
    );
    expect(container.firstChild).toMatchSnapshot();
  });
});
