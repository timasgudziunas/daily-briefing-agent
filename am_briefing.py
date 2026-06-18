"""AM Briefing entry point (run before market open, trading days only).

Daily loop (see CLAUDE.md "Architecture"):
    read lessons -> fetch news -> curate items + make predictions
    -> append predictions to ledger -> send email -> write to archive.

Phase 0: skeleton only. The pipeline is wired in Phases 1-2.
"""


def main() -> None:
    raise NotImplementedError("AM Briefing pipeline is built in Phases 1-2.")


if __name__ == "__main__":
    main()
