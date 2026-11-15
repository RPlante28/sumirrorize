import assert from "node:assert/strict";
import test from "node:test";
import { horizontalAlignment, place } from "../static/layout-model.mjs";

const widget = { x: .1, y: .1, w: .3, h: .2 };

test("moving and resizing stay snapped inside the screen", () => {
  assert.deepEqual(place(widget, "move", 2, -2), { x: .7, y: 0, w: .3, h: .2 });
  assert.deepEqual(place(widget, "resize", 2, 2), { x: .1, y: .1, w: .9, h: .9 });
});

test("small widgets cannot collapse", () => {
  assert.deepEqual(place(widget, "resize", -2, -2), { x: .1, y: .1, w: .15, h: .1 });
});

test("content alignment follows the widget's screen position", () => {
  assert.equal(horizontalAlignment({ x: 0, w: .2 }), "left");
  assert.equal(horizontalAlignment({ x: .4, w: .2 }), "center");
  assert.equal(horizontalAlignment({ x: .8, w: .2 }), "right");
});
