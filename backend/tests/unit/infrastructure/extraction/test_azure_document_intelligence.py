import asyncio
from unittest.mock import AsyncMock

import pytest
from azure.ai.documentintelligence.models import AnalyzeResult
from azure.core.exceptions import (
    AzureError,
    ClientAuthenticationError,
    HttpResponseError,
    ServiceRequestError,
    ServiceResponseError,
)

from nexus.documents.ports.extraction import DocumentExtractionError, OcrPage
from nexus.documents.ports.extraction import DocumentExtractionFailure as Failure
from nexus.infrastructure.extraction.azure_document_intelligence import (
    AzureDocumentIntelligenceOcr,
)


def result(*, pages=None, paragraphs=None, content="Café Ω\nSecond"):
    return AnalyzeResult(
        {
            "modelId": "prebuilt-read",
            "apiVersion": "2024-11-30",
            "content": content,
            "pages": pages
            if pages is not None
            else [
                {
                    "pageNumber": 2,
                    "lines": [
                        {"content": "Second", "spans": [{"offset": 7, "length": 6}]},
                        {"content": "Café Ω", "spans": [{"offset": 0, "length": 6}]},
                    ],
                },
            ],
            "paragraphs": paragraphs,
        }
    )


def client(value=None):
    poller = AsyncMock()
    poller.result.return_value = result() if value is None else value
    sdk = AsyncMock()
    sdk.begin_analyze_document.return_value = poller
    return sdk, poller


def extract(sdk, **limits):
    return asyncio.run(
        AzureDocumentIntelligenceOcr(sdk, **limits).extract_pages(
            b"verified-pdf", page_numbers=(2,)
        )
    )


def test_exact_request_order_unicode_and_borrowed_client_ownership():
    sdk, poller = client()
    submitted = []

    async def submit(*args, **kwargs):
        submitted.append(kwargs["body"].getvalue())
        return poller

    sdk.begin_analyze_document.side_effect = submit
    assert extract(sdk) == (OcrPage(2, ("Café Ω", "Second")),)
    args, kwargs = sdk.begin_analyze_document.call_args
    assert args == ("prebuilt-read",)
    assert submitted == [b"verified-pdf"]
    assert kwargs["body"].closed
    assert kwargs == {
        "body": kwargs["body"],
        "pages": "2",
        "content_type": "application/pdf",
        "string_index_type": "unicodeCodePoint",
        "polling_interval": 2,
        "retry_total": 0,
        "connection_timeout": 20,
        "read_timeout": 20,
    }
    poller.result.assert_awaited_once()
    sdk.close.assert_not_called()
    sdk.__aexit__.assert_not_called()


def test_reliable_paragraphs_replace_lines_without_duplicates():
    sdk, _ = client(
        result(
            paragraphs=[
                {
                    "content": "Café Ω\nSecond",
                    "spans": [{"offset": 0, "length": 13}],
                    "boundingRegions": [{"pageNumber": 2}],
                },
            ]
        )
    )
    assert extract(sdk) == (OcrPage(2, ("Café Ω\nSecond",)),)


@pytest.mark.parametrize("regions", [None, [{"pageNumber": 2}, {"pageNumber": 4}]])
def test_ambiguous_paragraphs_fall_back_to_original_pages_ordered_lines(regions):
    sdk, _ = client(
        result(
            pages=[
                {
                    "pageNumber": 4,
                    "lines": [
                        {"content": "Second", "spans": [{"offset": 7, "length": 6}]}
                    ],
                },
                {
                    "pageNumber": 2,
                    "lines": [
                        {"content": "Café Ω", "spans": [{"offset": 0, "length": 6}]}
                    ],
                },
            ],
            paragraphs=[
                {
                    "content": "Café Ω\nSecond",
                    "spans": [{"offset": 0, "length": 13}],
                    "boundingRegions": regions,
                }
            ],
        )
    )
    output = asyncio.run(
        AzureDocumentIntelligenceOcr(sdk).extract_pages(b"pdf", page_numbers=(2, 4))
    )
    assert output == (OcrPage(2, ("Café Ω",)), OcrPage(4, ("Second",)))
    assert sdk.begin_analyze_document.call_args.kwargs["pages"] == "2,4"


def test_empty_page_remains_present_without_inventing_text():
    sdk, _ = client(result(pages=[{"pageNumber": 2}], content=""))
    assert extract(sdk) == (OcrPage(2, ()),)


@pytest.mark.parametrize(
    "value",
    [
        result(pages=[]),
        result(pages=[{"pageNumber": 1}]),
        result(pages=[{"pageNumber": 2}, {"pageNumber": 2}]),
        result(pages=[{"pageNumber": True}]),
        AnalyzeResult(
            {
                "apiVersion": "old",
                "modelId": "other",
                "content": "private",
                "pages": [{"pageNumber": 2}],
            }
        ),
        result(
            paragraphs=[
                {
                    "content": "private",
                    "spans": [{"offset": 0, "length": 7}],
                    "boundingRegions": [{"pageNumber": 99}],
                }
            ]
        ),
        result(
            pages=[
                {
                    "pageNumber": 2,
                    "lines": [
                        {"content": "private", "spans": [{"offset": 100, "length": 5}]}
                    ],
                }
            ]
        ),
        result(pages=[{"pageNumber": 2, "lines": [{"content": "private"}]}]),
        result(
            pages=[
                {
                    "pageNumber": 2,
                    "lines": [
                        {"content": "duplicate", "spans": [{"offset": 0, "length": 6}]},
                        {"content": "duplicate", "spans": [{"offset": 0, "length": 6}]},
                    ],
                }
            ]
        ),
    ],
)
def test_partial_malformed_or_duplicate_provider_output_fails_safely(value):
    sdk, _ = client(value)
    with pytest.raises(DocumentExtractionError) as exc:
        extract(sdk)
    assert exc.value.reason is Failure.PROVIDER_FAILURE
    assert str(exc.value) == "Document extraction failed"


@pytest.mark.parametrize("stage", ["submit", "poll"])
@pytest.mark.parametrize(
    "error,reason",
    [
        (ClientAuthenticationError("private"), Failure.PROVIDER_ACCESS),
        (ServiceRequestError("private"), Failure.PROVIDER_TRANSIENT),
        (ServiceResponseError("private"), Failure.PROVIDER_TRANSIENT),
        (TimeoutError("private"), Failure.PROVIDER_TRANSIENT),
        (ValueError("private"), Failure.PROVIDER_FAILURE),
        (AzureError("private"), Failure.PROVIDER_FAILURE),
    ],
)
def test_failures_are_safe_chained_and_not_retried(stage, error, reason):
    sdk, poller = client()
    if stage == "submit":
        sdk.begin_analyze_document.side_effect = error
    else:
        poller.result.side_effect = error
    with pytest.raises(DocumentExtractionError) as exc:
        extract(sdk)
    assert exc.value.reason is reason
    assert str(exc.value) == "Document extraction failed"
    assert exc.value.__cause__ is error
    sdk.begin_analyze_document.assert_awaited_once()
    sdk.close.assert_not_called()


@pytest.mark.parametrize(
    "status,reason",
    [
        (401, Failure.PROVIDER_ACCESS),
        (403, Failure.PROVIDER_ACCESS),
        (404, Failure.PROVIDER_ACCESS),
        (408, Failure.PROVIDER_TRANSIENT),
        (429, Failure.PROVIDER_TRANSIENT),
        (503, Failure.PROVIDER_TRANSIENT),
        (400, Failure.MALFORMED),
        (415, Failure.MALFORMED),
        (422, Failure.MALFORMED),
        (200, Failure.PROVIDER_FAILURE),
        (409, Failure.PROVIDER_FAILURE),
    ],
)
def test_http_failure_classification(status, reason):
    error = HttpResponseError("private")
    error.status_code = status
    sdk, poller = client()
    poller.result.side_effect = error
    with pytest.raises(DocumentExtractionError) as exc:
        extract(sdk)
    assert exc.value.reason is reason


@pytest.mark.parametrize(
    "limits",
    [{"max_bytes": 3}, {"max_pages": 1}, {"max_blocks": 1}, {"max_text_bytes": 3}],
)
def test_resource_limits_fail_without_partial_output(limits):
    sdk, _ = client()
    with pytest.raises(DocumentExtractionError) as exc:
        extract(sdk, **limits)
    assert exc.value.reason is Failure.RESOURCE_LIMIT
    if "max_bytes" in limits or "max_pages" in limits:
        sdk.begin_analyze_document.assert_not_called()


@pytest.mark.parametrize("pages", [(), (True,), (0,), (2, 2), (3, 2), ("2",), [2]])
def test_invalid_selected_pages_prevent_network_calls(pages):
    sdk, _ = client()
    with pytest.raises(DocumentExtractionError) as exc:
        asyncio.run(
            AzureDocumentIntelligenceOcr(sdk).extract_pages(b"pdf", page_numbers=pages)
        )
    assert exc.value.reason is Failure.MALFORMED
    sdk.begin_analyze_document.assert_not_called()


@pytest.mark.parametrize(
    "limits",
    [
        {"concurrency": True},
        {"max_pages": 0},
        {"max_blocks": 1.5},
        {"timeout_seconds": True},
        {"timeout_seconds": float("nan")},
        {"timeout_seconds": 0},
    ],
)
def test_invalid_constructor_limits(limits):
    with pytest.raises(ValueError):
        AzureDocumentIntelligenceOcr(AsyncMock(), **limits)


@pytest.mark.parametrize("stage", ["submit", "poll", "admission"])
@pytest.mark.parametrize("cancel", [True, False])
def test_cancellation_and_deadline_settle_waiting_release_slots_and_leave_no_tasks(
    stage, cancel
):
    async def run():
        sdk, poller = client()
        entered, cleaned = asyncio.Event(), asyncio.Event()

        async def wait(*args, **kwargs):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaned.set()

        ocr = AzureDocumentIntelligenceOcr(
            sdk, concurrency=1, timeout_seconds=5 if cancel else 0.02
        )
        if stage == "submit":
            sdk.begin_analyze_document.side_effect = wait
        elif stage == "poll":
            poller.result.side_effect = wait
        else:
            await ocr._slots.acquire()
        task = asyncio.create_task(ocr.extract_pages(b"pdf", page_numbers=(2,)))
        if stage == "admission":
            await asyncio.sleep(0)
        else:
            await entered.wait()
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with pytest.raises(DocumentExtractionError) as exc:
                await task
            assert exc.value.reason is Failure.PROVIDER_TRANSIENT
        if stage == "admission":
            ocr._slots.release()
            sdk.begin_analyze_document.assert_not_called()
        else:
            assert cleaned.is_set()
        sdk.begin_analyze_document.side_effect = None
        poller.result.side_effect = None
        assert await ocr.extract_pages(b"pdf", page_numbers=(2,))
        assert asyncio.all_tasks() == {asyncio.current_task()}
        sdk.close.assert_not_called()

    asyncio.run(run())


def test_concurrent_operations_are_bounded_and_event_loop_remains_responsive():
    async def run():
        sdk, _ = client()
        release, two_started = asyncio.Event(), asyncio.Event()
        active = peak = 0

        async def submit(*args, **kwargs):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            if active == 2:
                two_started.set()
            poller = AsyncMock()

            async def finish():
                nonlocal active
                try:
                    await release.wait()
                    return result()
                finally:
                    active -= 1

            poller.result.side_effect = finish
            return poller

        sdk.begin_analyze_document.side_effect = submit
        ocr = AzureDocumentIntelligenceOcr(sdk, concurrency=2)
        tasks = [
            asyncio.create_task(ocr.extract_pages(b"pdf", page_numbers=(2,)))
            for _ in range(4)
        ]
        await asyncio.wait_for(two_started.wait(), 1)
        assert sdk.begin_analyze_document.await_count == 2
        assert active == 2
        release.set()
        await asyncio.gather(*tasks)
        assert peak == 2 and active == 0

    asyncio.run(run())


@pytest.mark.parametrize(
    "mode", ["success", "submit_429", "poll_429", "failed", "cancel", "timeout"]
)
def test_pinned_async_sdk_request_poll_failure_and_cancellation_behavior(mode):
    from aiohttp import web
    from azure.ai.documentintelligence.aio import DocumentIntelligenceClient
    from azure.core.credentials import AzureKeyCredential

    async def run():
        requests = []
        poll_started, release = asyncio.Event(), asyncio.Event()

        async def handle(request):
            requests.append((request.method, dict(request.query), await request.read()))
            if request.method == "POST":
                if mode == "submit_429":
                    return web.json_response(
                        {"error": {"code": "TooManyRequests", "message": "private"}},
                        status=429,
                    )
                return web.json_response(
                    {},
                    status=202,
                    headers={
                        "Operation-Location": f"http://{request.host}/documentintelligence/documentModels/prebuilt-read/analyzeResults/test?api-version=2024-11-30",
                        "Retry-After": "0",
                    },
                )
            if mode == "poll_429":
                return web.json_response(
                    {"error": {"code": "TooManyRequests", "message": "private"}},
                    status=429,
                )
            if mode == "failed":
                return web.json_response(
                    {
                        "status": "failed",
                        "error": {"code": "InternalError", "message": "private"},
                    }
                )
            if mode in {"cancel", "timeout"}:
                poll_started.set()
                await release.wait()
            return web.json_response(
                {"status": "succeeded", "analyzeResult": result().as_dict()}
            )

        app = web.Application()
        app.router.add_route("*", "/{path:.*}", handle)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        try:
            # Test-only credential, local HTTP server: no Azure access or production key path.
            async with DocumentIntelligenceClient(
                f"http://127.0.0.1:{port}",
                AzureKeyCredential("test"),
                api_version="2024-11-30",
            ) as sdk:
                ocr = AzureDocumentIntelligenceOcr(
                    sdk, timeout_seconds=0.1 if mode == "timeout" else 5
                )
                task = asyncio.create_task(
                    ocr.extract_pages(b"exact-pdf", page_numbers=(2,))
                )
                if mode == "cancel":
                    await asyncio.wait_for(poll_started.wait(), 3)
                    task.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await task
                elif mode == "success":
                    assert await task == (OcrPage(2, ("Café Ω", "Second")),)
                else:
                    with pytest.raises(DocumentExtractionError) as exc:
                        await task
                    assert exc.value.reason is (
                        Failure.PROVIDER_FAILURE
                        if mode == "failed"
                        else Failure.PROVIDER_TRANSIENT
                    )
                    assert str(exc.value) == "Document extraction failed"
                release.set()
                # Cancellation settles the HTTP connection without closing the borrowed client.
                transport = sdk._client._pipeline._transport
                assert not transport.session.closed
                assert not transport.session.connector._acquired
            assert [r[0] for r in requests] == (
                ["POST"] if mode == "submit_429" else ["POST", "GET"]
            )
            assert requests[0][1] == {
                "pages": "2",
                "stringIndexType": "unicodeCodePoint",
                "api-version": "2024-11-30",
            }
            assert requests[0][2] == b"exact-pdf"
        finally:
            release.set()
            await runner.cleanup()

    asyncio.run(run())
