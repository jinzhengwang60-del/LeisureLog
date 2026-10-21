const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const source = fs.readFileSync(path.join(__dirname, "../../src/leisurelog/api/static/category-labels.js"), "utf8");
const labels = import("data:text/javascript;base64," + Buffer.from(source).toString("base64"));

test("legacy movie records have a Chinese label without duplicating correction choices", async () => {
  const {categoryName, categoryLabels} = await labels;
  assert.equal(categoryName("movie"), categoryName("film"));
  assert.equal(categoryName("movie"), "影视");
  assert.equal(Object.hasOwn(categoryLabels, "movie"), false);
});

test("custom category IDs remain readable even when they match Object properties", async () => {
  const {categoryName} = await labels;
  for (const value of ["我的课程", "custom_activity", "constructor", "__proto__", "toString"]) {
    assert.equal(categoryName(value), value);
  }
});
