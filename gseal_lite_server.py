"""GSeal Lite mock server with FastAPI endpoints.

This module provides a trio of endpoints that simulate the interaction
between an application webhook listener and a mock external API. The
`/start-test` endpoint triggers a synthetic request to `/mock-gseal-api`,
which in turn schedules an asynchronous webhook dispatch to
`/app-webhook-listener` after a short delay. All interactions use an
in-process HTTP client so the server can run standalone without extra
infrastructure.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any, Dict, Optional

import httpx
from fastapi import FastAPI
from pydantic import BaseModel, Field

logger = logging.getLogger("gseal_lite_server")
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
logger.setLevel(logging.INFO)

app = FastAPI(title="GSeal Lite Mock Server", version="1.0.0")

INTERNAL_BASE_URL = "http://testserver"


def _model_to_dict(model: BaseModel) -> Dict[str, Any]:
    """Return a dictionary representation compatible with both Pydantic v1 & v2."""

    if hasattr(model, "model_dump"):
        return model.model_dump(exclude_none=True)  # type: ignore[attr-defined]
    return model.dict(exclude_none=True)


class StartTestRequest(BaseModel):
    """Payload accepted by the `/start-test` endpoint."""

    mock_payload: Dict[str, Any] = Field(
        default_factory=lambda: {"document_id": "demo-document"},
        description="Payload that will be forwarded to the mock GSeal API.",
    )
    webhook_payload: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Optional override for the webhook payload that the mock API will "
            "POST to the listener."
        ),
    )


class MockGsealRequest(BaseModel):
    """Body posted to the `/mock-gseal-api` endpoint."""

    mock_payload: Dict[str, Any] = Field(default_factory=dict)
    webhook_payload: Optional[Dict[str, Any]] = None


class WebhookNotification(BaseModel):
    """Payload consumed by `/app-webhook-listener`."""

    event: str = Field(default="mock.document.completed")
    data: Dict[str, Any] = Field(default_factory=dict)


async def dispatch_webhook(webhook_payload: Dict[str, Any]) -> None:
    """Wait for a second and then POST a mock webhook notification."""

    logger.info("Waiting 1 second before dispatching webhook...")
    await asyncio.sleep(1)
    async with httpx.AsyncClient(app=app, base_url=INTERNAL_BASE_URL) as client:
        response = await client.post(
            "/app-webhook-listener",
            json=webhook_payload,
            timeout=10.0,
        )
    try:
        response_payload = response.json()
    except ValueError:
        response_payload = response.text
    logger.info(
        "Webhook POST completed with status %s and payload %s",
        response.status_code,
        response_payload,
    )


@app.post("/start-test")
async def start_test(payload: Optional[StartTestRequest] = None) -> Dict[str, Any]:
    """Kick off the mock GSeal Lite loop."""

    payload = payload or StartTestRequest()
    payload_dict = _model_to_dict(payload)
    logger.info("Received /start-test request: %s", payload_dict)
    async with httpx.AsyncClient(app=app, base_url=INTERNAL_BASE_URL) as client:
        response = await client.post(
            "/mock-gseal-api",
            json=payload_dict,
            timeout=10.0,
        )
    response.raise_for_status()
    return {
        "status": "mock_request_dispatched",
        "mock_api_response": response.json(),
    }


@app.post("/mock-gseal-api")
async def mock_gseal_api(request: MockGsealRequest) -> Dict[str, Any]:
    """Simulate a response from the remote GSeal API and schedule a webhook."""

    request_dict = _model_to_dict(request)
    logger.info("Mock GSeal API received payload: %s", request_dict)

    webhook_payload: Dict[str, Any]
    if request.webhook_payload is not None:
        webhook_payload = request.webhook_payload
    else:
        webhook_payload = {
            "event": "mock.document.completed",
            "data": {
                "status": "completed",
                "original_payload": request.mock_payload,
            },
        }

    asyncio.create_task(dispatch_webhook(webhook_payload))

    return {
        "status": "webhook_scheduled",
        "webhook_payload": webhook_payload,
    }


@app.post("/app-webhook-listener")
async def app_webhook_listener(notification: WebhookNotification) -> Dict[str, Any]:
    """Receive the simulated webhook notification."""

    notification_dict = _model_to_dict(notification)
    logger.info("Webhook listener received payload: %s", notification_dict)
    return {"status": "received", "payload": notification_dict}


__all__ = ["app"]
