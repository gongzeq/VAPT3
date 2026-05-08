import { render } from "@testing-library/react";
import * as React from "react";
import { describe, expect, it } from "vitest";

import { AnimatedBeam } from "../animated-beam";

function Harness() {
  const containerRef = React.useRef<HTMLDivElement>(null);
  const fromRef = React.useRef<HTMLDivElement>(null);
  const toRef = React.useRef<HTMLDivElement>(null);

  return (
    <div ref={containerRef} style={{ position: "relative", width: 200, height: 100 }}>
      <div ref={fromRef} />
      <div ref={toRef} />
      <AnimatedBeam
        containerRef={containerRef}
        fromRef={fromRef}
        toRef={toRef}
      />
    </div>
  );
}

describe("magicui/AnimatedBeam", () => {
  it("renders the SVG beam shell with token gradient stops", () => {
    const { container } = render(<Harness />);
    // The beam mounts asynchronously after layout. Snapshot the SVG element
    // it renders (the `<svg>` with `pointer-events-none`).
    const svg = container.querySelector("svg");
    expect(svg).toMatchSnapshot();
  });
});
