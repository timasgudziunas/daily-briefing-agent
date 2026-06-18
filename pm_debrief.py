"""PM Debrief entry point (run in the evening, trading days only).

Daily loop (see CLAUDE.md "Architecture"):
    load this morning's predictions (+ long-horizon ones now due)
    -> fetch market/data outcomes -> grade strictly -> write verdicts + lessons
    -> build market wrap + learning piece -> send email -> write to archive.

Phase 0: skeleton only. The pipeline is wired in Phase 2.
"""


def main() -> None:
    raise NotImplementedError("PM Debrief pipeline is built in Phase 2.")


if __name__ == "__main__":
    main()
