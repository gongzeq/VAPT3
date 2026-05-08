import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ShimmerButton } from "../shimmer-button";

describe("magicui/ShimmerButton", () => {
  it("renders the button with default token-driven background", () => {
    const { container } = render(<ShimmerButton>Send</ShimmerButton>);
    expect(container.firstChild).toMatchSnapshot();
  });
});
