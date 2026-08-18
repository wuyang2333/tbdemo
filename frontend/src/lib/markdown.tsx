import { createElement } from "react";
import type { ReactNode } from "react";

/** 极简 Markdown 渲染：代码块、行内代码、标题、加粗、列表、中文小标题。不引入额外依赖。 */
function renderInline(text: string, keyPrefix: string): ReactNode[] {
  const parts: ReactNode[] = [];
  const regex = /(\*\*[^*]+\*\*|`[^`]+`)/g;
  let last = 0;
  let i = 0;
  let m: RegExpExecArray | null;
  while ((m = regex.exec(text)) !== null) {
    if (m.index > last) parts.push(text.slice(last, m.index));
    const tok = m[0];
    if (tok.startsWith("**") && tok.endsWith("**") && tok.length > 4) {
      parts.push(<strong key={`${keyPrefix}-b${i}`}>{tok.slice(2, -2)}</strong>);
    } else if (tok.startsWith("`") && tok.endsWith("`") && tok.length > 2) {
      parts.push(<code key={`${keyPrefix}-c${i}`}>{tok.slice(1, -1)}</code>);
    } else {
      parts.push(tok);
    }
    last = m.index + tok.length;
    i += 1;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}

export function Markdown({ text }: { text: string }) {
  const nodes: ReactNode[] = [];
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  let i = 0;
  let key = 0;
  let listType: "ul" | "ol" | null = null;
  let listItems: ReactNode[] = [];

  const flushList = () => {
    if (listType === "ul") {
      nodes.push(<ul key={`ul${key++}`}>{listItems}</ul>);
    } else if (listType === "ol") {
      nodes.push(<ol key={`ol${key++}`}>{listItems}</ol>);
    }
    listItems = [];
    listType = null;
  };

  while (i < lines.length) {
    const line = lines[i];

    // 代码块
    if (line.trim().startsWith("```")) {
      flushList();
      i += 1;
      const code: string[] = [];
      while (i < lines.length && !lines[i].trim().startsWith("```")) {
        code.push(lines[i]);
        i += 1;
      }
      i += 1; // 跳过结束 ```
      nodes.push(
        <pre key={`pre${key++}`}>
          <code>{code.join("\n")}</code>
        </pre>,
      );
      continue;
    }

    // Markdown 标题
    const heading = line.match(/^(#{1,4})\s+(.+)$/);
    if (heading) {
      flushList();
      const level = heading[1].length;
      const tag = (["h4", "h3", "h2", "h1"][level - 1] ?? "h4") as "h1" | "h2" | "h3" | "h4";
      nodes.push(
        createElement(tag, { key: `h${key++}` }, renderInline(heading[2], `h${key}`)),
      );
      i += 1;
      continue;
    }

    // 中文小标题：以【...】开头
    const cn = line.match(/^(【[^】]+】)\s*(.*)$/);
    if (cn) {
      flushList();
      nodes.push(
        <div className="ops-ai-subtitle" key={`cn${key++}`}>
          {renderInline(cn[1] + (cn[2] ? " " + cn[2] : ""), `cn${key}`)}
        </div>,
      );
      i += 1;
      continue;
    }

    // 无序列表
    const ul = line.match(/^\s*[-*]\s+(.+)$/);
    if (ul) {
      if (listType !== "ul") {
        flushList();
        listType = "ul";
      }
      listItems.push(<li key={`li${key++}`}>{renderInline(ul[1], `li${key}`)}</li>);
      i += 1;
      continue;
    }

    // 有序列表：1. / 1、 / 1)
    const ol = line.match(/^\s*\d+[.)、]\s+(.+)$/);
    if (ol) {
      if (listType !== "ol") {
        flushList();
        listType = "ol";
      }
      listItems.push(<li key={`li${key++}`}>{renderInline(ol[1], `li${key}`)}</li>);
      i += 1;
      continue;
    }

    // 空行
    if (line.trim() === "") {
      flushList();
      i += 1;
      continue;
    }

    flushList();
    nodes.push(<p key={`p${key++}`}>{renderInline(line, `p${key}`)}</p>);
    i += 1;
  }
  flushList();

  return <div className="ops-ai-markdown">{nodes}</div>;
}

export default Markdown;
