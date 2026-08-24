import type { Role } from "@/lib/api";

/**
 * What the account screen has to say before somebody does something irreversible.
 *
 * In `lib/` rather than in the page for the reason the rest of this directory is:
 * `web/` has vitest and no DOM, so a sentence written inside a component is a
 * sentence no test can reach — and these particular sentences are the difference
 * between a consented action and a surprise.
 */

/**
 * What ending every session means, said before the button rather than after it.
 *
 * `POST /auth/change-password` bumps `Candidate.token_epoch`, which invalidates
 * every token minted under the old password — including on devices this server has
 * no record of. The caller's own tab survives, because the route answers with a
 * fresh pair. Somebody who does not know that reads the sign-in screen on their
 * phone as a fault.
 */
export const PASSWORD_CHANGE_NOTICE =
  "Changing your password signs you out everywhere else — every phone, tab and device holding this account, including ones we cannot see. This tab stays signed in.";

/**
 * What erasure destroys, in the order it destroys it.
 *
 * The first two sentences are true for every account. The third is only true for a
 * recruiter, and it is about **other people's** history: deleting a recruiter
 * deletes their postings, and a posting ceasing to exist takes every screening and
 * every application to it. `api/app/api/routes/auth.py` says that out loud rather
 * than leaving it to be discovered, and so does this.
 */
export function erasureConsequences(role: Role): string[] {
  const everyone = [
    "Your documents are deleted from storage first, then the rows that point at them — so nothing is left in the bucket that no row can reach.",
    "Your profiles, screenings, applications and their history go with the account. None of it can be restored.",
  ];
  if (role !== "recruiter" && role !== "admin") return everyone;
  return [
    ...everyone,
    "Your postings are deleted too, and with them every screening and every other person's application to those postings. That is what a posting ceasing to exist means, and it is somebody else's history.",
  ];
}

/**
 * What the exported copy is called on disk.
 *
 * The account id rather than the email: a filename ends up in screenshots, backup
 * listings and support threads, and an address is the one field in the export that
 * identifies a person at a glance.
 */
export function exportFilename(accountId: string): string {
  const safe = accountId.replace(/[^a-zA-Z0-9-]/g, "");
  return `hirelens-export-${safe || "account"}.json`;
}
