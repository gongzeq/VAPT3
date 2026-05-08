import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { NumberTicker } from "../number-ticker";

describe("magicui/NumberTicker", () => {
  it("renders the initial start value before animating into view", () => {
    const { container } = render(<NumberTicker value={1234} />);
    expect(container.firstChild).toMatchSnapshot();
  });
});
