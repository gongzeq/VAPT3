import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ShineBorder } from "../shine-border";

describe("magicui/ShineBorder", () => {
  it("renders the masked overlay with default props", () => {
    const { container } = render(<ShineBorder />);
    expect(container.firstChild).toMatchSnapshot();
  });
});
