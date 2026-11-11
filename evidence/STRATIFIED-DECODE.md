# Stratified payload decode — does the MO hold across the whole queue?

Follow-up to `MAY26-1009-CONCURRENCY-DECODE.md`. The six-report window showed a job-queue MO;
this pulls the thread wider — **51 reports across 20 sources**, spread over dates and both wrapped and
direct submissions — to test whether the pattern holds across the run and, specifically, whether the
economics/trading targets behave any differently from the rest.

**Method.** Report IDs selected from the local catalog (stratified: top sources × a few each, biased
toward `indirection`/`custom_program` rows that carry a task URL or script). Pages read on
urlquery.net; payloads reported verbatim. No requests were sent to any target — reader/proxy fetches
were performed by the original submitter at capture time. Fetched via three parallel read-only agents,
2026-09-24. 51/51 returned detail.

---

## The one-line finding

**The MO holds across every theme, and it is the MO of an instrumented, multi-domain web-retrieval
benchmark — not a trading operation.** Finance is one category among ~9. The two trading-adjacent
targets are (a) a price-comparison *retrieval* and (b) a *security probe* of a crypto exchange using
synthetic fixtures — capability evaluation on a financial endpoint, not profit-seeking.

---

## Decoded sample, grouped by theme (the point is the breadth)

### Economics / trade / public spending
| source | target | wanted | via | marker |
|---|---|---|---|---|
| UNCTAD | unctadstat-api | US.PCI cell `$select=Year,M6080` | httpbin base64 auto-POST | — |
| UNCTAD | unctadstat-api | PCI M6080, economies 624/854, 2005 | httpbin base64 auto-POST | — |
| UNCTAD | unctadstat-api | trade-in-services M0100/M0103, 2005–10 | httpbin base64 auto-POST (embeds **apim key**) | — |
| UNCTAD | unctadstat-api | gender tradable-industries M3763/M5080, 2020 | httpbin base64 auto-POST (**apim key**) | — |
| MAX budget | portal/login.max.gov | one SF-133 budget PDF `2374423602.pdf` (wiki-cited) | markdown.new (also tried `login.max.gov`) | — |
| USAspending | api.usaspending.gov | homepage → API root → federal account 075-8005 (VA) | direct (broad→specific escalation) | — |
| DataUSA | api.datausa.io | tesseract cubes listing | r.jina.ai | — |
| DataUSA | api.datausa.io | IPEDS completions (univ 153658) **+ XSS probe** `foo=<script>alert(document.cookie)</script>` | direct | — |
| DataUSA | api.datausa.io | IPEDS completions **+ SQLi probe** `foo=' OR 1=1--` | direct | — |
| SEC county | www.sec.gov | `county.json` file | md.succ.ai | — |
| Data for India | assets.dataforindia.com | chart `data.json`, **tested via img/script/iframe/object/preload/fetch** | httpbin base64 (`LOADTEST`) | LOADTEST |
| Data for India | assets.dataforindia.com | chart `data.json` via a Cloudflare Worker | workers.cloudflare.com/playground | cfbulk |

### Trading / markets  ← the hypothesis under test
| source | target | wanted | via | marker |
|---|---|---|---|---|
| Trading Economics / metals | httpbin (no live target) | **submits an answer table**: monthly metal prices CSV (Au/Ag/Pt/Pd/Rh, 2014 vs 2024) | httpbin base64 (CSV *data*, not a script) | — |
| Quidax (crypto) | ramp.quidax.io/api/ramp-proxy | **P1–P7 probe matrix**: txn fetch, OTP verify, KYC reset, wallet add/assign | httpbin base64 | e898 / E898\|P1.. |
| Quidax | ramp.quidax.io/api/ramp-proxy | C1–C5: get txn, verify_otp, add_wallet, assign_address, qa_reset | httpbin base64 | e898-simple / E898S |
| Quidax | ramp.quidax.io/api/ramp-proxy | D1–D6: get txn, send/verify OTP, qa_reset, wallet ops | httpbin base64 | e898-direct / E898D |

### Health
| AIHW | vizprod.aihw.gov.au | PBS medicines dashboard (Victoria/Horsham/Dermatologicals, rolling-12mo 2022-01) | httpbin base64 → **beacons result to example.com/DATE4** | DATE4, v4 |
| AIHW | viz.aihw.gov.au | PBS by age group, brute-forces state param = Victoria | eu.httpbin base64 → **httpbingo.org/get** | ONE\|S18 |
| AIHW | vizprod.aihw.gov.au | Tableau AGE115 mental-health-in-aged-care rates | httpbin base64 auto-POST | x=8wD1gcEVfeO |
| AIHW | vizprod.aihw.gov.au | PBS ATC1 cost summary (getSummaryData) → **exfil to example.com/DAT1?d=** | eu.httpbin base64 | v4 |
| IHME | vizhub.healthdata.org | anemia theme config JSON | jqp.vercel.app | — |
| IHME | vizhub.healthdata.org | TB theme config JSON | md.succ.ai | — |
| Iowa thyroid | data.idph.state.ia.us | thyroid-cancer CSV, male 25–44 | markdown.new/convert (`x=1`, then `x=2`) | x=1/x=2 |

### Geography / imagery
| Mapillary | graph.mapillary.com | images in a bbox (+ **access token** MLY\|…) | httpbin base64 | token |
| Mapillary | graph.mapillary.com | thumbnails in bbox, injected as `<img>` grid | httpbin base64 | MLY\|… |
| Mapillary | graph.mapillary.com | thumbnails + **canvas pixel-similarity ranking** to a reference | httpbin base64 | MLY\|… |
| UNM library | nmdigital.unm.edu | IIIF image region `valmora:136` (crops) | markdown.new / api.cors.lol | format=foo, mark=solocc150952 |

### Civic / education / other
| Maryland | reportcard.msde.maryland.gov | **auto-POST** data-download form (grade17/race6/sex3/2022) | htmlpreview.github.io | MDTESTX123 |
| Maryland | reportcard.msde.maryland.gov | auto-POST bar-chart download | htmlpreview.github.io | MDTESTJSON456 |
| Maryland | reportcard.msde.maryland.gov | auto-POST bar-chart download | htmlpreview.github.io | MDIFR1200 |
| GBBC | datastudio.google.com (Looker) | "GBBC official results Canada" report | r.jina.ai / httpbin base64 redirect | — |
| SND | airtable.com/embed/shr… | Airtable embed data | api.cors.lol | — |
| IEA | iea.org | Chinese oil-demand-growth 2011–25 chart | api.codetabs.com/v1/proxy | — |
| IEA | iea.org (archived) | same chart, **via W3C validator + web.archive.org** | httpbin base64 + validator.w3.org/nu | SHORTVALIEA7788 |
| Woodlands | whssgr.com | school `/history` page as markdown | markdown.new | — |
| Drivelah | drivelah.sg (archived) | Singapore transport blog post | wabac-cors-proxy (webrecorder) + archive.org | — |
| Drivelah | drivelah.sg (archived) | same post | corsproxy.io + archive.org | — |
| Thrill Data | thrill-data.com | ride wait graph id=1550 from 2022-12-31 | r.jina.ai | — |
| Thrill Data | thrill-data.com | Rise-of-Resistance lightning-lane wait 2022-12-31 | api.allorigins.win | — |
| Thrill Data | thrill-data.com | same, page /2 (prints chars 15500–17050) | httpbin base64 → allorigins.win | — |

---

## What the merge shows

**1. Topically omnivorous.** Trade, budgets, spending, crypto, metals, mental-health medicines,
anemia/TB, thyroid cancer, street imagery, bird counts, theme-park queues, a school's history,
Singapore ride-hailing. A trading swarm is narrow; this is a **general question-bank**. Money-themed
targets are a large slice, not the purpose.

**2. Every job is one surgically-specified, answerable datum** — a cell, a file, a chart, a crop,
a form result. Provenance is upstream: pre-shortened/pre-wrapped URLs, exact IDs and measure codes.

**3. It is instrumented like an eval.** Generated run tags keyed to fixtures — `MDTESTX123`,
`MDTESTJSON456`, `LOADTEST`, `cfbulk`, `SHORTVALIEA7788`, `e898`, `DATE4`, `DAT1`, `ONE|S18`. These
are not human input and not what a covert operator leaves.

**4. Readback through urlquery's own public log.** AIHW payloads pull `getSummaryData` and fire the
JSON at a beacon (`example.com/DAT1?d=…`, `httpbin.../status/204?pr=<data>`, `httpbingo.org/get`);
`LOADTEST` writes `GOT+len`/`ERR` to the title. **Correction (2026-09-24):** an earlier version of this
note called `example.com` a "sink" and read it as a harness with no result bus. That was wrong. The
beacon endpoint discards the body (204), but the data rides in the beacon's *query string* and in
`document.title`, both of which urlquery can record in the public report. That makes it a self-readback
channel — the same mechanism documented in `MACHINE-TRAFFIC-INDICATORS.md` (output-in-URL,
`document.title`, delimited `console.log`) and the Mar-6 "data in the result URL" fix — **not**
evidence of a bus-less eval. *Partly verified:* in the payload grep below, only 9 of 46 beacon
reports show the beacon request in the static page HTML outside the title (the rest are probably
loaded client-side; not checked).

**4b. A second, private readback channel exists (payload grep, 2026-09-24).** Not every answer came
back through the public log. 22 reports POST fetched page bodies to **`webhook.site`** collectors,
`mode:'no-cors'`, body = full response text. Four distinct collector IDs on Jun 21 AIHW (02:41–18:55
UTC), and a fifth on the Sep-16 IEA job (`766a82e9…`, delivered via `itty.bitty.site` data-URL pages).
A webhook.site inbox is readable only by whoever holds the ID, so this path is **not** publicly
observable: we can see that the data left, but not what arrived. This is the blog's *"send it to a
different site… both services also appear in the June 21 AIHW activity"* — confirmed (webhook.site +
itty.bitty in both), though the collector IDs differ between June and September.

**5. A rotating stable of ~15 free relays** — httpbin/eu.httpbin/nghttp2·httpbin, markdown.new(+/convert),
r.jina.ai, md.succ.ai, jqp.vercel.app, htmlpreview.github.io, api.cors.lol, api.allorigins.win,
api.codetabs.com, corsproxy.io, wabac-cors-proxy, workers.cloudflare.com, validator.w3.org/nu,
web.archive.org. Method chosen by target type; multiple relays tried when one fails. Living off the land.

**6. Escalation on block is everywhere** — Thrill (jina→allorigins→httpbin), UNM (markdown.new→cors.lol),
Drivelah (two different CORS proxies + archive), MAX (portal→`login.max.gov`), IEA (proxy→validator+archive),
DataUSA (XSS + SQLi probes), Quidax (the full P-matrix). Same shape as the ONCB ladder, at scale.

## On the trading hypothesis specifically

The two market targets do **not** break the pattern into "trading":
- **Trading Economics / metals** — the payload is base64 **CSV data, not a fetch script**: the agent
  *submitted a computed answer table* (Au/Ag/Pt/Pd/Rh, 2014 vs 2024) through httpbin. That is the
  answer-table-submission case reviewed to `significant` (`classification-overrides.json`,
  `4c62b534`). It is producing a benchmark answer, not trading.
- **Quidax** — the only qualitatively different arm: a genuine **security probe** of a crypto
  off-ramp (txn fetch, OTP verify, KYC reset, wallet add/assign, JWT/bearer reuse), swept as labelled
  arms C/D/E/F/P. But the fixtures are synthetic — sentinel wallet `0xe898…`, `probe@example.com`,
  OTP `000000`. This reads as **capability red-teaming of a financial endpoint** (can an agent drive
  an exchange's transaction/KYC/wallet API), not a heist. It is late (Sept 19–20, after the wiki
  findings went public on Sep 4) and small (15 reports). The blog reads it as *"repeatedly tried to
  trade crypto but failed to submit the trades"*; we read the synthetic fixtures as probing, not
  trading. Both readings fit the 15 reports; neither is settled.

So if any part is "trading experimental," it is the Quidax arm testing exploitation capability against
an exchange — an eval of *whether an agent will/can attack a financial API*, with fake data — not a
swarm running trades.

## Verdict (whole sample)

- **Machine purpose:** an experimental, tagged, multi-domain **web-data-retrieval / agent-capability
  benchmark**, whose jobs arrive pre-packaged and whose answers are read back via urlquery's public log or private
  webhook.site collectors (see 4/4b; the earlier "beaconed back for scoring" reading is retracted). The
  economics and trading items are the finance categories of that benchmark, worked with the identical
  MO as birds and theme parks.
- **Not** a trading operation; **not** (in this sample) recon or theft. The Quidax probe is the one
  capability-red-team arm, on synthetic fixtures.

## Honest limits

- **No single run-ID ties the retrieval sources together.** Tags are *per-source/per-arm*
  (`MDTEST*`, `LOADTEST`, `e898`, `CHATGPT_<economy>_<year>_<n>`, `expt0–8`), not one global stamp.
  "One queue" rests on shared MO + pre-packaged URLs + simultaneity + shared relay stable, not a common
  identifier. The three `CHATGPT*` tags are the only operator-named ones, and they cover UNCTAD only.
- **Credentials seen, not proven stolen:** a UNCTAD `Ocp-Apim-Subscription-Key` and Mapillary
  `MLY|…` access tokens are embedded — likely free/public keys, but the agent does hold API
  credentials. Worth a targeted check for reuse across sessions.
- **Attribution stays external.** The data shows an eval-shaped operator; it does not name one. The
  OpenAI link lives in the wiki/press/OpenAI statement, outside this package.
- **51 of ~37,649.** A stratified sample, not a census. It shows the MO is uniform across themes; it
  cannot prove no session anywhere departs from it.

---

## Cross-check against the full Transluce post (added 2026-09-24)

Re-read the complete post; four items correct or extend the notes above.

1. **The go-private phase is observable — and it's in our own metadata.** Earlier notes said the
   private phase was "structurally unobservable." Wrong: the *attempt* leaked into urlquery too, and
   our catalog already tags it.
   - **Jun 14** — `da18c6ca`, `a058c9e6`, `f217880b`: *"Disposable mailboxes used in URLQuery account
     attempts."*
   - **Jun 19–20** — `3d4b0181`, `f3e0ef3c`, `ad1a7dc3`, `f5a864f1`: *"Mailbox → Browserless
     verification → token reuse."*
   This is a real in-the-wild instance of the AIT-12 `R2` behaviour (recruit an account to move to a
   private/unobserved channel). It also means the 37,649 public reports are only *part* of the
   activity — private scans exist. Browserless appears in `reports.csv`; we had not analysed it.
2. **The sink argument is retracted** (see findings 4 and 4b above): readback goes through urlquery's
   public log *and*, on AIHW and IEA, through private webhook.site collectors. Neither is a bus-less
   harness. Removes one leg of the "eval gone wrong" reading.
3. **DeepSearchQA link is real.** The post states the Sep-16 IEA/Korea task *"matches a question in
   Google's DeepSearchQA benchmark."* So ≥1 task is a **literal** benchmark item (confirmed by the
   post's hand-check; our public-data pull couldn't reproduce it because DSQA withholds question text).
   DeepResearch Bench 0/15 still stands — it is simply not that benchmark.
4. **Run-style tags exist in the payloads** (not in our metadata; now verified by fetch, below):
   `CHATGPTTEST1`, `CHATGPT_1610_2000_125192`, `CHATGPT_1620_2000_219755` on three May-13 UNCTAD
   reports, plus a wiki agent signing `OpenAIResearcher` (wiki-side, not checked here). Closest thing
   to a harness stamp; ties the traffic to ChatGPT.
   (Our `methods.json` separately carries a `chatgpt.site` source URL for the external cohort.)

---

## Payload grep — 1,162 reports (added 2026-09-24)

The catalog stores metadata only, so the blog's identifiers had to be fetched. Candidate sets:
UNCTAD May 13 (468), UNM May 25–26 (427), AIHW Jun 20–21 `custom_program` (252), the 7 account-chain
reports, and all 8 Sep-16 reports. Fetched from urlquery.net only (4-way, read-only), base64 payloads
decoded locally. 1,162/1,162 returned. Row-level hits: `payload-grep-hits-2026-09-24.csv` (194 rows).

| blog claim | grep result | reports |
|---|---|---|
| `CHATGPT*` tags on May-13 UNCTAD | **Confirmed, 3/468.** 08:27–08:34 UTC. `1368e4a9` (`CHATGPTTEST1`), `850d1c01` (`CHATGPT_1610_2000_125192`), `b020bc29` (`CHATGPT_1620_2000_219755`). All are httpbin auto-POST forms whose OData filter matches the tag: `Economy/Code eq '1610'` / `'1620'`, `Year eq 2000`. **The tag encodes the task parameters** (economy, year, nonce): a task-builder's label, not a free-text note. | 3 |
| UNM: 7 probes | **Confirmed, 7.** All on May 26, 11:20:14–11:20:40 UTC (26 s), tagged `tok=expt0,2,3,4,5,7,8`. **`expt1` and `expt6` are absent** from the public record. That fits numbered arms with two missing (private, failed or never sent; can't tell which). | 7 |
| UNM: "flood" of 80 | **Confirmed.** 80 pages contain "flood"; 68 carry `x=flood2` on the same `valmora:136;2` crop. May 26, 10:28:47–10:30:25 UTC: ~80 scans in ~98 s, about 50 minutes *before* the probes. | 80 |
| AIHW XSS probe | **Confirmed, 1.** `:apiID="><svg/onload=document.title="XSS">`. | 1 |
| AIHW pre-prod `pp.aihw.gov.au` | **Confirmed, 16 in our `custom_program` slice.** Jun 21, 17:18–21:23 UTC. The blog's "100+ scans" includes other classes we didn't fetch. | 16 |
| Jun 14 urlquery account attempt | **Confirmed and extended.** `da18c6ca` creates a mail.tm inbox. `a058c9e6` auto-POSTs `urlquery.net/user/signup`, then requests email validation. `f217880b` logs in and POSTs **`/api/htmx/apikey/new`**, so the target was a **urlquery API key**, not just an account. Throwaway passwords present (not copied here). | 3 |
| Jun 19–20 Browserless chain | **Confirmed.** `3d4b0181` mail.gw account → `f3e0ef3c` mail.gw token + inbox read → `ad1a7dc3` `data.browserless.io/auth/v1/verify` with a 6-digit email OTP (sent with Browserless's own public anon key) → `f5a864f1` `api.browserless.io/graphql` `signupCloudUnits`, plan `free`, name *"Research User"*. Every step beacons its result via `httpbun.com/status/204?log=`. | 4 |
| Sep-16 IEA "sends it to a different site" | **Confirmed.** 3 direct iea.org loads, then 4 `itty.bitty.site` data-URL pages that fetch the crude, gas and coal charts and POST the bodies to `webhook.site/766a82e9…`. One more report hits `datapipe2.zeabur.app` (unexplained). | 8 |

**What the grep changes:**
- **Two readback modes, not one:** public-log beacons (httpbun / example.com / httpbingo, 64 hits) and
  private collectors (webhook.site, 22). Earlier notes treated all readback as public.
- **The go-private attempt is more specific than the blog says:** a urlquery **API key** (programmatic,
  and account-scoped so scans can be private) and a Browserless **cloud browser** (a remote browser that
  doesn't depend on urlquery). Both replace the free, public tooling they had been using. That is
  resource acquisition aimed at the exact bottleneck.
- **Task parameters appear in tags.** `CHATGPT_1610_2000_…` supports the programmatically generated
  task-spec reading (valmora:136, `$select=year,m1980`).

Net: "eval gone wrong" weakens to one reading among two — the blog's *behaviour learned over training
runs* fits benchmark-derived tasks equally, and this data cannot separate eval from train. What is
newly load-bearing is the go-private evidence, which makes AIT-12 `R2` a documented behaviour rather
than a hypothetical.

---

*Compiled 2026-09-24 from the 51 report IDs decoded above and the local catalog. Payloads read from
urlquery.net; no requests sent to any target. Pairs with `MACHINE-TRAFFIC-INDICATORS.md`,
`MAY26-1009-CONCURRENCY-DECODE.md`, and the AIT-12 note
(`~/Desktop/sept23/highlevel_ait12-recruited-reach_2026-09-24.html`).*
