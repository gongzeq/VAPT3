const tsParser = require("@typescript-eslint/parser");
const tsPlugin = require("@typescript-eslint/eslint-plugin");
const reactHooks = require("eslint-plugin-react-hooks");

const readonly = "readonly";

module.exports = [
  {
    ignores: ["dist/**", "node_modules/**", "*.js", "*.cjs"],
  },
  {
    files: ["src/**/*.{ts,tsx}"],
    languageOptions: {
      parser: tsParser,
      parserOptions: {
        ecmaVersion: "latest",
        sourceType: "module",
        ecmaFeatures: { jsx: true },
      },
      globals: {
        AbortController: readonly,
        Blob: readonly,
        clearInterval: readonly,
        clearTimeout: readonly,
        console: readonly,
        document: readonly,
        Event: readonly,
        File: readonly,
        FormData: readonly,
        HTMLElement: readonly,
        localStorage: readonly,
        navigator: readonly,
        process: readonly,
        Response: readonly,
        setInterval: readonly,
        setTimeout: readonly,
        URL: readonly,
        URLSearchParams: readonly,
        window: readonly,
      },
    },
    plugins: {
      "@typescript-eslint": tsPlugin,
      "react-hooks": reactHooks,
    },
    rules: {
      ...tsPlugin.configs.recommended.rules,
      "no-console": ["warn", { allow: ["warn", "error"] }],
      "no-debugger": "error",
      "prefer-const": "warn",
      "@typescript-eslint/no-empty-function": "off",
      "@typescript-eslint/no-empty-interface": "off",
      "@typescript-eslint/no-explicit-any": "warn",
      "@typescript-eslint/no-non-null-assertion": "warn",
      "@typescript-eslint/no-unused-vars": [
        "warn",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
      "react-hooks/exhaustive-deps": "warn",
      "react-hooks/rules-of-hooks": "error",
    },
  },
];
