/** Only unconfirmed submissions persist; account-scoped and never auto-submitted. */
interface Submission {
  key: string;
  invention: string;
  jurisdiction: string;
}
const pending = new Map<string, Submission>();
const storageKey = (owner: string) => `patentmapper_pending:${owner}`;

export function pendingSubmission(owner: string): Submission | null {
  try {
    const value = JSON.parse(
      sessionStorage.getItem(storageKey(owner)) ?? "null",
    );
    if (
      value &&
      typeof value.key === "string" &&
      typeof value.invention === "string" &&
      typeof value.jurisdiction === "string"
    ) {
      pending.set(owner, value);
      return value;
    }
  } catch {
    /* Retain in-memory key if browser storage is unavailable. */
  }
  return pending.get(owner) ?? null;
}

export function prepareSubmission(
  owner: string,
  invention: string,
  jurisdiction: string,
): Submission {
  invention = invention.trim();
  const previous = pendingSubmission(owner);
  if (
    previous?.invention === invention &&
    previous.jurisdiction === jurisdiction
  )
    return previous;
  const value = { key: crypto.randomUUID(), invention, jurisdiction };
  pending.set(owner, value);
  try {
    sessionStorage.setItem(storageKey(owner), JSON.stringify(value));
  } catch {
    /* In-memory retry still works. */
  }
  return value;
}

export function confirmSubmission(owner: string, key: string): void {
  if (pendingSubmission(owner)?.key !== key) return;
  pending.delete(owner);
  try {
    sessionStorage.removeItem(storageKey(owner));
  } catch {
    /* No storage available. */
  }
}
