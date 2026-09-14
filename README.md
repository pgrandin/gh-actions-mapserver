# Navit Map Server

Pre-built [Navit](https://github.com/navit-gps/navit) maps, automatically converted daily from [Geofabrik](https://download.geofabrik.de/) OSM extracts.

## Getting a map

Go to the [latest release](https://github.com/navit-gps/gh-actions-mapserver/releases/latest) and download the `.bin` file for your region.

Files are named `<continent>-<region>-<date>.bin`, for example:

```
europe-france-alsace-2026-03-18.bin
north-america-us-california-2026-03-18.bin
asia-japan-2026-03-18.bin
```

## Using the map in Navit

Place the downloaded `.bin` file somewhere on your device and point Navit to it in your `navit.xml`:

```xml
<mapset enabled="yes">
  <map type="binfile" enabled="yes" data="/path/to/your-region.bin"/>
</mapset>
```

## Updates

A new release is published every day. Check the [releases page](https://github.com/navit-gps/gh-actions-mapserver/releases) for the latest build for your region.

## Combining regional maps

The intended planet build now uses bounded conversion jobs with merge metadata,
followed by streaming assembly and a Hugging Face storage test. See the
[planet pipeline design](PLANET_PIPELINE.md). The existing-binfile merger below
provides compatibility and regression tests for that work.

Current priority is proving map correctness; HF setup is deferred. The Navit
fork's [adjoining-chunk acceptance test](https://github.com/pgrandin/navit/blob/fix/binfile-overlap/contrib/binfile/README.md#reproducible-real-adjoining-chunk-proof)
now compares real overlapping OSM chunks with a monolithic conversion, including
features, native routes/searches and ZIP64 offsets beyond 4 GiB. This is a small
correctness proof, not yet a complete planet build within the runner budget.

The **Merge regional binfiles** workflow runs the conservative merger from
[pgrandin/navit](https://github.com/pgrandin/navit/tree/fix/binfile-overlap/contrib/binfile).
Select a fixed release date and comma-separated region prefixes. It downloads
those exact assets, verifies their SHA-256 hashes, and produces `combined.bin`
with a `combined.json` provenance report as a workflow artifact. It does not
publish a release or claim planet coverage.

The merger reconciles overlapping copies of a road when their geometry and
attributes agree but their intersection splits differ. It also rebases turn
restrictions to the normalized segments. Conflicting versions, incomplete ways,
or coincident vertices whose topology cannot be established from the source
binfiles stop the merge. See the merger's README for supported inputs and
remaining limitations, including polygon/coastline overlap handling.

The default selection is a small three-country smoke test. Select adjoining
regions explicitly when testing border routing. Large selections require enough
disk for source files, output, and the temporary topology database; hosted
runners are not sized for the full release's roughly 66 GB of source maps.

To run locally with the Navit fork checked out alongside this repository:

```sh
python3 scripts/merge_release.py --release 2026-09-14 --regions europe-monaco,europe-liechtenstein,europe-andorra --navit-source ../navit-src --output output/combined.bin
```

GitHub requires a manually dispatched workflow to exist on the repository's
default branch. Until this branch is merged, use the local command; push and
pull-request events run the downloader tests without downloading map assets.
