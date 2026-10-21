// Run with: npm test (node's built-in test runner; no extra dependencies).
import assert from "node:assert/strict";
import { test } from "node:test";

import { stanceCounts, stanceDisagreement } from "../lib/stance.mjs";

const src = (stance) => ({ url: `https://example.org/${Math.random()}`, stance });

test("2 supporting and 2 refuting sources show the disagreement line", () => {
  const sources = [src("SUPPORTS"), src("SUPPORTS"), src("REFUTES"), src("REFUTES")];
  assert.equal(stanceDisagreement(sources), "Sources disagree: 2 support, 2 refute.");
});

test("no disagreement line unless both stances are present", () => {
  assert.equal(stanceDisagreement([src("SUPPORTS"), src("NEUTRAL")]), null);
  assert.equal(stanceDisagreement([src("REFUTES")]), null);
  assert.equal(stanceDisagreement([]), null);
  assert.equal(stanceDisagreement(undefined), null);
});

test("counts ignore neutral and unknown stances", () => {
  assert.deepEqual(stanceCounts([src("SUPPORTS"), src("NEUTRAL"), src(undefined), src("REFUTES")]), {
    support: 1,
    refute: 1,
  });
});
