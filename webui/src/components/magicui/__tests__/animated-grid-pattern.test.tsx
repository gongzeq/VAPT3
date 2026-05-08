import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AnimatedGridPattern } from "../animated-grid-pattern";

describe("magicui/AnimatedGridPattern", () => {
  it("renders the SVG grid pattern with default props", () => {
    const { container } = render(<AnimatedGridPattern />);
    expect(container.firstChild).toMatchSnapshot();
  });
});
