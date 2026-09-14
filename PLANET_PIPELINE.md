# Small build jobs, one planet.bin, Hugging Face storage

Target clarified on 2026-09-14: perform conversion in chunks that fit the worker
compute budget, assemble one complete Navit binfile, and test hosting it on
Hugging Face Storage Buckets. The regional build pipeline may change and preserve
extra merge information. Existing regional `.bin` releases are useful fixtures,
but are not the required intermediate format for this pipeline.

The target is the existing regional GitHub Actions runners (`ubuntu-latest`),
confirmed by the user. Public-repository Linux runners currently specify 4 CPUs,
16 GB RAM and 14 GB SSD, with a six-hour job execution limit. The existing regional
workflow passes `--slice-size 6442450944` (6 GiB) to maptool; that slice size is not
a cap on total process memory. The old planet workflow's self-hosted runner is
not the target.

Initial engineering budgets are 12 GiB peak job RAM, at most 10 GB task scratch
(also requiring measured free space with 2 GB reserved), and five hours active
work per job, leaving time for setup, checkpointing and cleanup. These are
targets to measure, not demonstrated limits. Chunk sizes must account for source,
expanded temporary records, sort runs, indexes and output simultaneously. Start
with 64 MiB multipart buffers and one in-flight upload; tune after measurement.
Global stages must also fit the budget; moving all topology processing to one
final worker would defeat the design. If streaming assembly exceeds one job's
time allowance, checkpoint multipart state and byte offsets for continuation.

Sources: [runner specifications](https://docs.github.com/en/actions/reference/runners/github-hosted-runners),
[job limits](https://docs.github.com/en/actions/reference/limits).

## Build contract

1. **Freeze the source.** Start from one OSM snapshot, a pinned maptool build and
   one mapping configuration. Store their identifiers and hashes in a build
   manifest. Completeness includes the missing regions in today's release set.
2. **Resolve topology before discarding identity.** Preserve original node IDs
   and coordinates, way IDs and versions, ordered node occurrences, routing
   attributes, and complete restriction relation members. Use external sorting
   or partitioned reductions to establish junctions and feature ownership.
   A fixed geographic halo cannot guarantee complete long ways or relations;
   fetch their dependency closure or resolve them in a dedicated global stage.
3. **Convert bounded work units.** Workers emit canonical item/tile data plus
   sidecars containing identity, ownership, boundary dependencies and hashes.
   Context from adjacent chunks is read-only: each emitted feature/segment has
   exactly one owner. Oversized work units must be subdivided or streamed, rather
   than being retried on a worker with the same insufficient budget.
4. **Resolve global products.** Handle administrative/search indexes, coastlines
   and multipolygons across chunk boundaries. These need explicit stages; road
   deduplication alone cannot make the map complete or visually correct.
5. **Plan the binfile directory.** Build a deterministic tile catalog and assign
   member numbers before serializing references. Workers can then emit final,
   compressed tile payloads. The assembler consumes tiles in catalog order and
   emits their headers, the combined root/index, the central directory and ZIP64
   trailer. Its local working set should be a bounded input buffer, upload part
   buffer and disk-backed directory metadata, not the entire planet file.
6. **Upload and validate.** Stream the final object through multipart upload,
   then verify ranges and representative tile CRCs. Publish a build manifest
   only after assembly and validation succeed. Failed uploads must be aborted or
   explicitly tracked for resume.

The first correctness target is equivalence to a single maptool conversion of
the same complete source fixture, with independent expected route outcomes for
prohibited turns, one-way streets and grade-separated crossings. Known Navit
reader/routing limitations must not be mistaken for correct OSM behavior merely
because two builds agree.

The current `contrib/binfile` merger and its native routing tests remain useful
regression tools. Its whole-input SQLite reconciliation and same-length inactive
records are not the final planned-tile assembly architecture. New intermediates
should preserve node identities so valid cases currently rejected as ambiguous
can be resolved without coordinate guesses.

The fork's `NavitZip` writer now accepts forward-only sinks and can copy verified
precompressed tiles with at most 1 MiB per read, spooling only the directory to
disk. Short-write and payload-integrity tests cover this primitive. The trusted
tile catalog, distributed topology stages, multipart sink/checkpointing and
planet-scale measurements are still to be implemented; the legacy merge CLI
continues to stage a local output file.

## Hugging Face constraints checked against current documentation

* Storage Buckets expose S3 through `https://s3.hf.co/<namespace>`, using path-style
  bucket addressing and region `us-east-1`. The S3 gateway applies to buckets,
  not model/dataset repositories.
* Multipart uploads are supported; `UploadPartCopy` is not. The assembler must
  read and upload final bytes. Stored build chunks cannot be assumed to support
  server-side concatenation. Build chunks and upload parts need not have the
  same boundaries.
* The documented client settings disable optional request/response trailing
  checksum handling with `when_required`. Verify our own hashes in the build
  manifest. Multipart ETags must not be assumed to be whole-file MD5 hashes.
* Downloads may redirect to a CDN. For boto3/botocore the gateway documents a
  proxy path. Actual byte-range response correctness and bandwidth amplification
  still require an integration test against the selected bucket.
* Buckets are mutable and have no object versioning. GetObject does not honor
  If-Match/If-None-Match preconditions. Use application-level immutable keys such
  as `builds/<snapshot>/<build-id>/planet.bin`; never overwrite an object while
  clients are reading it. Update a small discovery manifest to announce a new
  completed build.
* HF's Xet chunk storage can deduplicate bytes and serve partial reads. It does
  not resolve OSM topology, feature ownership or Navit tile references. Stable
  serialization and timestamps should help avoid needless byte changes, but
  actual upload/storage savings need measurement.

Sources: [S3 compatibility](https://huggingface.co/docs/hub/storage-buckets-s3),
[Storage Buckets](https://huggingface.co/docs/hub/storage-buckets),
[Xet](https://huggingface.co/docs/hub/en/xet/index).

## Reading the hosted planet

The checked Navit source opens binfiles as local files, seeks to the ZIP trailer
and directory, then seeks to individual compressed tiles. Its current binfile
reader does not implement a direct S3/HTTPS random-access file backend.

For the first integration test, mount the bucket with `hf-mount` and point the
existing reader at the mounted `planet.bin`. HF documents lazy NFS/FUSE access.
Test file open permissions (Navit currently requests O_RDWR), seek behavior,
cache limits, cold versus warm reads, and whether mmap causes unwanted prefetch.
This is a candidate approach, not yet verified compatibility. A native HTTPS
range cache can be considered separately if mounting does not suit the target
Navit platforms.

[HF access patterns](https://huggingface.co/docs/hub/storage-buckets-access).

## Next acceptance milestone

Build adjoining chunks from a shared small source snapshot, including a genuine
border junction, a same-coordinate/different-node case, a via-way restriction,
and a polygon with holes crossing the partition. Compare the assembled file's
features, searches and native route outcomes with the monolithic reference.
Then upload that small file to the selected HF bucket, verify explicit ranges,
and run the same Navit queries through lazy mounted storage. Measure peak RAM,
scratch use, elapsed time, bytes transferred and request counts. Scale only once
the correctness and resource measurements pass.

`scripts/probe_hf_ranges.py` prepares the bounded byte-range verification portion
of this test. It does not upload or mutate objects. Supply the selected namespace,
bucket and immutable key, a local reference file, and S3 credentials through the
standard AWS credential mechanism. A real bucket has not yet been selected or
tested in this workspace.

With boto3 installed and HF-issued S3 credentials configured:

```sh
python3 scripts/probe_hf_ranges.py --namespace YOUR_NAMESPACE --bucket YOUR_BUCKET --key builds/BUILD_ID/planet.bin --reference output/combined.bin
```

The probe checks the beginning, tail, interior and (for large objects) offsets
around 4/8 GiB, reading at most eight 64 KiB samples plus one excess-byte check
per response. It requires HTTP 206 and exact Content-Range/Content-Length values,
checks bytes against the local file and closes rejected responses without
consuming a full object. HEAD before/after catches some concurrent modifications;
it does not provide snapshot isolation. Reported request counts are logical API
calls, excluding SDK retries, and sampled bytes exclude protocol overhead or
gateway/CDN amplification. Full tile CRC checks and mounted Navit tests remain
separate acceptance steps. Offline tests do not establish HF compatibility.
