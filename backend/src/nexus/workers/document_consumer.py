"""Reserved production consumer entrypoint, unactivated until DP-05 integration."""

from nexus.workers.document_processing import main

if __name__ == "__main__":
    main(consume=True)
