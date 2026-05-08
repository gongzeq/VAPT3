import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Tracker } from "../tracker";

describe("tremor/Tracker", () => {
  it("renders the kill-chain phase row", () => {
    const { container } = render(
      <Tracker
        data={[
          { color: "bg-success", tooltip: "recon" },
          { color: "bg-success", tooltip: "scan" },
          { color: "bg-warning", tooltip: "exploit" },
          { tooltip: "post" },
        ]}
      />,
    );
    expect(container.firstChild).toMatchSnapshot();
  });
});
