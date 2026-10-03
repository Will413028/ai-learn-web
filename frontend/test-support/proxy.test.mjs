import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import vm from "node:vm";
import ts from "typescript";

const configPath = process.argv[2] ?? fileURLToPath(new URL("../next.config.ts", import.meta.url));
const compiled = ts.transpileModule(readFileSync(configPath, "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText;
const exports = {};
vm.runInNewContext(compiled, { exports, process: { env: {} } });
const rules = await exports.default.rewrites();
assert.equal(rules.length, 1);
assert.equal(rules[0].source, "/api/v1/:path*");
assert.equal(rules[0].destination, "http://127.0.0.1:8100/api/v1/:path*");
console.log("Proxy retains /api/v1 path to FastAPI");
