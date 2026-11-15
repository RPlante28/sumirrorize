import { lookup } from "node:dns/promises";
import { createServer } from "node:http";
import { BlockList, connect, isIP } from "node:net";
import type { AddressInfo } from "node:net";

/*
 * The sign-in browser is a real browser running on our server, steered by whoever is signing
 * in. Left alone it could be pointed at things only the server can reach: the database, the
 * other services, anything else on the machine's networks. So all of its traffic goes through
 * this small proxy, which only connects to public internet addresses, over HTTPS.
 *
 * The check is made on the address actually connected to, after looking the name up, so a
 * public-looking name that points at a private address is refused as well.
 */

const HTTPS_PORT = 443;

// Addresses that aren't the public internet: this machine, private and Docker networks,
// link-local (which includes cloud metadata services), and other reserved ranges.
const notPublic = new BlockList();
for (const [network, prefix] of [
  ["0.0.0.0", 8], ["10.0.0.0", 8], ["100.64.0.0", 10], ["127.0.0.0", 8], ["169.254.0.0", 16],
  ["172.16.0.0", 12], ["192.0.0.0", 24], ["192.168.0.0", 16], ["198.18.0.0", 15], ["224.0.0.0", 3],
] as const) {
  notPublic.addSubnet(network, prefix, "ipv4");
}
for (const [network, prefix] of [
  ["::", 127], ["64:ff9b::", 96], ["fc00::", 7], ["fe80::", 10], ["ff00::", 8],
] as const) {
  notPublic.addSubnet(network, prefix, "ipv6");
}

export function isPublicAddress(address: string): boolean {
  const mapped = address.match(/^::ffff:(\d+\.\d+\.\d+\.\d+)$/i)?.[1]; // an IPv4 address written as IPv6
  if (mapped) return !notPublic.check(mapped, "ipv4");
  const family = isIP(address);
  return family !== 0 && !notPublic.check(address, family === 4 ? "ipv4" : "ipv6");
}

/** Splits "host:443" or "[::1]:443". */
function hostAndPort(target: string): { host: string; port: number } | null {
  const match = target.match(/^\[?([^\]]+?)\]?:(\d+)$/);
  return match ? { host: match[1], port: Number(match[2]) } : null;
}

/** The public address to connect to for `host`, or null if it has none. */
async function publicAddress(host: string): Promise<string | null> {
  const addresses = isIP(host) ? [{ address: host }] : await lookup(host, { all: true }).catch(() => []);
  // If a name has any non-public address, refuse it outright rather than pick around it.
  if (addresses.length === 0 || !addresses.every((a) => isPublicAddress(a.address))) return null;
  return addresses[0].address;
}

/** Starts the proxy on this machine only and returns its address for Chromium, e.g. "http://127.0.0.1:41873". */
export async function startEgressProxy(): Promise<string> {
  // Plain http:// pages come here as ordinary requests. Nothing a sign-in needs is plain HTTP.
  const server = createServer((_request, response) => {
    response.writeHead(403, { "Content-Type": "text/plain" }).end("The sign-in browser only opens HTTPS pages.");
  });

  // HTTPS pages come as CONNECT requests: "open me a connection to host:443".
  server.on("connect", (request, client) => {
    void (async () => {
      const target = hostAndPort(request.url ?? "");
      const address = target?.port === HTTPS_PORT ? await publicAddress(target.host) : null;
      if (!target || !address) {
        console.error(`[login] Kept the sign-in browser from reaching ${request.url}`);
        client.end("HTTP/1.1 403 Forbidden\r\n\r\n");
        return;
      }
      const upstream = connect(target.port, address, () => {
        client.write("HTTP/1.1 200 Connection Established\r\n\r\n");
        upstream.pipe(client);
        client.pipe(upstream);
      });
      upstream.on("error", () => client.destroy());
      client.on("error", () => upstream.destroy());
    })();
  });

  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  server.unref();
  return `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
}
