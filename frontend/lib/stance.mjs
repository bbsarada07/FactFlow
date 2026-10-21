/** Source-stance helpers for display only. The verdict gate (backend decide_verdict) does not use these. */

/** Count sources that support and refute the claim; NEUTRAL and missing stances are not counted. */
export function stanceCounts(sources) {
  const list = sources || [];
  return {
    support: list.filter((s) => s.stance === "SUPPORTS").length,
    refute: list.filter((s) => s.stance === "REFUTES").length,
  };
}

/** "Sources disagree: X support, Y refute." when both stances are present, otherwise null. */
export function stanceDisagreement(sources) {
  const { support, refute } = stanceCounts(sources);
  return support > 0 && refute > 0 ? `Sources disagree: ${support} support, ${refute} refute.` : null;
}
