import { describe, expect, it } from "vitest";

import type { Resume } from "./api";
import {
  DOCUMENT_STATUSES,
  documentState,
  documentSummary,
  formatSize,
} from "./documents";

function resume(overrides: Partial<Resume> = {}): Resume {
  return {
    id: "r1",
    filename: "cv.pdf",
    status: "extracted",
    size_bytes: 240_000,
    page_count: 2,
    pages_without_text: [],
    pages_from_ocr: [],
    failure_reason: null,
    attempts: 1,
    can_retry: false,
    ...overrides,
  };
}

describe("documentState", () => {
  it("has words for every status the API can send", () => {
    for (const status of DOCUMENT_STATUSES) {
      const state = documentState(status);
      expect(state.label, status).toBeTruthy();
      expect(state.detail, status).toBeTruthy();
    }
  });

  // `docs/DESIGN.md` §1: the three meaning colours say what the system found in a
  // *document*, and a document that could not be read is exactly that. A queued
  // one is a workflow state and gets none of them.
  it("spends a reserved colour only where the system is talking about the document", () => {
    expect(documentState("extracted").tone).toBe("cited");
    expect(documentState("failed").tone).toBe("dropped");
    expect(documentState("dead_lettered").tone).toBe("ambiguous");
    expect(documentState("pending").tone).toBe("neutral");
    expect(documentState("processing").tone).toBe("neutral");
  });

  // The two failure statuses mean different things to the person looking at them:
  // one is worth pressing a button about, the other is not.
  it("keeps the two failures apart in words, not only in colour", () => {
    expect(documentState("dead_lettered").detail).toMatch(/trying again/);
    expect(documentState("failed").detail).not.toMatch(/trying again/);
  });
});

describe("documentSummary", () => {
  it("names the size and the page count", () => {
    expect(documentSummary(resume())).toBe("234 KB · 2 pages");
  });

  it("says nothing about pages when the file has no page breaks", () => {
    expect(documentSummary(resume({ page_count: null, filename: "cv.docx" }))).toBe("234 KB");
  });

  it("says when pages were recognised rather than read", () => {
    expect(documentSummary(resume({ pages_from_ocr: [1] }))).toMatch(/1 page read by OCR/);
  });

  it("counts one page as one page", () => {
    expect(documentSummary(resume({ page_count: 1 }))).toMatch(/1 page$/);
  });
});

describe("formatSize", () => {
  it("keeps small files in bytes", () => {
    expect(formatSize(900)).toBe("900 B");
  });

  it("rounds kilobytes rather than showing a decimal nobody needs", () => {
    expect(formatSize(2048)).toBe("2 KB");
  });

  it("keeps one decimal for megabytes", () => {
    expect(formatSize(3_500_000)).toBe("3.3 MB");
  });

  // The case the naive version gets wrong: a 1023-byte file is not "0 KB", which
  // reads as an empty upload.
  it("never rounds a real file down to nothing", () => {
    expect(formatSize(1023)).toBe("1023 B");
    expect(formatSize(1024)).toBe("1 KB");
  });
});
