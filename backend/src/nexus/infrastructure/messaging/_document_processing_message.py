"""Bounded Azure transport encoding for Document processing requests."""

import json
from dataclasses import asdict
from uuid import UUID

from azure.servicebus import ServiceBusReceivedMessage
from azure.servicebus.amqp import AmqpMessageBodyType

from nexus.documents.ports.processing import DocumentProcessingRequested

MAX_DOCUMENT_MESSAGE_BYTES = 65_536


def encode_document_message(message: DocumentProcessingRequested) -> bytes:
    return json.dumps(
        asdict(message), default=str, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate message field")
        result[key] = value
    return result


def decode_document_message(
    message: ServiceBusReceivedMessage,
) -> DocumentProcessingRequested:
    if message.body_type is not AmqpMessageBodyType.DATA:
        raise ValueError("Invalid document message")
    body = message.body
    data = bytearray()
    for section in (body,) if isinstance(body, bytes) else body:
        if (
            not isinstance(section, bytes)
            or len(data) + len(section) > MAX_DOCUMENT_MESSAGE_BYTES
        ):
            raise ValueError("Invalid document message")
        data.extend(section)
    try:
        payload = json.loads(
            data.decode("utf-8", errors="strict"), object_pairs_hook=_unique_object
        )
        if not isinstance(payload, dict) or set(payload) != {
            "schema_version",
            "request_public_id",
            "organization_public_id",
            "document_public_id",
        }:
            raise ValueError("Invalid document message")
        if not all(
            isinstance(payload[key], str)
            for key in (
                "request_public_id",
                "organization_public_id",
                "document_public_id",
            )
        ):
            raise ValueError("Invalid document identity")
        return DocumentProcessingRequested(
            request_public_id=UUID(payload["request_public_id"]),
            organization_public_id=UUID(payload["organization_public_id"]),
            document_public_id=UUID(payload["document_public_id"]),
            schema_version=payload["schema_version"],
        )
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, RecursionError) as exc:
        raise ValueError("Invalid document message") from exc
