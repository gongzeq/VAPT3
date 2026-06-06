/** @type {import("eslint").Linter.Config} */
module.exports = {
  root: true,
  parser: "@typescript-eslint/parser",
  parserOptions: {
    ecmaVersion: "latest",
    sourceType: "module",
    ecmaFeatures: { jsx: true },
  },
  plugins: ["@typescript-eslint", "react-hooks"],
  extends: [
    "eslint:recommended",
    "plugin:@typescript-eslint/recommended",
  ],
  env: {
    browser: true,
    es2022: true,
    node: true,
  },
  rules: {
    // ── console ──
    "no-console": ["warn", { allow: ["warn", "error"] }],

    // ── TypeScript ──
    "@typescript-eslint/no-non-null-assertion": "warn",
    "@typescript-eslint/no-explicit-any": "warn",
    "@typescript-eslint/no-unused-vars": [
      "warn",
      { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
    ],

    // ── React Hooks ──
    "react-hooks/rules-of-hooks": "error",
    "react-hooks/exhaustive-deps": "warn",

    // ── Misc ──
    "no-debugger": "error",
    "prefer-const": "warn",
    "@typescript-eslint/no-empty-function": "off",
    "@typescript-eslint/no-empty-interface": "off",
  },
  ignorePatterns: ["dist/", "node_modules/", "*.js", "*.cjs"],
};
