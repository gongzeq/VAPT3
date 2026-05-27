import { deriveTitle } from "@/lib/format";
import type { ChatSummary } from "@/lib/types";

/** The sidebar/page title must reflect the user's opening line. */
export function displaySessionTitle(
  session: ChatSummary,
  fallback: string,
  firstUserMessage?: string,
): string {
  return deriveTitle(
    firstUserMessage || session.preview || session.title,
    fallback,
  );
}

export function sessionSubtitle(session: ChatSummary): string {
  const title = session.title?.trim();
  const preview = session.preview?.trim();
  if (!title || !preview || title === preview) {
    return "";
  }
  return title;
}
