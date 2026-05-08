import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import Page from "../sidebar-07/page";

describe("blocks/sidebar-07/page", () => {
  it("renders the sidebar shell with the placeholder breadcrumb", () => {
    const { container } = render(<Page />);
    expect(container.firstChild).toMatchSnapshot();
  });
});
