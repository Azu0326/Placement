"""Local .env loading: missing file is fine; process environment wins."""

from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase
from dotenv import load_dotenv


class LocalEnvLoadTests(SimpleTestCase):
    def test_missing_env_file_is_a_noop(self):
        with TemporaryDirectory() as tmp:
            self.assertFalse(load_dotenv(Path(tmp) / ".env"))

    def test_existing_process_environment_is_not_overwritten(self):
        key = "SCRAPOS_DOTENV_OVERRIDE_TEST"
        os.environ[key] = "from-process"
        try:
            with TemporaryDirectory() as tmp:
                (Path(tmp) / ".env").write_text(f"{key}=from-file\n", encoding="utf-8")
                self.assertTrue(load_dotenv(Path(tmp) / ".env"))
            self.assertEqual(os.environ[key], "from-process")
        finally:
            os.environ.pop(key, None)

    def test_file_fills_only_unset_variables(self):
        key = "SCRAPOS_DOTENV_FILL_TEST"
        os.environ.pop(key, None)
        try:
            with TemporaryDirectory() as tmp:
                (Path(tmp) / ".env").write_text(f"{key}=from-file\n", encoding="utf-8")
                self.assertTrue(load_dotenv(Path(tmp) / ".env"))
            self.assertEqual(os.environ[key], "from-file")
        finally:
            os.environ.pop(key, None)
