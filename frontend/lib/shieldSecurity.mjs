/**
 * Security and sanitization utility for Shield plain-text rendering.
 * Replaces invisible and zero-width unicode format characters with visible [U+XXXX] markers.
 */
export function escapeSuspiciousCharacters(str) {
  if (typeof str !== "string") return str;

  return str
    .replace(/\u200B/g, "[U+200B]") // Zero-Width Space
    .replace(/\u200C/g, "[U+200C]") // Zero-Width Non-Joiner
    .replace(/\u200D/g, "[U+200D]") // Zero-Width Joiner
    .replace(/\u2060/g, "[U+2060]") // Word Joiner
    .replace(/\uFEFF/g, "[U+FEFF]") // Zero-Width No-Break Space / BOM
    .replace(/\u00AD/g, "[U+00AD]") // Soft Hyphen
    .replace(/\u200E/g, "[U+200E]") // Left-to-Right Mark
    .replace(/\u200F/g, "[U+200F]") // Right-to-Left Mark
    // Unicode Tags (U+E0000 - U+E007F)
    .replace(/[\uDB40][\uDC00-\uDC7F]/g, (match) => {
      const code = match.codePointAt(0);
      return `[U+${(code || 0).toString(16).toUpperCase()}]`;
    });
}
