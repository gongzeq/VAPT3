import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Marquee } from "../marquee";

describe("magicui/Marquee", () => {
  it("renders the marquee with default repeat", () => {
    const { container } = render(
      <Marquee>
        <span>tick</span>
      </Marquee>,
    );
    expect(container.firstChild).toMatchSnapshot();
  });
});
