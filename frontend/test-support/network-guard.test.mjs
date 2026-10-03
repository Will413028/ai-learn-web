import assert from "node:assert/strict";
import net from "node:net";
import dns from "node:dns";
import "./network-guard.mjs";

assert.throws(() => net.connect({ host: "example.invalid", port: 443 }), /External network/);
assert.throws(() => dns.lookup("example.invalid", () => {}), /External network/);
console.log("Node external network guard passed");
