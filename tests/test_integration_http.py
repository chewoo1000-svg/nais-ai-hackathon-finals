"""External metadata must fail closed and preserve public response provenance."""
# [작성: 0 이영 · Codex] 2026-10-01 KST — 실제 오류·과대 응답·비정상 JSON을 성공으로 저장하지 않도록 검증.
import unittest
import sys
from unittest.mock import MagicMock, patch
from core import integration_http as transport


class TransportTests(unittest.TestCase):
    def setUp(self):
        transport._CACHE.clear()

    def response(self, raw, status=200):
        connection = MagicMock()
        connection.getresponse.return_value.status = status
        connection.getresponse.return_value.read.return_value = raw
        return connection

    def fetch(self, raw, kind='json', status=200):
        with patch.object(transport, '_reserve_slot'), patch.object(transport.http.client, 'HTTPSConnection', return_value=self.response(raw, status)):
            return transport._request('zenodo.org', '/api/records/1', {}, kind)

    def test_provenance_and_cache_preserve_observation(self):
        first = self.fetch(b'{"id":1}')
        self.assertTrue(first['ok'])
        self.assertEqual(len(first['response_sha256']), 64)
        second = transport.get_json('zenodo.org', '/api/records/1')
        self.assertTrue(second['cached'])
        self.assertEqual(first['retrieved_at_kst'], second['retrieved_at_kst'])

    def test_no_external_or_sensitive_target(self):
        for host, path, params in [('localhost', '/x', {}), ('zenodo.org', '//bad', {}),
                                   ('zenodo.org', '/x', {'email': 'PRIVATE'}),
                                   ('zenodo.org', '/x', {'q': 'sk-' + 'a' * 30})]:
            with self.assertRaises(ValueError):
                transport.get_json(host, path, params)

    def test_http_error_is_not_empty_success(self):
        result = self.fetch(b'{"items":[]}', status=429)
        self.assertFalse(result['ok'])
        self.assertEqual(result['error'], 'HTTP_429')

    def test_nonfinite_duplicate_and_oversize_responses_fail(self):
        for raw in (b'{"x":NaN}', b'{"x":1,"x":2}', b'x' * (transport.MAX_BYTES + 1)):
            self.assertFalse(self.fetch(raw)['ok'])

    def test_external_xml_entity_is_rejected(self):
        self.assertFalse(self.fetch(b'<!DOCTYPE rss [<!ENTITY x SYSTEM "file:///private">]><rss>&x;</rss>', 'xml')['ok'])

    def test_deep_json_is_a_failure_response(self):
        depth = sys.getrecursionlimit() + 100
        result = self.fetch(b'[' * depth + b'0' + b']' * depth)
        self.assertFalse(result['ok'])
        self.assertEqual(result['error'], 'CONNECTION_OR_RESPONSE_ERROR')
        self.assertIsNone(result['data'])


if __name__ == '__main__':
    unittest.main()
