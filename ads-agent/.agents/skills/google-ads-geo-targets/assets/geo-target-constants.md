---
type: Dataset
title: Geo target constants
description: The US part of Google's published list of targetable locations (about 64,000), with its columns, statuses, how often it changes, how to search it, and how to update it.
resource: https://developers.google.com/google-ads/api/data/geotargets
tags: [google-ads, geo-targeting, reference-data]
sources:
  - id: geotargets
    resource: https://developers.google.com/google-ads/api/data/geotargets
    title: Google Ads API geo targets
    author: Google
    last_modified: 2026-08-12
---
# Geo target constants

Every location a Google Ads campaign can target has a numeric criterion ID, such as `2840` for the United States. Campaign specs list these IDs under `locations`. Google publishes the full list of about 274,000 locations as a CSV, refreshed every month or two.[^geotargets] This bundle keeps its 64,284 US entries, about a quarter. Release in use: 2026-08-12

## Searching

[geotargets.csv](/geotargets.csv) is the US part of the release named above, committed as plain text (5.4 MB). Search it with one-line `grep`s from the repository root; never open or load the whole file.

```bash
C=.agents/skills/google-ads-geo-targets/assets/geotargets.csv
grep -i '"Austin,Texas,United States"' $C   # one place, by canonical name
grep -i '"Travis County,Texas,' $C          # a place and everything inside it
grep '^"[0-9]*","78701",' $C                # by postal code
grep '^"2840",' $C                          # by ID
grep ',"21176","US","County",Active' $C     # children: every county in Texas (21176)
```

Each line is `"ID","Name","Canonical Name","Parent ID","Country Code","Target Type",Status`. Use the API's `geo-suggest` command only for reach estimates, or for place types this file leaves out (see [Target types](/target-types.md)).

## Columns

| Column | Meaning |
|---|---|
| Criteria ID | The ID to put in a campaign's `locations` |
| Name | The place's own name, for example `Austin` |
| Canonical Name | The full path from place to country, for example `Austin,Texas,United States`; names can repeat, canonical names don't |
| Parent ID | The ID of the enclosing location, so the list forms a tree (see [Target types](/target-types.md)) |
| Country Code | ISO 3166-1 alpha-2, for example `US` |
| Target Type | `Country`, `State`, `City`, `Postal Code`, and others |
| Status | `Active`, or `Removal Planned` |

## Statuses and change

`Removal Planned` means Google will retire the target; don't use one in a new campaign. About 3% of the US entries (2,200 in release 2026-08-12) have this status; check the last field of each matching line.

IDs are stable. Across the whole list, between releases 2026-07-16 and 2026-08-12, no entries were added or removed and no IDs or statuses changed; 846 canonical names, 176 names, and 15 parent IDs were edited. Countries, states, and counties essentially never change, so their IDs are safe to reuse; brand-new postal codes and neighborhoods are where a stale copy can fall short. A campaign create's `--dry-run` validates every ID with Google, so a retired target is caught before anything is written.

## Updating

Google publishes a new release every month or two; the source page lists them. To move to a newer one, replace the CSV, then update the release date in this page's text and the `last_modified` of the `geotargets` source on this page and the tables, and add an entry to the [log](/log.md). Find the newest file name (`geotargets-YYYY-MM-DD.csv.zip`) on the source page, then:

```bash
curl -sL https://developers.google.com/static/google-ads/api/data/geo/geotargets-YYYY-MM-DD.csv.zip | funzip \
  | grep -E '^Criteria ID,|,"US",' > .agents/skills/google-ads-geo-targets/assets/geotargets.csv
```

To keep another country's places too, add its code to the filter, for example `,"(US|CA)",`. Regenerate the [US states](/us-states.md) table from the CSV, and the [countries](/countries.md) table from the full download, if any of their rows changed.

## License

The data is published by Google under the Creative Commons Attribution 4.0 License.[^geotargets]

[^geotargets]: Google Ads API, "Geo targets", https://developers.google.com/google-ads/api/data/geotargets
