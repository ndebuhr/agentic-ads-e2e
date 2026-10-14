---
name: google-ads-geo-targets
description: >-
  Finds Google Ads geo target IDs offline (countries, states, counties, cities,
  ZIP codes, neighborhoods) in a bundled copy of Google's published list, with
  no sign-in or API call, and explains target types and location options. Use
  this skill whenever a campaign needs location IDs, the user names places to
  target or exclude, or asks about presence versus interest targeting.
---

# Google Ads Geo Targets Skill

Campaign specs list locations as numeric criterion IDs, such as `2840` for the
United States. This skill bundles Google's full geo targets list as a CSV and
looks IDs up with one-line `grep` searches: no `~/google-ads.yaml`, no API
quota, no network.

```bash
C=.agents/skills/google-ads-geo-targets/assets/geotargets.csv
```

The CSV is 23 MB. Never open or load the whole file; search it. Each line is
`"ID","Name","Canonical Name","Parent ID","Country Code","Target Type",Status`.

## Workflow

### 1. Resolve Each Place
```bash
grep -i '"Boulder County,Colorado,' $C      # by canonical name (place,state,country)
grep -i '"Austin,Texas,United States"' $C   # one exact place
grep '^"[0-9]*","78701",' $C                # by ZIP code
grep '^"2840",' $C                          # by ID, to check one
```
* Names repeat across states and countries, so search the canonical name
  (`Place,State,Country`) rather than the bare name, and check the type and
  canonical name in each matching line.
* Don't target entries whose status is `Removal Planned`.

### 2. Build Areas from the Hierarchy
The fourth field is the parent ID, so one search lists one level of the tree:
```bash
grep ',"21176","US","County",Active' $C     # every county in Texas (21176)
```
Use it to turn a region into a county or ZIP list, and to check a service area
for gaps at its edges.

### 3. Choose Types and Location Options
`assets/index.md` is an Open Knowledge Format catalog of the pages in
`assets/`. Read the ones you need:
* `assets/target-types.md`: which type fits (state, county, city, ZIP,
  neighborhood) and what the list leaves out.
* `assets/location-options.md`: presence versus presence-or-interest,
  exclusions, and overlap between targets.
* `assets/countries.md` and `assets/us-states.md`: ready tables of country and
  US state IDs.

### 4. Hand Off
Put the IDs in the campaign spec's `locations`, for example in the
`google-ads-search-campaigns` skill. Its create `--dry-run` validates every ID
with Google before anything is written.

## Notes
* US Nielsen DMA regions (metros such as "Denver CO") aren't in the list. Use
  `search_campaign.py geo-suggest` for those, or target the metro's counties.
* Use `geo-suggest` too when the user wants reach estimates, which the list
  doesn't have.
* To update the copy, see "Updating" in `assets/geo-target-constants.md`. IDs
  are stable between releases.
