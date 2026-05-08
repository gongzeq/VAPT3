import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AnimatedShinyText } from "../animated-shiny-text";

describe("magicui/AnimatedShinyText", () => {
  it("renders the streaming-text shimmer wrapper", () => {
    const { container } = render(
      <AnimatedShinyText>thinking</AnimatedShinyText>,
    );
    expect(container.firstChild).toMatchSnapshot();
  });
});
