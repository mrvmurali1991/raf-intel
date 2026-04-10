import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";
import safetyPlugin from "./eslint-plugin-safety/index.js";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    files: ["**/*.ts", "**/*.tsx"],
    plugins: {
      safety: safetyPlugin,
    },
    rules: {
      "@typescript-eslint/no-explicit-any": 0,
      "@typescript-eslint/no-unused-vars": 0,
      "@typescript-eslint/no-unused-expressions": 0,
      "@next/next/no-img-element": 0,
      "react/no-unescaped-entities": 0,
      "react-hooks/exhaustive-deps": 0,
      "safety/no-nested-interactive": "error",
      "safety/safe-number-methods": "warn"
    }
  },
  globalIgnores([
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
  ]),
]);

export default eslintConfig;
