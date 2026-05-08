import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Metric } from "../metric";

describe("tremor/Metric", () => {
  it("renders the KPI text with default styling", () => {
    const { container } = render(<Metric>$ 12,699</Metric>);
    expect(container.firstChild).toMatchSnapshot();
  });

  it("supports a token text-color override", () => {
    const { container } = render(
      <Metric color="text-primary">42</Metric>,
    );
    expect(container.firstChild).toMatchSnapshot();
  });
});
