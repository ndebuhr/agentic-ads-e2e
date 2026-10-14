---
type: Concept
title: Location options
description: Presence versus interest targeting, excluded locations, and avoiding overlapping targets.
tags: [google-ads, geo-targeting, campaign-settings]
sources:
  - id: location-options
    resource: https://support.google.com/google-ads/answer/1722038
    title: About advanced location options
    author: Google
---
# Location options

## Presence or interest

A campaign's location option decides who counts as "in" a targeted location:[^location-options]

- **Presence:** people who are, or regularly are, in the location. The API sets this with `positive_geo_target_type: PRESENCE`. The `google-ads-search-campaigns` skill uses it by default (`location_presence_only: true`). It's the right choice for local delivery and in-person services.
- **Presence or interest:** also people elsewhere who search about the location, for example someone in another state searching "hotels in Austin". This is Google's default and recommended option. Use it for travel, relocation, or gifts shipped into an area.

## Excluded locations

Excluded (negative) locations remove an area from a broader target, for example a whole state except one county the business doesn't serve. They take the same criterion IDs from the [geo target constants](/geo-target-constants.md). Exclusions work by presence: they keep out people likely to be in the excluded location.[^location-options]

## Avoiding overlap

- Don't target a location and a place inside it in the same campaign, such as a state and a city in it. The larger one already covers the smaller one, and the duplicate only complicates reporting and bid adjustments.
- Don't target the same place from two campaigns that bid on the same keywords. They compete in the same auctions.
- When a service area is a list of postal codes or counties, check the list against its parents' children (see [target types](/target-types.md)) so it has no gaps at the edges.

[^location-options]: Google Ads Help, "About advanced location options", https://support.google.com/google-ads/answer/1722038
