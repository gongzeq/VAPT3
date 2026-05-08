import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import Page from "../dashboard-01/page";

describe("blocks/dashboard-01/page", () => {
  it("renders the dashboard scaffold with section cards + chart strip", () => {
    const { container } = render(<Page />);
    expect(container.firstChild).toMatchSnapshot();
  });
});
