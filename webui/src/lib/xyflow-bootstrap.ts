// xyflow / react-flow ships its CSS as a separate file that must be imported
// once at bootstrap time. The CSS is scoped to xyflow's own classes
// (`.react-flow`, `.react-flow__node`, etc.) so it does NOT collide with our
// Tailwind layer; per-node visual customization happens via the React node
// components (PR4) which read our `hsl(var(--*))` tokens directly.
//
// Doing this once in a side-effect module avoids leaking the import into every
// xyflow-using component and keeps the JS bundle's xyflow chunk in one place.
//
// Source: https://reactflow.dev/learn (canonical setup).
// Added 2026-05-07 for trellis task 05-07-ocean-tech-frontend (PR2) — the
// component that consumes xyflow lands in PR4. PR4 imports this module
// (or `main.tsx` does) once before mounting any `<ReactFlow>` instance.
import "@xyflow/react/dist/style.css";
