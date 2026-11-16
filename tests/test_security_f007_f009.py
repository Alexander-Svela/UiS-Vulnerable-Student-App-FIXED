"""Offline regression checks for F-007 and F-009. Run: python -m unittest discover -s tests"""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from fastapi import HTTPException
from app.routes import admin_routes, utility_routes


class F007Tests(unittest.TestCase):
    @patch.object(admin_routes, "run_query")
    @patch.object(admin_routes, "get_user_from_session")
    def test_student_cannot_modify_grade_even_with_forged_role(self, user, query):
        user.return_value = {"id": 4, "role": "student"}
        with self.assertRaises(HTTPException) as error:
            admin_routes.update_grade(None, 2, "A", "changed")
        self.assertEqual(error.exception.status_code, 403)
        query.assert_not_called()

    @patch.object(admin_routes, "run_query")
    @patch.object(admin_routes, "get_user_from_session")
    def test_teacher_can_modify_grade(self, user, query):
        user.return_value = {"id": 2, "role": "teacher"}
        response = admin_routes.update_grade(None, 2, "A", "approved")
        self.assertEqual(response.status_code, 303)
        query.assert_called_once()


class MockResponse:
    status = 200
    headers = {"Content-Type": "text/plain"}
    def read(self, *args, **kwargs): return b"public resource"
    def close(self): pass


class MockPool:
    def __init__(self, *args, **kwargs): self.kwargs = kwargs
    def request(self, *args, **kwargs): return MockResponse()
    def close(self): pass


class F009Tests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"RESOURCE_IMPORT_ALLOWED_HOSTS": "example.com"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_internal_url_rejected(self):
        with self.assertRaises(ValueError):
            utility_routes.fetch_external_resource("http://backend:8000/health")

    def test_non_allowlisted_host_rejected(self):
        with self.assertRaises(ValueError):
            utility_routes.fetch_external_resource("https://other.example/private")

    @patch.object(utility_routes.socket, "getaddrinfo", return_value=[(2, 1, 6, '', ('127.0.0.1', 443))])
    def test_allowlisted_hostname_resolving_to_loopback_is_rejected(self, _):
        with self.assertRaises(ValueError):
            utility_routes.fetch_external_resource("https://example.com/")

    @patch.object(utility_routes.urllib3, "HTTPSConnectionPool", MockPool)
    @patch.object(utility_routes.socket, "getaddrinfo", return_value=[(2, 1, 6, '', ('93.184.215.14', 443))])
    def test_public_approved_host_still_works(self, _):
        self.assertEqual(utility_routes.fetch_external_resource("https://example.com/article"), "public resource")


if __name__ == "__main__": unittest.main()
