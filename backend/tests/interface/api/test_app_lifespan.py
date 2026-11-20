"""The API's lifespan: the shared startup validation runs before the first
request is served (and a refusal stops the app from starting), and the
container is closed once on shutdown. `tests/interface/test_startup.py`
covers what the validation itself checks."""

import unittest
from unittest.mock import AsyncMock, patch

from starlette.testclient import TestClient

from app.container import container
from app.interface.api import app as api
from app.interface.startup import API


class LifespanTests(unittest.TestCase):
    def test_startup_validates_as_the_api_and_shutdown_closes_the_container(self) -> None:
        with patch.object(api, "validate_startup", AsyncMock()) as validate, patch.object(
            container, "close", AsyncMock()
        ) as close:
            with TestClient(api.app) as client:
                validate.assert_awaited_once_with(container, API)
                close.assert_not_awaited()
                self.assertEqual(client.get("/api/health").status_code, 200)
            close.assert_awaited_once_with()

    def test_a_startup_refusal_keeps_the_app_from_serving(self) -> None:
        refusal = RuntimeError("ALLOWED_ORIGINS=* is refused in distributed mode")
        with patch.object(api, "validate_startup", AsyncMock(side_effect=refusal)), patch.object(
            container, "close", AsyncMock()
        ):
            with self.assertRaises(RuntimeError) as caught:
                with TestClient(api.app):
                    self.fail("served a request after a refused startup")
        self.assertIs(caught.exception, refusal)


if __name__ == "__main__":
    unittest.main()
