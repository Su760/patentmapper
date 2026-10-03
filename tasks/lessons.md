# Lessons Learned

<!-- Format: [date] | what went wrong | rule to follow next time -->
<!-- Add entries here after any correction -->

- 2026-10-02 | Parsing hook configuration did not establish runtime success; a stop-hook error recurred after the report. Inspect the actual failing command and redacted runtime output, and keep unresolved runtime behavior explicitly unverified.
