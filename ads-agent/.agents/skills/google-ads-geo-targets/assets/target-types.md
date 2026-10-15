---
type: Concept
title: Target types
description: The kinds of locations (country, state, county, city, postal code, neighborhood, and others), how they nest, and which to choose.
tags: [google-ads, geo-targeting]
sources:
  - id: geotargets
    resource: https://developers.google.com/google-ads/api/data/geotargets
    title: Google Ads API geo targets
    author: Google
---
# Target types

Each entry in the [geo target constants](/geo-target-constants.md) has a `Target Type`. Each entry's `Parent ID` points to the location that contains it, so the types form a tree: country, then state or province, then county or region, then city, then postal code or neighborhood. Searching for `,"PARENT_ID",` in the parent field lists one level of that tree (see [Geo target constants](/geo-target-constants.md)).

## Counts in release 2026-08-12

The bundled CSV holds the United States column; the worldwide column is Google's full list.

| Type | Worldwide | United States |
|---|---|---|
| Postal Code | 132,824 | 33,371 |
| City | 65,483 | 19,676 |
| Municipality | 23,415 | 1,947 |
| District | 18,303 | – |
| Neighborhood | 15,237 | 4,911 |
| County | 3,706 | 3,098 |
| Province | 1,301 | – |
| Region | 1,165 | 2 |
| Congressional District | 689 | 684 |
| Airport | 395 | 174 |
| State | 275 | 51 |
| Country | 219 | – |
| University | 219 | 169 |

Smaller types include Borough, Canton, Colloquial Area, National Park, Prefecture, Territory, and TV Region (18 UK and similar regions). The type names are Google's and vary by country; a few appear in lowercase.

## What's not in the file

US Nielsen DMA regions (metro areas, such as "Denver CO") aren't in the published CSV. To target a DMA, resolve it with the API's `geo-suggest`, or target its counties instead (list the state's counties, then keep the ones in the metro).

Radius targeting (a distance around an address or point) doesn't use these IDs at all. It's a separate proximity criterion.

## Choosing a type

- **Country or state** for national or statewide sellers. One ID covers everything inside it.
- **Counties** for a delivery or service area defined by region. They change rarely and cover rural areas that city targets miss.
- **Cities** when the service area really is the city limits. A city target covers only that city, not its suburbs.
- **Postal codes** for precise service areas, such as a delivery zone. They take more IDs to cover an area, and they're where new entries appear most often.
- **Neighborhoods, airports, universities** for narrow local campaigns, usually alongside a broader target with its own bid adjustments.
