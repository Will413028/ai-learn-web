export function guardRoute(route, blockedURLs) {
  const url = new URL(route.request().url());
  if (url.origin !== "http://127.0.0.1:3100") {
    blockedURLs.push(url.href);
    return route.abort("blockedbyclient");
  }
  return route.continue();
}
