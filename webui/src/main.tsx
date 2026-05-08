import React from "react";
import ReactDOM from "react-dom/client";

import App from "./App";
import "./globals.css";
import "./i18n";

/**
 * Ocean-tech HUD feature flag — see `.trellis/tasks/05-07-ocean-tech-frontend/
 * prd.md` §Decision 6. Default is ON; set `VITE_SECBOT_HUD=0` at build time
 * to ship a brand-deep-free fallback (the CSS rule in `globals.css` under
 * `[data-ocean-hud="off"]` rebinds brand tokens to primary/secondary so the
 * whole UI remains coherent without the ocean identity layer).
 *
 * Why attribute-on-root and not runtime context: the flag must be settable at
 * Vite build time (no runtime cost, no flicker), and CSS variable overrides
 * don't require re-rendering React. One attribute, one CSS rule — fully
 * reversible.
 */
const hudFlag = import.meta.env.VITE_SECBOT_HUD;
const hudOn = hudFlag === undefined || hudFlag === "" || hudFlag === "1";
document.documentElement.dataset.oceanHud = hudOn ? "on" : "off";

const root = document.getElementById("root");
if (!root) throw new Error("root element missing");

ReactDOM.createRoot(root).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
