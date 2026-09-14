import io
from pathlib import Path
import tempfile
import unittest

from probe_hf_ranges import MAX_SAMPLE, probe, sample_ranges


class ShortReads(io.BytesIO):
    def __init__(self, data):
        super().__init__(data)
        self.bytes_read = 0

    def read(self, size=-1):
        if size < 0:
            raise AssertionError("Unbounded response read")
        data = super().read(min(size, 3))
        self.bytes_read += len(data)
        return data


class FakeS3:
    def __init__(self, data, mutate=None):
        self.data = data
        self.mutate = mutate
        self.bodies = []
        self.heads = 0

    def head_object(self, **kwargs):
        self.heads += 1
        return {"ContentLength": len(self.data), "ETag": "same"}

    def get_object(self, Bucket, Key, Range):
        start, end = map(int, Range.removeprefix("bytes=").split("-"))
        response = {
            "ResponseMetadata": {"HTTPStatusCode": 206},
            "ContentRange": f"bytes {start}-{end}/{len(self.data)}",
            "ContentLength": end - start + 1,
            "data": self.data[start : end + 1],
        }
        if self.mutate:
            self.mutate(response)
        response["Body"] = ShortReads(response.pop("data"))
        self.bodies.append(response["Body"])
        return response


class RangeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.reference = Path(self.tmp.name) / "map.bin"
        self.reference.write_bytes(bytes(range(256)) * 4)

    def run_probe(self, client):
        try:
            return probe(
                client, "test-bucket", "builds/test/map.bin", self.reference, 16
            )
        finally:
            self.assertTrue(all(body.closed for body in client.bodies))

    def test_correct_ranges_with_short_reads(self):
        client = FakeS3(self.reference.read_bytes())
        report = self.run_probe(client)
        self.assertEqual(report["verified_bytes"], 64)
        self.assertEqual(report["logical_get_requests"], 4)
        self.assertEqual(client.heads, 2)

    def test_ignored_range_is_rejected_before_read(self):
        client = FakeS3(
            self.reference.read_bytes(),
            lambda r: r.update(ResponseMetadata={"HTTPStatusCode": 200}),
        )
        with self.assertRaisesRegex(ValueError, "HTTP 206"):
            self.run_probe(client)
        self.assertEqual(client.bodies[0].bytes_read, 0)

    def test_incorrect_headers_are_rejected_before_read(self):
        for field, value in [
            ("ContentRange", "bytes 1-16/1024"),
            ("ContentLength", 1024),
        ]:
            with self.subTest(field=field):
                client = FakeS3(
                    self.reference.read_bytes(), lambda r: r.update({field: value})
                )
                with self.assertRaisesRegex(ValueError, "unexpected Content-"):
                    self.run_probe(client)
                self.assertEqual(client.bodies[0].bytes_read, 0)

    def test_oversized_body_is_bounded(self):
        client = FakeS3(
            self.reference.read_bytes(), lambda r: r.update(data=b"x" * 1024)
        )
        with self.assertRaisesRegex(ValueError, "body length"):
            self.run_probe(client)
        self.assertEqual(client.bodies[0].bytes_read, 17)

    def test_truncated_body_is_rejected(self):
        client = FakeS3(self.reference.read_bytes(), lambda r: r.update(data=b"x"))
        with self.assertRaisesRegex(ValueError, "body length"):
            self.run_probe(client)

    def test_wrong_bytes_are_rejected(self):
        client = FakeS3(self.reference.read_bytes(), lambda r: r.update(data=b"x" * 16))
        with self.assertRaisesRegex(ValueError, "bytes differ"):
            self.run_probe(client)

    def test_changed_object_is_rejected(self):
        class ChangingS3(FakeS3):
            def head_object(self, **kwargs):
                response = super().head_object(**kwargs)
                response["ETag"] = str(self.heads)
                return response

        with self.assertRaisesRegex(ValueError, "changed during"):
            self.run_probe(ChangingS3(self.reference.read_bytes()))

    def test_size_mismatch_makes_no_get_requests(self):
        client = FakeS3(b"short")
        with self.assertRaisesRegex(ValueError, "Remote size"):
            self.run_probe(client)
        self.assertEqual(client.bodies, [])

    def test_large_offsets_and_small_files(self):
        size = 66_098_454_713
        ranges = sample_ranges(size)
        self.assertTrue(any(start < 2**32 <= end for start, end in ranges))
        self.assertTrue(any(start == 2**32 for start, _ in ranges))
        self.assertEqual(ranges[-1][1], size - 1)
        self.assertLessEqual(
            sum(end - start + 1 for start, end in ranges), 8 * MAX_SAMPLE
        )
        self.assertEqual(sample_ranges(1), [(0, 0)])
        for size, width in [(0, 1), (100, 0), (100, MAX_SAMPLE + 1)]:
            with self.assertRaises(ValueError):
                sample_ranges(size, width)


if __name__ == "__main__":
    unittest.main()
