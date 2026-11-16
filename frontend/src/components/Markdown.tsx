import type { ReactNode } from "react";

function inline(text: string, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  const pattern = /(\*\*[^*]+\*\*|`[^`]+`)/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  let index = 0;
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) {
      nodes.push(text.slice(lastIndex, match.index));
    }
    const token = match[0];
    if (token.startsWith("**")) {
      nodes.push(<strong key={`${keyPrefix}-b-${index}`}>{token.slice(2, -2)}</strong>);
    } else {
      nodes.push(
        <code key={`${keyPrefix}-c-${index}`} className="md-code">
          {token.slice(1, -1)}
        </code>,
      );
    }
    lastIndex = match.index + token.length;
    index += 1;
  }
  if (lastIndex < text.length) nodes.push(text.slice(lastIndex));
  return nodes;
}

function renderTable(rows: string[], key: string): ReactNode {
  const cells = rows.map((row) =>
    row
      .replace(/^\||\|$/g, "")
      .split("|")
      .map((cell) => cell.trim().replace(/\\\|/g, "|")),
  );
  const header = cells[0] ?? [];
  const body = cells.slice(2);
  return (
    <div className="md-table-wrap" key={key}>
      <table className="md-table">
        <thead>
          <tr>
            {header.map((cell, index) => (
              <th key={index}>{inline(cell, `${key}-h-${index}`)}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {body.map((row, rowIndex) => (
            <tr key={rowIndex}>
              {row.map((cell, cellIndex) => (
                <td key={cellIndex}>{inline(cell, `${key}-${rowIndex}-${cellIndex}`)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** 极简 Markdown：只覆盖报告用到的标题/列表/表格/代码块/加粗。 */
export function Markdown({ source }: { source: string }): ReactNode {
  const lines = source.replace(/\r\n/g, "\n").split("\n");
  const blocks: ReactNode[] = [];
  let index = 0;
  let key = 0;

  while (index < lines.length) {
    const line = lines[index];

    if (line.trim() === "") {
      index += 1;
      continue;
    }

    if (line.startsWith("```")) {
      const body: string[] = [];
      index += 1;
      while (index < lines.length && !lines[index].startsWith("```")) {
        body.push(lines[index]);
        index += 1;
      }
      index += 1;
      blocks.push(
        <pre className="md-pre" key={`k${key}`}>
          <code>{body.join("\n")}</code>
        </pre>,
      );
      key += 1;
      continue;
    }

    const heading = /^(#{1,4})\s+(.*)$/.exec(line);
    if (heading) {
      const level = heading[1].length;
      const content = inline(heading[2], `k${key}`);
      const Tag = (`h${level}` as unknown) as "h1";
      blocks.push(
        <Tag className={`md-h md-h${level}`} key={`k${key}`}>
          {content}
        </Tag>,
      );
      key += 1;
      index += 1;
      continue;
    }

    if (line.trimStart().startsWith("|")) {
      const rows: string[] = [];
      while (index < lines.length && lines[index].trimStart().startsWith("|")) {
        rows.push(lines[index].trim());
        index += 1;
      }
      blocks.push(renderTable(rows, `k${key}`));
      key += 1;
      continue;
    }

    if (/^\s*[-*]\s+/.test(line)) {
      const entries: string[] = [];
      while (index < lines.length && /^\s*[-*]\s+/.test(lines[index])) {
        entries.push(lines[index].replace(/^\s*[-*]\s+/, ""));
        index += 1;
      }
      blocks.push(
        <ul className="md-ul" key={`k${key}`}>
          {entries.map((entry, entryIndex) => (
            <li key={entryIndex}>{inline(entry, `k${key}-${entryIndex}`)}</li>
          ))}
        </ul>,
      );
      key += 1;
      continue;
    }

    const paragraph: string[] = [];
    while (
      index < lines.length &&
      lines[index].trim() !== "" &&
      !lines[index].startsWith("#") &&
      !lines[index].startsWith("```") &&
      !lines[index].trimStart().startsWith("|") &&
      !/^\s*[-*]\s+/.test(lines[index])
    ) {
      paragraph.push(lines[index]);
      index += 1;
    }
    blocks.push(
      <p className="md-p" key={`k${key}`}>
        {inline(paragraph.join(" "), `k${key}`)}
      </p>,
    );
    key += 1;
  }

  return <div className="markdown">{blocks}</div>;
}
