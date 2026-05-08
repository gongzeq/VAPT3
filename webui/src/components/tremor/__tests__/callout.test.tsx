import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Callout } from "../callout";

describe("tremor/Callout", () => {
  it("renders a default-variant callout with title", () => {
    const { container } = render(
      <Callout title="Heads up">
        <p>Body content.</p>
      </Callout>,
    );
    expect(container.firstChild).toMatchSnapshot();
  });

  it("renders an error variant", () => {
    const { container } = render(
      <Callout variant="error" title="Critical">
        Something failed.
      </Callout>,
    );
    expect(container.firstChild).toMatchSnapshot();
  });
});
