/**
 * Layout shell for the Threat Intel workspace.
 *
 * PRD §7.1: the threat intel module uses a **light** visual style
 * (background ``#F5F7FA``) to distinguish it from the dark VAPT console.
 * This layout applies the light background and renders the Navbar + Outlet.
 */

import { Outlet } from "react-router-dom";
import { Navbar } from "@/components/Navbar";

export function ThreatIntelLayout() {
  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <Navbar />
      <main className="mx-auto max-w-[1600px] px-6 py-6">
        <Outlet />
      </main>
    </div>
  );
}

export default ThreatIntelLayout;
