import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ProgressBar } from "../progress-bar";

describe("tremor/ProgressBar", () => {
  it("renders a default-variant track at 50%", () => {
    const { container } = render(<ProgressBar value={50} />);
    expect(container.firstChild).toMatchSnapshot();
  });

  it("renders a success variant with a label", () => {
    const { container } = render(
      <ProgressBar value={80} variant="success" label="80% complete" />,
    );
    expect(container.firstChild).toMatchSnapshot();
  });
});
