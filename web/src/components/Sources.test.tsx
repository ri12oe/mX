// @vitest-environment jsdom
// Sources under an answer (design.md §10.1, §17).
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { Citation, ToolStep, UiMessage } from "../types";
import { MessageView } from "./MessageView";
import { answerSources, isHttpUrl, Sources } from "./Sources";

afterEach(cleanup);

const search = (sources: Citation[]): ToolStep => ({
  id: "s",
  tool: "web_search",
  status: "ok",
  input: { query: "latest Python" },
  output: { sources },
});

describe("isHttpUrl", () => {
  it("accepts http and https only", () => {
    expect(isHttpUrl("https://docs.python.org/3/")).toBe(true);
    expect(isHttpUrl("http://example.com")).toBe(true);
    expect(isHttpUrl("javascript:alert(1)")).toBe(false);
    expect(isHttpUrl("data:text/html,hi")).toBe(false);
    expect(isHttpUrl("not a url")).toBe(false);
  });
});

describe("answerSources", () => {
  it("prefers citations, and falls back to search-step sources", () => {
    const cited = [{ url: "https://a.example", title: "A" }];
    const steps = [search([{ url: "https://b.example", title: "B" }])];
    expect(answerSources(cited, steps)).toEqual({ kind: "cited", items: cited });
    expect(answerSources([], steps)?.kind).toBe("searched");
    expect(answerSources(undefined, undefined)).toBeNull();
  });
});

describe("Sources", () => {
  it("links http(s) titles and leaves unsafe schemes as plain text", () => {
    render(
      <Sources
        citations={[
          { url: "https://docs.python.org/3/", title: "Python docs" },
          { url: "javascript:alert(1)", title: "<img src=x>" },
          { url: "data:text/html,hi", title: "data page" },
        ]}
      />,
    );
    expect(screen.getByRole("region", { name: "Cited sources" })).toBeTruthy();
    expect(screen.getByText("Cited")).toBeTruthy();
    const link = screen.getByRole("link", { name: "Python docs" });
    expect(link.getAttribute("href")).toBe("https://docs.python.org/3/");
    expect(link.getAttribute("rel")).toBe("noopener noreferrer");
    expect(link.getAttribute("target")).toBe("_blank");
    expect(screen.queryByRole("link", { name: "<img src=x>" })).toBeNull();
    expect(screen.getByText("<img src=x>")).toBeTruthy();
    expect(document.querySelector("img")).toBeNull();
    expect(screen.getByText("data page").tagName).toBe("SPAN");
  });

  it("labels search-step sources as searched when nothing was cited", () => {
    render(
      <Sources
        steps={[search([{ url: "https://python.org", title: "Python" }, { url: "https://python.org", title: "dup" }])]}
      />,
    );
    expect(screen.getByRole("region", { name: "Searched sources" })).toBeTruthy();
    expect(screen.getByText("Searched")).toBeTruthy();
    expect(screen.getAllByRole("link")).toHaveLength(1);
  });
});

describe("MessageView sources", () => {
  const base: UiMessage = { id: "a", role: "assistant", content: "Python 3.14 is current.", images: [], imageRefs: [] };

  it("shows the list under the answer", () => {
    render(<MessageView message={{ ...base, citations: [{ url: "https://python.org", title: "Python" }] }} />);
    const body = document.querySelector(".assistant-body")!;
    const answer = body.querySelector(".markdown")!;
    const sources = body.querySelector(".sources")!;
    expect(answer.compareDocumentPosition(sources) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByRole("link", { name: "Python" })).toBeTruthy();
  });
});
