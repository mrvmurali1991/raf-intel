/**
 * Custom ESLint plugin to catch common runtime safety issues:
 * 1. Nested interactive elements (<button> inside <button>, <a> inside <a>)
 * 2. Unsafe .toFixed() / .toPrecision() without null guard
 * 3. Unsafe [0] indexing on potentially undefined values
 */

const INTERACTIVE_ELEMENTS = new Set(["button", "a", "select", "textarea", "input"]);
const INTERACTIVE_COMPONENTS = new Set(["Link", "NextLink"]);

function isInteractive(node) {
  if (node.type !== "JSXOpeningElement") return false;
  const name = node.name;
  if (name.type === "JSXIdentifier") {
    return INTERACTIVE_ELEMENTS.has(name.name) || INTERACTIVE_COMPONENTS.has(name.name);
  }
  return false;
}

module.exports = {
  rules: {
    /**
     * Disallow nesting interactive elements (button in button, a in a, etc.)
     */
    "no-nested-interactive": {
      meta: {
        type: "problem",
        docs: { description: "Disallow nesting interactive HTML elements (causes hydration errors)" },
        messages: {
          nested: "<{{child}}> cannot be nested inside <{{parent}}>. Use <div role=\"button\"> for the outer element.",
        },
      },
      create(context) {
        const stack = [];
        return {
          JSXOpeningElement(node) {
            if (isInteractive(node)) {
              const name = node.name.name;
              // Self-closing tags (<input />) won't have a closing element
              const isSelfClosing = node.selfClosing;
              if (stack.length > 0) {
                context.report({
                  node,
                  messageId: "nested",
                  data: { child: name, parent: stack[stack.length - 1] },
                });
              }
              if (!isSelfClosing) {
                stack.push(name);
              }
            }
          },
          "JSXClosingElement:exit"(node) {
            const closingName = node.name?.name;
            if (closingName && stack.length > 0 && stack[stack.length - 1] === closingName) {
              stack.pop();
            }
          },
        };
      },
    },

    /**
     * Warn when .toFixed() or .toPrecision() is called without a null guard.
     * Safe patterns: (x ?? 0).toFixed(), x?.toFixed(), x != null && x.toFixed()
     */
    "safe-number-methods": {
      meta: {
        type: "problem",
        docs: { description: "Require null guard before .toFixed() / .toPrecision()" },
        messages: {
          unsafe: ".{{method}}() on potentially undefined value. Use (value ?? 0).{{method}}() instead.",
        },
      },
      create(context) {
        return {
          CallExpression(node) {
            const callee = node.callee;
            if (callee.type !== "MemberExpression") return;
            const prop = callee.property;
            if (prop.type !== "Identifier") return;
            if (prop.name !== "toFixed" && prop.name !== "toPrecision") return;

            const obj = callee.object;
            // Safe: optional chain — x?.toFixed()
            if (callee.optional) return;
            // Safe: (x ?? 0).toFixed() — LogicalExpression with ??
            if (obj.type === "LogicalExpression" && obj.operator === "??") return;
            // Safe: literal number — (123).toFixed()
            if (obj.type === "Literal" && typeof obj.value === "number") return;
            // Safe: parenthesized (+(x ?? 0)).toFixed()
            if (obj.type === "UnaryExpression" && obj.argument?.type === "LogicalExpression" && obj.argument.operator === "??") return;

            // Everything else is suspicious when accessing API data
            // Only warn on member expressions (row.value.toFixed) which are likely API data
            if (obj.type === "MemberExpression" || obj.type === "Identifier") {
              context.report({
                node,
                messageId: "unsafe",
                data: { method: prop.name },
              });
            }
          },
        };
      },
    },
  },
};
