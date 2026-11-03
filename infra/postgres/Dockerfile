# syntax=docker/dockerfile:1
# This is the exact multi-architecture base used by the existing Alpine server.
FROM postgres@sha256:cf78e76683b9ca8c5733cbbdce6c9262b45b6767934dd0a95e671f9a0fc20685 AS build

ADD --checksum=sha256:83d673c3b287cddbf3879f86215f043f2c2b56c69d37b2a77504910db1ed6e56 \
    https://codeload.github.com/pgvector/pgvector/tar.gz/f37c13f68b57d2c3472b2214fbcff699d6d34876 /tmp/pgvector.tar.gz

RUN set -eu; \
    test "$(/usr/local/bin/pg_config --version)" = 'PostgreSQL 16.15'; \
    test "$(cat /etc/alpine-release)" = '3.24.1'; \
    test -f /usr/local/include/postgresql/server/postgres.h; \
    test -f "$(/usr/local/bin/pg_config --pgxs)"; \
    apk add --no-cache build-base $DOCKER_PG_LLVM_DEPS; \
    mkdir /tmp/pgvector; \
    tar -xzf /tmp/pgvector.tar.gz -C /tmp/pgvector --strip-components=1; \
    cd /tmp/pgvector; \
    grep -qx 'EXTVERSION = 0.8.7' Makefile; \
    make PG_CONFIG=/usr/local/bin/pg_config OPTFLAGS=""; \
    make PG_CONFIG=/usr/local/bin/pg_config OPTFLAGS="" DESTDIR=/extension install

# No runtime package installation, configuration, entrypoint or PGDATA changes.
# Only pgvector's shared library, SQL/control files and LLVM bitcode are added.
FROM postgres@sha256:cf78e76683b9ca8c5733cbbdce6c9262b45b6767934dd0a95e671f9a0fc20685
COPY --from=build /extension/ /
LABEL org.opencontainers.image.title="Nexus PostgreSQL 16 Alpine with pgvector" \
    org.opencontainers.image.version="16.15-alpine3.24.1-pgvector0.8.7" \
    org.opencontainers.image.source="https://github.com/pgvector/pgvector" \
    nexus.postgres.base="sha256:cf78e76683b9ca8c5733cbbdce6c9262b45b6767934dd0a95e671f9a0fc20685" \
    nexus.pgvector.revision="f37c13f68b57d2c3472b2214fbcff699d6d34876"
