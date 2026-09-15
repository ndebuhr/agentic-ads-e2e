---
name: google-ads-campaign-summary
description: >-
  Summarizes Google Ads campaigns in structured markdown tables. Use this skill
  whenever the user asks to summarize, list, display, or review campaigns, their
  statuses, budgets, channel types, bidding strategies, and key performance metrics.
---

# Google Ads Campaign Summary Skill

This skill provides a standard runbook for querying and summarizing Google Ads campaigns in formatted markdown tables using the `google-ads-mcp` tools.

## Workflow

### 1. Identify Customer ID
* If the user specifies a customer ID, normalize it to digits only (e.g., convert `123-456-7890` to `1234567890`).
* If no customer ID is provided, call the MCP tool `customers_list_accessible_customers` on server `google-ads-mcp`.
  * If a single customer ID is returned, use that account ID.
  * If multiple customer IDs are returned, ask the user which customer account they wish to summarize or list the accounts available.

### 2. Fetch Campaign Details
Use `call_mcp_tool` with `search_search`:
* **ServerName**: `google-ads-mcp`
* **ToolName**: `search_search`
* **Resource**: `campaign`
* **Fields**:
  * `campaign.id`
  * `campaign.name`
  * `campaign.status`
  * `campaign.primary_status`
  * `campaign.primary_status_reasons`
  * `campaign.serving_status`
  * `campaign.advertising_channel_type`
  * `campaign.bidding_strategy_type`
  * `campaign.campaign_budget`
  * `campaign.start_date_time`
* **Conditions**:
  * Default: `["campaign.status != 'REMOVED'"]`
  * If the user requested only active/enabled campaigns: `["campaign.status = 'ENABLED'"]`

### 3. Fetch Budgets
Query the `campaign_budget` resource to get daily amounts:
* **Resource**: `campaign_budget`
* **Fields**:
  * `campaign_budget.id`
  * `campaign_budget.name`
  * `campaign_budget.amount_micros`
  * `campaign_budget.period`
* Convert `amount_micros` to standard currency: `amount = amount_micros / 1,000,000`.

### 4. Fetch Performance Metrics
Query metrics for the campaigns:
* **Resource**: `campaign`
* **Fields**:
  * `campaign.id`
  * `metrics.impressions`
  * `metrics.clicks`
  * `metrics.ctr`
  * `metrics.cost_micros`
  * `metrics.average_cpc`
  * `metrics.conversions`
  * `metrics.conversions_value`
* **Date filtering**: If requested for a time period, specify date conditions (e.g. `segments.date BETWEEN 'YYYY-MM-DD' AND 'YYYY-MM-DD'`).

### 5. Format Output Tables

Present the summary clearly in two complementary tables:

#### Table 1: Campaign Configuration & Status
| Campaign Name | ID | Status | Serving Status | Channel Type | Bidding Strategy | Daily Budget |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |

#### Table 2: Performance Metrics
| Campaign Name | Impressions | Clicks | CTR | Cost | Avg CPC | Conversions |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |

* Format currency values to 2 decimal places with `$` symbol.
* Format percentages with `%` (e.g., `(ctr * 100).toFixed(2)%`).
* If `primary_status` is `LIMITED`, highlight the reason or note the status constraints underneath the table.
