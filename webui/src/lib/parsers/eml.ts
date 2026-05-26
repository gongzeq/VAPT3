/**
 * EML (RFC 2822) file parser for the workflow RunDialog.
 *
 * Extracted field names match the phishing-email workflow template's input
 * names: sender / subject / body / recipient / urls.
 *
 * Supports:
 *   - RFC 2047 encoded-words (=?UTF-8?B?...?=  =?GBK?Q?...?=)
 *   - Content-Transfer-Encoding: base64 / quoted-printable
 *   - MIME structures: text/plain, text/html, multipart/alternative,
 *     multipart/mixed (first text/plain part wins; falls back to text/html)
 */

import type { FileParser, FileParseResult } from "./types";

// ─── Internal helpers ────────────────────────────────────────────────────

/** Decode a base64 or quoted-printable body part to a UTF-8 string. */
function decodeBody(s: string, enc: string): string {
  if (enc === "base64") {
    try {
      const clean = s.replace(/\s/g, "");
      return new TextDecoder("utf-8").decode(
        Uint8Array.from(atob(clean), (c) => c.charCodeAt(0)),
      );
    } catch {
      return s;
    }
  }
  if (enc === "quoted-printable") {
    return s
      .replace(/=\r?\n/g, "")
      .replace(
        /=([0-9A-Fa-f]{2})/g,
        (_, h: string) => String.fromCharCode(parseInt(h, 16)),
      );
  }
  return s;
}

/** Strip HTML tags and unescape common entities. */
function stripHtml(s: string): string {
  return s
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/g, " ")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&amp;/g, "&")
    .replace(/\s+/g, " ")
    .trim();
}

/** Decode RFC 2047 encoded-words in a header value. */
function decodeHeaderWord(s: string): string {
  return s.replace(
    /=\?([^?]+)\?([BbQq])\?([^?]*)\?=/g,
    (_, cs: string, enc: string, data: string) => {
      try {
        const bytes =
          enc.toUpperCase() === "B"
            ? Uint8Array.from(atob(data), (c) => c.charCodeAt(0))
            : new TextEncoder().encode(
                data
                  .replace(/_/g, " ")
                  .replace(
                    /=([0-9A-Fa-f]{2})/g,
                    (__, h: string) => String.fromCharCode(parseInt(h, 16)),
                  ),
              );
        return new TextDecoder(cs).decode(bytes);
      } catch {
        return data;
      }
    },
  );
}

/**
 * Recursively extract the best plain-text representation from a MIME body.
 * Prefers text/plain over text/html; for multipart picks the first text/plain
 * part, falling back to text/html or nested multipart.
 */
function extractText(body: string, mimeType: string, enc: string): string {
  const mt = mimeType.trim().split(";")[0].toLowerCase().trim();
  if (mt === "text/plain") return decodeBody(body, enc);
  if (mt === "text/html") return stripHtml(decodeBody(body, enc));
  if (mt.startsWith("multipart/")) {
    const boundary = mimeType.match(/boundary="?([^";\s]+)"?/i)?.[1];
    if (!boundary) return "";
    const esc = boundary.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const parts = body
      .split(new RegExp(`--${esc}(?:--)?`))
      .filter((p) => p.trim() && p.trim() !== "--");
    let htmlFallback = "";
    for (const part of parts) {
      const pi = part.indexOf("\n\n");
      if (pi < 0) continue;
      const ph = part.slice(0, pi);
      const pb = part.slice(pi + 2);
      const pct = ph.match(/Content-Type:\s*([^\r\n]+)/i)?.[1]?.trim() ?? "";
      const pcte = (
        ph.match(/Content-Transfer-Encoding:\s*([^\r\n]+)/i)?.[1] ?? ""
      )
        .trim()
        .toLowerCase();
      const sub = extractText(pb, pct, pcte);
      if (pct.toLowerCase().startsWith("text/plain")) return sub;
      if (!htmlFallback && pct.toLowerCase().startsWith("text/html"))
        htmlFallback = sub;
      if (!htmlFallback && pct.toLowerCase().startsWith("multipart/"))
        htmlFallback = sub;
    }
    return htmlFallback;
  }
  return "";
}

// ─── Public parser ────────────────────────────────────────────────────────

/**
 * Parse a raw EML string and return a flat map suitable for filling workflow
 * inputs.  Output keys:
 *   sender    — From: address
 *   subject   — decoded Subject: value
 *   recipient — To: / Delivered-To: address
 *   body      — best plain-text representation (≤ 6 000 chars)
 *   urls      — JSON array string of unique http(s) URLs found in body
 */
export function parseEml(raw: string): FileParseResult {
  const text = raw.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  const blankAt = text.indexOf("\n\n");
  if (blankAt < 0) return {};

  const headerBlock = text.slice(0, blankAt);
  const bodyBlock = text.slice(blankAt + 2);

  // Unfold and parse headers into lowercase map
  const hmap: Record<string, string> = {};
  let cur = "";
  for (const line of (headerBlock + "\n").split("\n")) {
    if (line.length && (line[0] === " " || line[0] === "\t")) {
      cur += " " + line.trim();
    } else {
      if (cur) {
        const ci = cur.indexOf(":");
        if (ci > 0)
          hmap[cur.slice(0, ci).trim().toLowerCase()] = cur.slice(ci + 1).trim();
      }
      cur = line;
    }
  }

  const result: FileParseResult = {};

  // sender — extract bare email address from From: header
  const fromRaw = hmap["from"] ?? "";
  const senderEmail =
    fromRaw.match(/<([^>]+@[^>]+)>/)?.[1] ??
    fromRaw.match(/[\w.+%\-]+@[\w.\-]+\.[\w]{2,}/)?.[0] ??
    fromRaw;
  if (senderEmail) result.sender = senderEmail.trim();

  // subject — decode RFC 2047 encoded-words
  if (hmap["subject"]) result.subject = decodeHeaderWord(hmap["subject"]);

  // recipient — To: takes precedence, fall back to Delivered-To:
  const toRaw = hmap["to"] ?? hmap["delivered-to"] ?? "";
  if (toRaw) {
    const toEmail =
      toRaw.match(/<([^>]+@[^>]+)>/)?.[1] ??
      toRaw.match(/[\w.+%\-]+@[\w.\-]+\.[\w]{2,}/)?.[0] ??
      "";
    if (toEmail) result.recipient = toEmail.trim();
  }

  // body — extract best plain-text representation
  const ctFull = hmap["content-type"] ?? "text/plain";
  const cte = (hmap["content-transfer-encoding"] ?? "").toLowerCase().trim();
  const bodyText = extractText(bodyBlock, ctFull, cte) || bodyBlock;
  result.body = bodyText.trim().slice(0, 6000);

  // urls — unique HTTP(S) links found in body
  const urls = [
    ...new Set(result.body.match(/https?:\/\/[^\s<>"'\\]+/g) ?? []),
  ];
  if (urls.length) result.urls = JSON.stringify(urls.slice(0, 50));

  return result;
}

// ─── FileParser implementation ────────────────────────────────────────────

export const emlParser: FileParser = {
  name: "EML 邮件",
  accepts(fileName, mimeType) {
    return (
      fileName.toLowerCase().endsWith(".eml") ||
      mimeType === "message/rfc822"
    );
  },
  parse: parseEml,
};
