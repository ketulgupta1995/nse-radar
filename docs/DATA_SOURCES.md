# Data sources: verification log

These are the facts behind SPEC §3. When a ticket worker confirms or corrects something, they add a dated line here.

## Verified 2026-11-09 (planner probe)
- `ind_nifty500list.csv`: HTTP 200, 501 rows (header + 500). Fixture: `backend/tests/fixtures/sources/nse_archives/nifty500list.csv`.
- UDiFF bhavcopy for 2026-11-06: HTTP 200, a 208 KB zip. Header: `TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,XpryDt,FininstrmActlXpryDt,StrkPric,OptnTp,FinInstrmNm,OpnPric,HghPric,LwPric,ClsPric,LastPric,PrvsClsgPric,UndrlygPric,SttlmPric,OpnIntrst,ChngInOpnIntrst,TtlTradgVol,TtlTrfVal,TtlNbOfTxsExctd,SsnId,NewBrdLotQty,Rmks,Rsvd1..4`. Fixture (5 EQ rows): `fixtures/sources/nse_bhav/bhav_udiff_20261106.csv`.
- Old bhavcopy for 2015-01-02: HTTP 200. Header: `SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,TOTTRDQTY,TOTTRDVAL,TIMESTAMP,TOTALTRADES,ISIN,` (note the trailing comma). Fixture: `fixtures/sources/nse_bhav/bhav_old_20150102.csv`.
- `www.nseindia.com/` homepage: **HTTP 403**. The `/api/*` endpoints below still returned 200 in the probe without homepage cookies:
  - `corporate-announcements?index=equities&symbol=TCS`: 200, 2.6 MB (full history). Keys seen: `an_dt`, `attchmntFile`, `attchmntText`, …
  - `corporates-corporateActions?index=equities&symbol=TCS`: 200. Keys: `symbol, comp, series, exDate ("14-Oct-2026"), recDate, subject ("Interim Dividend - Rs 12 Per Share"), faceVal, isin, bcStartDate, bcEndDate, ndStartDate, ndEndDate`.
  - `corporates-financial-results?index=equities&period=Quarterly&symbol=TCS`: 200, 162 items. Fixture (3 items): `fixtures/sources/nse_api/financial_results_TCS.json`. It includes the `xbrl` URL.
- Screener `company/TCS/consolidated/`: HTTP 200, 284 KB, with sections `quarters`, `profit-loss`, `ratios`, `shareholding`, and labels Market Cap / Stock P/E / ROCE / ROE / Book Value / Dividend Yield. Fixture: `fixtures/sources/screener/TCS_consolidated.html`.


## Unverified (the worker checks and records the result)
- announcements `from_date`/`to_date` params
- `ind_close_all_{DDMMYYYY}.csv`
- yfinance `^CRSLDX` = Nifty 500
- RSS feed URLs
- the exact XBRL element names

## T013 manual check (2026-11-09)
- `nsearchives.nseindia.com/content/indices/ind_nifty500list.csv` with the **honest User-Agent** (`stock-tools/0.1 …`): **HTTP 200**, 501 data rows (not 500). The job `universe.nse_archives` ran through the app and set `in_universe=1` for 501 symbols. No fallback needed for the universe.

## T014 manual check (2026-11-09)
- UDiFF bhavcopy with the **honest User-Agent**: HTTP 200 for 2026-11-06 (2,746 EQ bars), 2026-11-09 and 2026-11-08; 404 for Sat 2026-11-07. Old format 2015-01-02: HTTP 200, 1,450 EQ bars. No fallback needed.
- 2026-11-08 is a **Sunday** and has a real file (3,551 lines, TradDt 2026-11-08): the Diwali Muhurat trading session. NSE also holds occasional special Saturday sessions. Weekday-only key selection (§3.4) will not fetch these.

## T015 manual check (2026-11-09)
- `www.nseindia.com/api/corporates-corporateActions` with the **honest User-Agent**: HTTP 200 for TCS, RELIANCE, INFY, HDFCBANK. No fallback needed.
- **Without `from_date`/`to_date` the API returns only the latest 20 rows** (INFY lost its 2014 split and 2015 bonus). With `from_date=01-01-2010&to_date=DD-MM-YYYY` INFY returns 39 rows including `02-Dec-2014`, `15-Jun-2015`, `04-Sep-2018`. The adapter always sends that range. (The date params are now **verified** for this endpoint.)
- Parsed OK: RELIANCE bonus 0.5 (2017, 2024), INFY bonus 0.5 (2018), HDFCBANK split 0.2 (2011), 0.5 (2019), bonus 0.5 (2025). No `unparsed` subjects seen.

## T016 manual check (2026-11-09)
- yfinance 1.8.0 works unthrottled-by-us at 1 call/s: TCS.NS bars (10 rows), INFY.NS splits (Yahoo lists the 2018 bonus as "Split 2:1"), `^CRSLDX` index (10 rows).
- **`^CRSLDX` is the Nifty 500**: Yahoo closes 23456.95 (2026-11-06) and 23567.0 (2026-11-09) match NSE's `ind_close_all` file exactly.
- **`ind_close_all_{DDMMYYYY}.csv` is now verified** (HTTP 200, honest UA) for 06112026 and 09112026. Header: `Index Name,Index Date,Open Index Value,High Index Value,Low Index Value,Closing Index Value,Points Change,Change(%),Volume,Turnover (Rs. Cr.),P/E,P/B,Div Yield`. The row to use is `Nifty 500` (index date `DD-MM-YYYY`, close in column 6). Note the name is `Nifty 500`, not `NIFTY 500`.

## T032 manual check (2026-11-09)
- `nsearchives.nseindia.com/corporate/xbrl/INDAS_117182_1341298_09012025093940.xml` (TCS consolidated Q3 FY25) with the **honest User-Agent**: HTTP 200, 69 KB. Saved as `fixtures/sources/nse_api/xbrl_sample.xml`. No fallback needed.
- **Element names** (namespace `in-bse-fin`, matched by local name): `RevenueFromOperations`, `OtherIncome`, `Income`, `Expenses`, `ProfitBeforeTax`, `ProfitLossForPeriod`, `ProfitOrLossAttributableToOwnersOfParent`, `BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations`.
- **Units:** `unitRef="INR"` with full rupees (`decimals="-7"`), so crore = value / 1e7. EPS uses `INRPerShare` (no conversion).
- **Contexts:** the document has several duration contexts with the **same start and end dates**: `OneD` = the quarter (revenue 63,973 cr) and `FourD` = year to date (19,084 cr). Dates alone can't tell them apart, so the parser takes dimensionless contexts matching the dates and prefers the id `OneD`. Contexts with a `scenario` (segments, expense details) are ignored.
- **Net profit** uses `ProfitOrLossAttributableToOwnersOfParent` (12,380 cr, after minority) and falls back to `ProfitLossForPeriod` (12,444 cr). Standalone filings are expected to use the fallback (*unverified*).
- Bank / non-Ind-AS-new revenue names (`Revenue`, `InterestEarned`) are *unverified* guesses; a failed match shows as a `parse_error` quarter.
- `quarters()` downloads **one filing per period** (consolidated preferred, else standalone) to halve requests.

## T039 manual check (2026-11-09)
- `www.nseindia.com/api/corporate-announcements?index=equities&symbol=TCS&from_date=01-11-2026&to_date=09-11-2026` with the **honest User-Agent**: HTTP 200, **3 items**. Without the date params the same endpoint returned **3,385 items** back to 01-Apr-2008. **`from_date`/`to_date` (`DD-MM-YYYY`) do filter server-side**, so no client-side `since` filtering is needed for volume (the adapter still drops older rows defensively) and the `all` variant keeps `max_items` 500.
- **Item keys:** `an_dt` ("09-Nov-2026 17:12:15", IST), `attchmntText`, `attchmntFile` (PDF URL on nsearchives), `desc` (short subject), `attFileSize`, `bflag`, `csvName`, `difference`, `dt`, `exchdisstime`, `fileSize`, `hasXbrl`, `old_new`, `orgid`, `seq_id`, `smIndustry`, `sm_isin`, `sm_name`, `sort_date`, `symbol`, `voiceSummary`, `voiceUrl`.
- `desc` is a short, often generic subject ("Updates", "General Updates", "Analysts/Institutional Investor Meet/Con. Call Updates", "Copy of Newspaper Publication"); the informative sentence is in `attchmntText`. The category keywords are matched on headline + body, so this still categorizes correctly.
- Fixture: 5 items in `fixtures/sources/nse_api/announcements_TCS.json`.

## T040 manual check (2026-11-09)
All three default RSS feeds fetched once with the **honest User-Agent**; all returned HTTP 200 and parsed cleanly (no feedparser `bozo` flag). Entry keys: `title`, `link`, `summary`, `published` (RFC-822 with offset).
- ET Markets `…/markets/rssfeeds/1977021501.cms`: 50 entries, all dated 2026-11-09. **Live.**
- Business Standard `…/rss/markets-106.rss`: 35 entries, 2026-11-08 to 2026-11-09. **Live.** It has extra `bs_*` and `media_content` keys that we ignore.
- Moneycontrol `…/rss/latestnews.xml`: HTTP 200 but 15 entries **all dated 2024-04-23**: the feed is **stale**, so it was **removed from `DEFAULT_SETTINGS`**. (Existing databases keep the old setting value; edit it in Settings.)

## T044 `claude --help` check (2026-11-09)
- **Tools off:** `--tools ""` (help text: `Use "" to disable all tools`; `"default"` = the normal set). Used by `claude_cli`. `--allowedTools`/`--disallowedTools` also exist but are not used.
- **Output:** `-p --output-format json` returns a JSON object whose `result` field is the reply text. Verified 2026-11-09 with a real call through `claude_cli` (CLI 2.1.319, model haiku, env stripped, `--tools ""`): prompt "Reply with exactly the word: pong" → `"pong"`.
- Other flags used: `--model <model>`; the prompt goes on stdin.

## Trendlyne research reports (checked 2026-11-27, from the owner's laptop)
- Page `https://trendlyne.com/research-reports/all/`, then `?page=N`. Server-rendered table `#brokerTable`; about 20 rows on page 1, 10 on later pages. HTTP 200 with the **honest User-Agent**.
- `robots.txt`: this path is not disallowed for `*`; crawl delay 1 s. Our policy is 3 s, 5 pages, once a day. Report PDFs and `/get-document/` are login-only or disallowed and are never fetched.
- On Sell rows `Upside(%)` is published **unsigned** (target below price, still a positive number). Stored as published; the page shows no "+".
- **Terms** (`/terms/`) forbid keeping the site's information in a searchable database without written permission. The owner was told this on 2026-11-27 and chose to use it for personal use only. Don't widen it (no backfill, no sharing). Test fixtures are made up because the repo is public.
- **GitHub Actions is refused:** the first live run (2026-11-27) got HTTP 405, while the owner's laptop got 200. The adapter treats 405 as a refusal, so the source pauses itself.
