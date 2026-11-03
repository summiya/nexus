#!/usr/bin/env bash
# All mutable Docker resources are newly allocated and test-owned. Never reads
# the root .env or accepts a caller-supplied project, volume or database URL.
set -euo pipefail
umask 077

repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
script_dir="$repo_root/infra/postgres"
base_image='postgres@sha256:cf78e76683b9ca8c5733cbbdce6c9262b45b6767934dd0a95e671f9a0fc20685'
custom_image='nexus-postgres:16.15-alpine3.24-pgvector0.8.7'
nonce="$(od -An -N8 -tx1 /dev/urandom | tr -d ' \n')"
project="nexus-rf04-test-$nonce"
artifacts="$(mktemp -d "${TMPDIR:-/tmp}/nexus-rf04.XXXXXXXX")"
compose_active=false

die() { echo "RF-04 validation failed: $* (artifacts: $artifacts)" >&2; exit 1; }
dc() {
    COMPOSE_IGNORE_ORPHANS=true docker compose --project-name "$project" --project-directory "$script_dir" \
        --env-file "$repo_root/.env.example" --file "$script_dir/compose.test.yml" "$@"
}
finish() {
    # Stop only this invocation's resources. Deliberately retain containers and
    # disposable volumes for inspection; no rm, down, volume deletion or prune.
    if $compose_active; then dc stop >/dev/null 2>&1 || true; fi
    local identity
    for identity in $(docker ps --quiet --filter "label=nexus.rf04.test=$project"); do
        docker stop --time 30 "$identity" >/dev/null || true
    done
    echo "Retained test resources: project/owner=$project; artifacts=$artifacts"
}
trap finish EXIT

compose_checks() {
    export NEXUS_RF04_POSTGRES_IMAGE="$project-postgres"
    export NEXUS_RF04_BACKEND_IMAGE="$project-backend"
    export NEXUS_RF04_FRONTEND_IMAGE="$project-frontend"
    # Explicit -f/-p/--env-file defeat COMPOSE_FILE/PROJECT_NAME and .env defaults.
    dc config --format json > "$artifacts/compose.json"
    python3 - "$artifacts/compose.json" <<'PY'
import json
import sys

config = json.load(open(sys.argv[1]))
assert config["name"].startswith("nexus-rf04-test-")
assert not config.get("volumes"), "Named/external volumes are forbidden"
for service in config["services"].values():
    assert not service.get("ports"), "Published test ports are forbidden"
    for volume in service.get("volumes", []):
        assert volume["type"] == "volume" and not volume.get("source")
backend = config["services"]["backend"]["environment"]
assert backend["DATABASE_URL"] == "postgresql://nexus:nexus-test-only@postgres:5432/nexus"
assert backend["REDIS_URL"] == "redis://redis:6379/0"
assert "http://azurite:10000/" in backend["AZURE_STORAGE_CONNECTION_STRING"]
assert backend["NEXUS_TEST_AZURITE_CONNECTION_STRING"] == backend["AZURE_STORAGE_CONNECTION_STRING"]
PY
    test -z "$(dc ps --all --quiet)" || die "Project already exists"
    compose_active=true
    echo "Using isolated Compose project $project (anonymous disposable volumes)"
    if [ "$1" = docker-check ]; then
        dc build --no-cache
        return
    fi
    dc build backend postgres
    if [ "$1" = backend-check ]; then
        dc run -T backend pytest tests/unit -q
        dc run -T backend pytest tests/api -q
    fi
    dc run -T backend pytest tests/integration -q
    if [ "$1" = backend-check ]; then
        dc run -T backend pytest tests --cov=nexus --cov-branch --cov-report=term-missing -q
        dc run -T backend ruff check src tests
        dc run -T backend mypy src
    fi
}

new_volume() {
    if docker volume inspect "$1" >/dev/null 2>&1; then die "Volume already exists"; fi
    docker volume create --label "nexus.rf04.test=$project" "$1" >/dev/null
}
start_database() {
    local name="$1" image="$2" volume="$3" admin="$4" database="$5"
    test "$(docker volume inspect "$volume" --format '{{index .Labels "nexus.rf04.test"}}')" = "$project" \
        || die "Unowned volume"
    docker run --detach --name "$name" --label "nexus.rf04.test=$project" \
        --network "$project-network" --network-alias postgres \
        --mount "type=volume,source=$volume,target=/var/lib/postgresql/data" \
        -e "POSTGRES_USER=$admin" -e 'POSTGRES_PASSWORD=rf04-test-only' -e "POSTGRES_DB=$database" \
        --health-cmd "pg_isready -h 127.0.0.1 -U $admin -d $database" \
        --health-interval 1s --health-timeout 5s --health-retries 60 "$image" >/dev/null
    local attempt
    for attempt in $(seq 1 60); do
        case "$(docker inspect "$name" --format '{{.State.Health.Status}}')" in
            healthy) return ;;
            unhealthy) die "Test PostgreSQL is unhealthy" ;;
        esac
        sleep 1
    done
    die "Test PostgreSQL did not become healthy"
}
sql() {
    docker exec --interactive "$1" psql -X --set=ON_ERROR_STOP=1 \
        --username "$2" --dbname "$3" --tuples-only --no-align
}
migrate() {
    docker run --name "$project-migrate-$1" --label "nexus.rf04.test=$project" \
        --network "$project-network" --env-file "$repo_root/.env.example" \
        -e 'DATABASE_URL=postgresql://nexus_test_admin:rf04-test-only@postgres:5432/nexus_test' \
        "$project-backend" alembic upgrade "$2"
}
dump_database() {
    docker exec "$1" pg_dump -U "$2" -d nexus_test --create \
        --restrict-key=NexusRF04SyntheticOnly
}
dump_parent_data() {
    docker exec "$1" pg_dump -U nexus_test_admin -d nexus_test --data-only \
        --exclude-table=alembic_version --exclude-table='chunk_embeddings*' \
        --restrict-key=NexusRF04SyntheticOnly
}
check_reader() {
    test "$(printf 'SELECT count(*) FROM files;\n' | sql "$1" nexus_smoke_reader nexus_test)" = 1
    if printf "UPDATE files SET original_name = 'forbidden' WHERE false;\n" \
        | sql "$1" nexus_smoke_reader nexus_test > "$artifacts/reader.out" 2>&1; then
        die "Read-only role unexpectedly has UPDATE permission"
    fi
    grep -q 'permission denied' "$artifacts/reader.out" || die "Unexpected permission error"
}
catalog_fingerprint() {
    sql "$1" nexus_test_admin nexus_test <<'SQL'
SELECT n.nspname, c.relname, c.relkind, c.relowner::regrole, c.relacl
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname='public' ORDER BY c.relname;
SELECT c.conrelid::regclass, c.conname, c.contype, c.convalidated,
       c.condeferrable, c.condeferred, c.conkey, c.confkey,
       CASE WHEN c.confrelid=0 THEN NULL ELSE c.confrelid::regclass::text END,
       CASE WHEN c.contype='c' THEN NULL ELSE pg_get_constraintdef(c.oid) END
FROM pg_constraint c WHERE c.connamespace='public'::regnamespace
ORDER BY c.conrelid::regclass::text, c.conname;
SELECT a.attrelid::regclass, a.attnum, a.attname, a.atttypid::regtype, a.atttypmod, a.attnotnull
FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
WHERE c.relnamespace='public'::regnamespace AND a.attnum>0 AND NOT a.attisdropped
ORDER BY a.attrelid::regclass::text, a.attnum;
SELECT rolname, rolsuper, rolinherit, rolcreaterole, rolcreatedb, rolcanlogin,
       rolreplication, rolconnlimit, rolpassword, rolvaliduntil, rolbypassrls
FROM pg_authid WHERE rolname IN ('nexus_test_admin','nexus_smoke_reader') ORDER BY rolname;
SQL
}
check_constraints() {
    sql "$1" nexus_test_admin nexus_test <<'SQL'
DO $$ BEGIN
    BEGIN
        UPDATE user_roles SET organization_id=999999 WHERE user_id=1 AND role_id=1;
        RAISE EXCEPTION 'Missing tenant foreign key';
    EXCEPTION WHEN foreign_key_violation THEN NULL;
    END;
    BEGIN
        UPDATE files SET size_bytes=-1 WHERE id=1;
        RAISE EXCEPTION 'Missing File CHECK';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        UPDATE documents SET status='invalid' WHERE id=1;
        RAISE EXCEPTION 'Missing Document CHECK';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO users (id, public_id, organization_id, email, status, created_at, updated_at)
        VALUES (999999, '00000000-0000-0000-0000-000000000099', 1, 'synthetic@example.invalid', 'active', now(), now());
        RAISE EXCEPTION 'Missing User uniqueness';
    EXCEPTION WHEN unique_violation THEN NULL;
    END;
END $$;
SQL
}

image_checks() {
    docker buildx imagetools inspect "$base_image" --raw > "$artifacts/base-index.json"
    python3 - "$artifacts/base-index.json" <<'PY'
import json
import sys

index = json.load(open(sys.argv[1]))
platforms = {m["platform"]["architecture"]: m for m in index["manifests"]
             if m["platform"].get("architecture") in ("amd64", "arm64")}
assert set(platforms) == {"amd64", "arm64"}
assert all(m["annotations"]["org.opencontainers.image.version"] == "16.15-alpine3.24"
           for m in platforms.values())
print("Verified pinned PostgreSQL 16.15 Alpine base: AMD64 and ARM64")
PY
    docker build --tag "$custom_image" "$script_dir"
    docker build --tag "$project-backend" "$repo_root/backend"
    local image suffix
    for suffix in base custom; do
        image="$base_image"
        if [ "$suffix" = custom ]; then image="$custom_image"; fi
        docker image inspect "$image" --format \
            '{{json .Config.Entrypoint}} {{json .Config.Cmd}} {{json .Config.Env}} {{json .Config.Volumes}} {{json .Config.User}} {{json .Config.StopSignal}}' \
            > "$artifacts/$suffix-config.txt"
        docker run --name "$project-$suffix-files" --label "nexus.rf04.test=$project" \
            --read-only --mount type=tmpfs,destination=/var/lib/postgresql/data "$image" sh -ec '
                test "$(postgres --version)" = "postgres (PostgreSQL) 16.15"
                test "$(pg_config --version)" = "PostgreSQL 16.15"
                test "$(cat /etc/alpine-release)" = "3.24.1"
                sha256sum /usr/local/bin/postgres /usr/local/bin/pg_config \
                    /usr/local/bin/docker-entrypoint.sh /lib/ld-musl-*.so.1 /usr/lib/libicu*.so.*
                id postgres
            ' > "$artifacts/$suffix-files.txt"
    done
    cmp "$artifacts/base-config.txt" "$artifacts/custom-config.txt"
    cmp "$artifacts/base-files.txt" "$artifacts/custom-files.txt"
    echo "Verified unchanged PostgreSQL, libc/ICU, UID/GID, entrypoint, configuration and PGDATA"

    docker network create --label "nexus.rf04.test=$project" "$project-network" >/dev/null
    new_volume "$project-data"
    local original="$project-original" upgraded="$project-upgraded" restored="$project-restored"
    start_database "$original" "$base_image" "$project-data" nexus_test_admin nexus_test
    migrate baseline 20261007_0019
    sql "$original" nexus_test_admin nexus_test <<'SQL'
BEGIN;
INSERT INTO organizations (id, public_id, name, slug, status, settings_json, created_at, updated_at)
VALUES (1, '00000000-0000-0000-0000-000000000001', 'Synthetic', 'rf04-synthetic', 'active', '{}', now(), now());
INSERT INTO users (id, public_id, organization_id, email, status, created_at, updated_at)
VALUES (1, '00000000-0000-0000-0000-000000000002', 1, 'synthetic@example.invalid', 'active', now(), now());
INSERT INTO roles (id, public_id, organization_id, name, is_system, created_at, updated_at)
VALUES (1, '00000000-0000-0000-0000-000000000003', 1, 'Synthetic reader', false, now(), now());
INSERT INTO user_roles (organization_id, user_id, role_id) VALUES (1, 1, 1);
INSERT INTO role_permissions (role_id, permission_id) SELECT 1, id FROM permissions WHERE key = 'files.read';
INSERT INTO files (id, public_id, organization_id, created_by_user_id, original_name, mime_type, size_bytes,
                   storage_key, storage_status, created_at, updated_at)
VALUES (1, '00000000-0000-0000-0000-000000000004', 1, 1, 'synthetic.txt', 'text/plain', 9,
        'synthetic-only/file', 'available', now(), now());
INSERT INTO documents (id, public_id, organization_id, source_file_id, status, processing_version,
                       extractor_version, created_at, processing_started_at, processing_completed_at)
VALUES (1, '00000000-0000-0000-0000-000000000005', 1, 1, 'completed', 'synthetic-v1', '1', now(), now(), now());
INSERT INTO document_chunk_sets (document_id, organization_id, source_entity_tag, extractor_id,
 extractor_version, normalizer_id, normalizer_version, segmenter_id, segmenter_version,
 preferred_chunk_bytes, max_chunk_bytes, max_source_contributions, chunk_count)
VALUES (1, 1, 'synthetic-etag', 'extractor', '1', 'normalizer', '1', 'segmenter', '1', 1024, 4096, 128, 1);
INSERT INTO document_chunks (id, document_id, organization_id, chunk_index, text, kind, section_path, contributions)
VALUES (1, 1, 1, 0, 'Synthetic', 'text', '{}', '[{"source_block_index":0,"kind":"text","start_line":1,"end_line":1}]');
INSERT INTO model_providers (id, public_id, organization_id, provider_type, display_name, settings_json, enabled)
VALUES (1, '00000000-0000-0000-0000-000000000006', 1, 'openai', 'Synthetic OpenAI', '{}', true);
INSERT INTO configured_models (id, public_id, organization_id, provider_id, provider_model_name,
                               display_name, model_type, capabilities, embedding_dimension, enabled)
VALUES (1, '00000000-0000-0000-0000-000000000007', 1, 1, 'text-embedding-3-small',
        'Synthetic embedding', 'embedding', '{}', 1536, true);
CREATE ROLE nexus_smoke_reader LOGIN;
GRANT CONNECT ON DATABASE nexus_test TO nexus_smoke_reader;
GRANT USAGE ON SCHEMA public TO nexus_smoke_reader;
GRANT SELECT ON users, files, documents, roles, permissions, role_permissions, user_roles TO nexus_smoke_reader;
GRANT USAGE, SELECT ON SEQUENCE users_id_seq, files_id_seq, documents_id_seq TO nexus_smoke_reader;
SELECT setval('users_id_seq', 100, true), setval('files_id_seq', 100, true), setval('documents_id_seq', 100, true);
DO $$ BEGIN
    BEGIN
        UPDATE user_roles SET organization_id = 999999 WHERE user_id = 1 AND role_id = 1;
        RAISE EXCEPTION 'Tenant constraint unexpectedly accepted a foreign organization';
    EXCEPTION WHEN foreign_key_violation THEN NULL;
    END;
END $$;
COMMIT;
SQL
    check_reader "$original"
    printf 'SELECT system_identifier FROM pg_control_system();\n' \
        | sql "$original" nexus_test_admin nexus_test > "$artifacts/cluster-before.txt"
    dump_database "$original" nexus_test_admin > "$artifacts/before.sql"
    dump_parent_data "$original" > "$artifacts/parents-before.sql"
    catalog_fingerprint "$original" > "$artifacts/catalog-before.txt"
    docker exec "$original" pg_dump -U nexus_test_admin -d nexus_test --format=custom \
        > "$artifacts/database.dump"
    docker exec "$original" pg_dumpall -U nexus_test_admin --globals-only \
        --restrict-key=NexusRF04SyntheticOnly > "$artifacts/globals.sql"
    docker stop --time 30 "$original" >/dev/null
    docker network disconnect "$project-network" "$original"
    start_database "$upgraded" "$custom_image" "$project-data" nexus_test_admin nexus_test
    docker logs "$upgraded" > "$artifacts/upgraded.log" 2>&1
    grep -q 'Skipping initialization' "$artifacts/upgraded.log" || die "Existing test cluster was initialized"
    printf 'SELECT system_identifier FROM pg_control_system();\n' \
        | sql "$upgraded" nexus_test_admin nexus_test > "$artifacts/cluster-after.txt"
    cmp "$artifacts/cluster-before.txt" "$artifacts/cluster-after.txt"
    dump_database "$upgraded" nexus_test_admin > "$artifacts/after.sql"
    cmp "$artifacts/before.sql" "$artifacts/after.sql"
    docker exec "$upgraded" pg_dumpall -U nexus_test_admin --globals-only \
        --restrict-key=NexusRF04SyntheticOnly > "$artifacts/globals-after.sql"
    cmp "$artifacts/globals.sql" "$artifacts/globals-after.sql"
    check_reader "$upgraded"
    echo "PASS: existing synthetic cluster, users/Files/Documents/RBAC, constraints, sequences and ACLs preserved"

    # Restore the actual synthetic backup into another fresh cluster. It has a
    # different bootstrap role to avoid collisions with restored global roles.
    new_volume "$project-restore-data"
    start_database "$restored" "$custom_image" "$project-restore-data" rf04_restore_admin postgres
    docker exec --interactive "$restored" psql -X -v ON_ERROR_STOP=1 -U rf04_restore_admin -d postgres \
        < "$artifacts/globals.sql" > "$artifacts/globals-restore.log"
    docker exec --interactive "$restored" pg_restore --exit-on-error --create -U rf04_restore_admin -d postgres \
        < "$artifacts/database.dump"
    # SQL restore can normalize CHECK expression cast syntax. Keep the exact
    # full dump comparison above for image replacement; for restore compare
    # all data/sequence state and catalog structure/owners/ACLs/role hashes,
    # then exercise CHECK, unique and tenant FK semantics directly.
    dump_parent_data "$restored" > "$artifacts/restored-data.sql"
    cmp "$artifacts/parents-before.sql" "$artifacts/restored-data.sql"
    catalog_fingerprint "$restored" > "$artifacts/catalog-restored.txt"
    cmp "$artifacts/catalog-before.txt" "$artifacts/catalog-restored.txt"
    check_constraints "$restored"
    check_reader "$restored"
    test "$(printf "SELECT nextval('users_id_seq');\n" | sql "$restored" nexus_smoke_reader nexus_test)" = 101
    docker stop --time 30 "$restored" >/dev/null
    echo "PASS: verified logical restore with ownership, grants, constraints, data and sequence continuation"

    # Remove the restored server's network alias before using the private
    # 'postgres' hostname again. Network disconnect does not delete its data.
    docker network disconnect "$project-network" "$restored"
    migrate embedding head
    sql "$upgraded" nexus_test_admin nexus_test <<'SQL'
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector' AND extversion = '0.8.7') THEN
        RAISE EXCEPTION 'pgvector 0.8.7 is not enabled';
    END IF;
END $$;
INSERT INTO chunk_embeddings (organization_id, chunk_id, configured_model_id, model_type,
 provider_type, provider_model_name, embedding_dimension, embedding_generation, embedding_version, embedding)
VALUES (1, 1, 1, 'embedding', 'openai', 'text-embedding-3-small', 1536, 1, 'synthetic-v1',
        ('[1,' || repeat('0,', 1534) || '0]')::vector);
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM chunk_embeddings WHERE vector_dims(embedding) = 1536 AND vector_norm(embedding) = 1) THEN
        RAISE EXCEPTION 'Vector functionality failed';
    END IF;
END $$;
SQL
    dump_parent_data "$upgraded" > "$artifacts/parents-after.sql"
    cmp "$artifacts/parents-before.sql" "$artifacts/parents-after.sql"
    echo "PASS: RF-04 migration and pgvector 0.8.7 / VECTOR(1536), with source data unchanged"
    docker image inspect "$custom_image" --format 'Native image architecture: {{.Architecture}}'
}

test "$#" -le 1 || die "Expected one validation mode"
case "${1:-image-check}" in
    image-check) image_checks ;;
    backend-check|integration-check|docker-check) compose_checks "$1" ;;
    *) die "Unknown validation mode" ;;
esac
