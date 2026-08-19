/** Word-level diff between the normalized script and normalized ASR output.
 * LCS-based; strings here are short (one utterance), so O(n*m) is fine.
 */
export default function DiffText({ reference, hypothesis }: { reference: string; hypothesis: string }) {
  const ops = diffWords(reference.split(" ").filter(Boolean), hypothesis.split(" ").filter(Boolean));
  if (ops.every((o) => o.type === "same")) return null;
  return (
    <div className="arabic diff-text" dir="auto">
      {ops.map((op, i) =>
        op.type === "same" ? (
          <span key={i}>{op.word} </span>
        ) : op.type === "del" ? (
          <span key={i} className="diff-del">{op.word} </span>
        ) : (
          <span key={i} className="diff-ins">{op.word} </span>
        )
      )}
    </div>
  );
}

type Op = { type: "same" | "del" | "ins"; word: string };

function diffWords(a: string[], b: string[]): Op[] {
  const n = a.length;
  const m = b.length;
  const lcs: number[][] = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      lcs[i][j] = a[i] === b[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
    }
  }
  const ops: Op[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      ops.push({ type: "same", word: a[i] });
      i++;
      j++;
    } else if (lcs[i + 1][j] >= lcs[i][j + 1]) {
      ops.push({ type: "del", word: a[i++] }); // in script, not heard
    } else {
      ops.push({ type: "ins", word: b[j++] }); // heard, not in script
    }
  }
  while (i < n) ops.push({ type: "del", word: a[i++] });
  while (j < m) ops.push({ type: "ins", word: b[j++] });
  return ops;
}
