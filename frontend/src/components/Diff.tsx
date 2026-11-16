import type { ReactNode } from "react";

export interface DiffLine {
  type: "add" | "del" | "ctx";
  text: string;
  oldNo: number | null;
  newNo: number | null;
}

function lcsMatrix(a: string[], b: string[]): Int32Array {
  const rows = a.length + 1;
  const cols = b.length + 1;
  const table = new Int32Array(rows * cols);
  for (let i = a.length - 1; i >= 0; i -= 1) {
    for (let j = b.length - 1; j >= 0; j -= 1) {
      table[i * cols + j] =
        a[i] === b[j]
          ? table[(i + 1) * cols + j + 1] + 1
          : Math.max(table[(i + 1) * cols + j], table[i * cols + j + 1]);
    }
  }
  return table;
}

/** 行级 LCS diff；提示词长度有限，直接算完整矩阵。 */
export function diffLines(before: string, after: string): DiffLine[] {
  const a = before.replace(/\r\n/g, "\n").split("\n");
  const b = after.replace(/\r\n/g, "\n").split("\n");
  const cols = b.length + 1;
  const table = lcsMatrix(a, b);
  const result: DiffLine[] = [];
  let i = 0;
  let j = 0;
  let oldNo = 1;
  let newNo = 1;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      result.push({ type: "ctx", text: a[i], oldNo, newNo });
      i += 1;
      j += 1;
      oldNo += 1;
      newNo += 1;
    } else if (table[(i + 1) * cols + j] >= table[i * cols + j + 1]) {
      result.push({ type: "del", text: a[i], oldNo, newNo: null });
      i += 1;
      oldNo += 1;
    } else {
      result.push({ type: "add", text: b[j], oldNo: null, newNo });
      j += 1;
      newNo += 1;
    }
  }
  while (i < a.length) {
    result.push({ type: "del", text: a[i], oldNo, newNo: null });
    i += 1;
    oldNo += 1;
  }
  while (j < b.length) {
    result.push({ type: "add", text: b[j], oldNo: null, newNo });
    j += 1;
    newNo += 1;
  }
  return result;
}

export function DiffView({ before, after }: { before: string; after: string }): ReactNode {
  const lines = diffLines(before, after);
  const added = lines.filter((line) => line.type === "add").length;
  const removed = lines.filter((line) => line.type === "del").length;
  return (
    <div className="diff">
      <div className="diff__stats">
        <span className="diff__stat diff__stat--add">+{added}</span>
        <span className="diff__stat diff__stat--del">−{removed}</span>
        <span className="diff__hint">初始提示词 → 最终提示词（行级）</span>
      </div>
      <div className="diff__body">
        {lines.map((line, index) => (
          <div key={index} className={`diff__line diff__line--${line.type}`}>
            <span className="diff__no">{line.oldNo ?? ""}</span>
            <span className="diff__no">{line.newNo ?? ""}</span>
            <span className="diff__sign">
              {line.type === "add" ? "+" : line.type === "del" ? "−" : " "}
            </span>
            <span className="diff__text">{line.text || " "}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
