import net from "node:net";
import dns from "node:dns";

export function checkHost(host) {
  if (!["localhost", "127.0.0.1", "::1", "[::1]"].includes(host)) {
    throw new Error("External network is blocked in fake tests");
  }
}

const originalConnect = net.Socket.prototype.connect;
net.Socket.prototype.connect = function (...args) {
  const first = Array.isArray(args[0]) ? args[0][0] : args[0];
  if (first && typeof first === "object") {
    if (first.path) throw new Error("Non-TCP sockets are blocked in fake tests");
    checkHost(first.host ?? "localhost");
  } else if (typeof first === "number") {
    checkHost(typeof args[1] === "string" ? args[1] : "localhost");
  } else {
    throw new Error("Unsupported socket connection in fake tests");
  }
  return originalConnect.apply(this, args);
};
const originalLookup = dns.lookup;
dns.lookup = function (host, ...args) {
  checkHost(host);
  return originalLookup.call(this, host, ...args);
};
