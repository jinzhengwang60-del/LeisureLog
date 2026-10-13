const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const source = fs.readFileSync(path.join(__dirname, "../../src/leisurelog/api/static/activity-context.js"), "utf8");
const helpers = import("data:text/javascript;base64," + Buffer.from(source).toString("base64"));

test("changing one attribution field preserves the other instead of writing a fallback", async () => {
  const {attributionPayload} = await helpers;
  assert.deepEqual(attributionPayload(["a"], "study", "__keep__"), {event_ids: ["a"], purpose: "study"});
  assert.deepEqual(attributionPayload(["a"], "__keep__", "project-1"), {event_ids: ["a"], project_id: "project-1"});
});

test("explicit automatic purpose and unassigned project remain distinct from leaving fields alone", async () => {
  const {attributionPayload} = await helpers;
  assert.deepEqual(attributionPayload(["a"], "__auto__", "none"), {event_ids: ["a"], purpose: null, project_id: null});
  assert.deepEqual(attributionPayload(["a"], "unknown", "__keep__"), {event_ids: ["a"], purpose: "unknown"});
});

test("keyword association carries only the user's chosen pattern and deduplicates selected events", async () => {
  const {attributionPayload} = await helpers;
  assert.deepEqual(attributionPayload(["a", "b", "a"], "__keep__", "p", "title_contains", " LeisureLog "), {
    event_ids: ["a", "b"], project_id: "p", remember_scope: "title_contains", match_text: "LeisureLog",
  });
  assert.equal("match_text" in attributionPayload(["a"], "work", "__keep__", "title", "ignored"), false);
});

test("an empty choice or oversized batch cannot silently submit modifications", async () => {
  const {attributionPayload} = await helpers;
  assert.throws(() => attributionPayload(["a"], "__keep__", "__keep__"), /先选择/);
  assert.throws(() => attributionPayload([], "work", "none"), /1–1000/);
  assert.throws(() => attributionPayload(Array.from({length: 1001}, (_, i) => String(i)), "work", "none"), /1–1000/);
});

test("a stale preview and a conflicting undo provide actionable Chinese messages", async () => {
  const {contextRequest} = await helpers;
  const original = global.fetch;
  try {
    for (const [detail, message] of [
      ["Rule preview is outdated; preview again", /重新预览/],
      ["These decisions changed after this operation; undo newer changes first", /较新的修改/],
    ]) {
      global.fetch = async () => ({ok: false, status: 409, json: async () => ({detail})});
      await assert.rejects(contextRequest("/test"), error => error.status === 409 && message.test(error.message));
    }
  } finally { global.fetch = original; }
});
