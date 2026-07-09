import unittest

from xtorage.commerce import Account, CommerceClient


class CommerceClientTests(unittest.TestCase):
    def test_http2_client_can_be_constructed(self) -> None:
        account = Account(
            owner_id="1",
            bearer="test-bearer",
            cookies={"auth_token": "test-auth", "ct0": "test-csrf"},
        )

        client = CommerceClient(account)
        try:
            self.assertFalse(client.client.is_closed)
        finally:
            client.close()


if __name__ == "__main__":
    unittest.main()
