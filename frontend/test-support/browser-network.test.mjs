import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";

const target = process.argv[2] ? pathToFileURL(process.argv[2]) : new URL("./browser-network.mjs", import.meta.url);
const { guardRoute } = await import(target.href);
const blockedURLs = [];
let abortReason;
guardRoute({
  request: () => ({ url: () => "https://example.invalid/probe" }),
  abort: reason => { abortReason = reason; },
  continue: () => { assert.fail("External request escaped browser guard"); },
}, blockedURLs);
assert.equal(abortReason, "blockedbyclient");
assert.deepEqual(blockedURLs, ["https://example.invalid/probe"]);
let continued = false;
guardRoute({
  request: () => ({ url: () => "http://127.0.0.1:3100/api/v1/health" }),
  abort: () => { assert.fail("Local proxy was blocked"); },
  continue: () => { continued = true; },
}, blockedURLs);
assert.equal(continued, true);
console.log("Browser guard blocks external requests before route.continue");
