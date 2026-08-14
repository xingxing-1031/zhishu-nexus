import assert from "node:assert/strict";
import { readMigratedStorage } from "../src/storageMigration.ts";

function memoryStorage(initial = {}) {
  const values = new Map(Object.entries(initial));
  return {
    getItem(key) {
      return values.has(key) ? values.get(key) : null;
    },
    setItem(key, value) {
      values.set(key, value);
    },
  };
}

const legacyOnly = memoryStorage({ old: "legacy" });
assert.equal(readMigratedStorage(legacyOnly, "new", "old"), "legacy");
assert.equal(legacyOnly.getItem("new"), "legacy");
assert.equal(legacyOnly.getItem("old"), "legacy");

const currentAndLegacy = memoryStorage({ old: "legacy", new: "current" });
assert.equal(readMigratedStorage(currentAndLegacy, "new", "old"), "current");
assert.equal(currentAndLegacy.getItem("new"), "current");
assert.equal(currentAndLegacy.getItem("old"), "legacy");

const empty = memoryStorage();
assert.equal(readMigratedStorage(empty, "new", "old"), null);
assert.equal(readMigratedStorage(undefined, "new", "old"), null);

console.log("storage migration smoke passed");
