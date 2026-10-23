// Run with: npm test
import assert from "node:assert/strict";
import { test } from "node:test";

import { escapeSuspiciousCharacters } from "../lib/shieldSecurity.mjs";

test("escapes zero-width spaces to [U+200B]", () => {
  const input = "Hello\u200BWorld";
  assert.equal(escapeSuspiciousCharacters(input), "Hello[U+200B]World");
});

test("escapes zero-width non-joiner and joiner", () => {
  const input = "Safe\u200CInject\u200DTest";
  assert.equal(escapeSuspiciousCharacters(input), "Safe[U+200C]Inject[U+200D]Test");
});

test("escapes soft hyphen and byte-order mark (BOM)", () => {
  const input = "\uFEFFHidden\u00ADPrompt";
  assert.equal(escapeSuspiciousCharacters(input), "[U+FEFF]Hidden[U+00AD]Prompt");
});

test("handles non-string and empty inputs cleanly", () => {
  assert.equal(escapeSuspiciousCharacters(null), null);
  assert.equal(escapeSuspiciousCharacters(undefined), undefined);
  assert.equal(escapeSuspiciousCharacters(""), "");
});
