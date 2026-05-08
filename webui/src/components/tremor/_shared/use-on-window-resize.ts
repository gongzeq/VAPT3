// Tremor Raw window-resize hook — copied 2026-05-07 from
// https://github.com/tremorlabs/tremor/blob/main/src/hooks/useOnWindowResize.ts
// for trellis task 05-07-ocean-tech-frontend (PR2).

import * as React from "react";

export const useOnWindowResize = (handler: () => void) => {
  React.useEffect(() => {
    const handleResize = () => {
      handler();
    };
    handleResize();
    window.addEventListener("resize", handleResize);

    return () => window.removeEventListener("resize", handleResize);
  }, [handler]);
};
