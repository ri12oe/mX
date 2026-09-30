"""Shared test setup. Runs before any test module imports the app.

Sets a known test key so tests never depend on the developer's .env.
Environment variables take priority over .env in pydantic-settings.
"""
import os

TEST_API_KEY = "test-key-" + "x" * 40

os.environ["MX_API_KEY"] = TEST_API_KEY
