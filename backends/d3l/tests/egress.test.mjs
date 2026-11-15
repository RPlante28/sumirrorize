import assert from "node:assert/strict";
import test from "node:test";
import { isPublicAddress } from "../dist/egress.js";

test("egress blocks local, private, link-local, and mapped private addresses", () => {
  for (const address of ["127.0.0.1", "10.0.0.1", "172.16.0.1", "192.168.0.1", "169.254.169.254", "::1", "::ffff:127.0.0.1"]) {
    assert.equal(isPublicAddress(address), false, address);
  }
  assert.equal(isPublicAddress("8.8.8.8"), true);
  assert.equal(isPublicAddress("2606:4700:4700::1111"), true);
});
