import { describe, expect, it } from "vitest";
import { SSEParser } from "./sse";

const META = 'event: meta\ndata: {"conversation_id": "c1", "message_id": "m1"}\n\n';
const DELTA = 'event: delta\ndata: {"text": "Hello"}\n\n';

describe("SSEParser", () => {
  it("parses several events in one chunk", () => {
    const events = new SSEParser().push(META + DELTA);
    expect(events.map((e) => e.event)).toEqual(["meta", "delta"]);
    expect(JSON.parse(events[1].data)).toEqual({ text: "Hello" });
  });

  it("waits for the rest of an event split across chunks, even mid-JSON", () => {
    const parser = new SSEParser();
    const whole = META + DELTA;
    const cut = whole.indexOf('"Hel') + 3;
    expect(parser.push(whole.slice(0, cut)).map((e) => e.event)).toEqual(["meta"]);
    expect(parser.push(whole.slice(cut))).toEqual([{ event: "delta", data: '{"text": "Hello"}' }]);
  });

  it("handles one character at a time", () => {
    const parser = new SSEParser();
    const events = [...META + DELTA].flatMap((ch) => parser.push(ch));
    expect(events.map((e) => e.event)).toEqual(["meta", "delta"]);
  });

  it("accepts CRLF line endings, skips comments, joins multi-line data", () => {
    const events = new SSEParser().push(": keep-alive\r\n\r\nevent: note\r\ndata: a\r\ndata: b\r\n\r\n");
    expect(events).toEqual([{ event: "note", data: "a\nb" }]);
  });

  it("defaults the event name to 'message'", () => {
    expect(new SSEParser().push("data: x\n\n")).toEqual([{ event: "message", data: "x" }]);
  });
});
