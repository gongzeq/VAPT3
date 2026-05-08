import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { BorderBeam } from "../border-beam";

describe("magicui/BorderBeam", () => {
  it("renders the masked beam wrapper with default props", () => {
    const { container } = render(<BorderBeam />);
    expect(container.firstChild).toMatchSnapshot();
  });
});
