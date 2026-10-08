"""Explicit production consumer entrypoint for the real Document pipeline."""

from nexus.workers.document_processing import main

if __name__ == "__main__":
    main(consume=True)
