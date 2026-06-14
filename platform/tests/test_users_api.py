import unittest
from types import SimpleNamespace
from datetime import datetime

from app.api.v1 import users


class UsersApiTest(unittest.TestCase):
    def test_serialize_user_excludes_password_hash(self):
        raw_user = SimpleNamespace(
            id=1,
            username="admin",
            email="admin@traffic.local",
            role="admin",
            is_active=True,
            created_at=datetime(2026, 6, 1, 8, 0, 0),
            hashed_password="secret-hash",
        )

        payload = users.serialize_user(raw_user)

        self.assertEqual(payload["username"], "admin")
        self.assertEqual(payload["role"], "admin")
        self.assertNotIn("hashed_password", payload)


if __name__ == "__main__":
    unittest.main()
