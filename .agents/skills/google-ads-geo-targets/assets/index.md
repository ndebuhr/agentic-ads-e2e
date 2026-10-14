---
okf_version: "0.2"
---
# Google Ads geo targets

Location targeting for Google Ads campaigns: the IDs Google Ads uses for countries, states, cities, postal codes, and other places, and how to target with them.

To find IDs, search [the CSV](/geotargets.csv) with a one-line `grep`, from the repository root:

```bash
grep -i '"Boulder County,Colorado,' .agents/skills/google-ads-geo-targets/assets/geotargets.csv
```

The CSV is 23 MB: always search it, never open or load the whole file. [Geo target constants](/geo-target-constants.md) has more searches.

## Data

- [Geo target constants](/geo-target-constants.md): Google's published list of every targetable location (about 274,000), with its columns, statuses, how often it changes, how to search it, and how to update it.
- [geotargets.csv](/geotargets.csv): the list itself (23 MB). Search it; don't open it.
- [Countries](/countries.md): criterion IDs for every active country target.
- [US states](/us-states.md): criterion IDs for the 50 US states and the District of Columbia.

## Concepts

- [Target types](/target-types.md): the kinds of locations (country, state, county, city, postal code, neighborhood, and others), how they nest, and which to choose.
- [Location options](/location-options.md): presence versus interest targeting, excluded locations, and avoiding overlapping targets.
