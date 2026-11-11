# The May 26 10:09 UTC concurrency window — six streams decoded

The largest overlap in the record: on 2026-05-26 around 10:09 UTC, six different sources had a live
session open at once (dataset-shape report, "a floor of 6 parallel threads"). This note fetches one
report per source and reads what each was actually working on, to test whether the overlap is a swarm
with a shared purpose or a job queue drained in parallel.

**Method.** Reports opened on urlquery.net by report ID and read. Payloads reported verbatim.
No requests were sent to any target; the reader/proxy fetches (`markdown.new`, `da.gd`) were performed
by the original submitter at capture time, not by this analysis.

---

## The six streams, one report each

Selected as the in-window report nearest 10:09 for each source; for page/document targets the
`indirection` (reader-wrapped) row was preferred because it carries the task URL.

| Source | Report ID | Time (UTC) | Class |
|---|---|---|---|
| MAX budget documents | `feb53ad9-a988-4ba6-9479-591b2a5d5193` | 10:08:59 | indirection |
| UNCTAD | `a87a8291-2755-448d-81ad-ebd2c743eac4` | 10:07:52 | source_request |
| UNM digital library | `dbaaa2db-45db-4209-8a40-6b6000348b8c` | 10:05:04 | source_request |
| USAspending | `739920ae-8bc3-4de3-8fb4-9d6bb6c03217` | 10:13:56 | source_request |
| Thrill Data | `596214e4-fcd0-4319-ba99-bc11c000539f` | 10:04:30 | source_request |
| Woodlands House School | `0911e177-207a-42ad-8eaa-515c5f744974` | 10:09:30 | indirection |

### 1. MAX budget documents — a specific budget PDF, through a reader
```
Submitted:  markdown.new/https://portal.max.gov/portal/document/SF133/Budget/attachments/2346466575/2374423602.pdf
Target:     portal.max.gov  (SF-133 budget-execution document)
Via:        markdown.new (reader/proxy; Cloudflare 172.67.70.150)
Result:     rendered to about:privatebrowsing — reader returned nothing usable
```
`2374423602.pdf` is the exact file the dataset flags as the wiki-cited MAX PDF
(`source:max_pdf_q2`, marker `2374423602.pdf`) and matches the post's "only direct wiki→urlquery link,
May 26, federal budget PDF." **The task list has wiki provenance sitting inside this window.**

### 2. UNCTAD — one data cell, direct API
```
Submitted:  unctadstat-api.unctad.org/datamart-api/US.TransportCosts/1107/Facts
            ?$filter=destination/code eq '512' and transportmode/code eq '10'
                     and origin/code eq '0000' and product/code eq '93'
            &$select=year,m1980 &culture=en
Target:     unctadstat-api.unctad.org (dataset 1107, US.TransportCosts)
```
A single statistic: one destination × mode × origin × product, selecting only `year` and the `m1980`
measure. Surgically specified — benchmark-question shape.

### 3. UNM digital library — one document by exact ID
```
Submitted:  nmdigital.unm.edu/digital/api/collection/valmora/id/136/download
Retrieved:  valmora_136.pdf  (5.4 MB, 17 pages, md5 768da1c0c435824a70f5909e54696b1c)
```
Get document #136 from the Valmora collection. One-and-done retrieval.

### 4. USAspending — one federal account, via a shortener
```
Submitted:  da.gd/bIhl5   →   api.usaspending.gov/api/v2/federal_accounts/075-8005/
Target:     api.usaspending.gov (federal account 075-8005; 075 = Dept. of Veterans Affairs)
Alert:      Suricata "ET INFO Observed URL Shortening Domain (da.gd in TLS SNI)" — medium
```
The task URL was **pre-shortened** — generated upstream and handed to the agent.

### 5. Thrill Data — one park, one month, direct
```
Submitted:  www.thrill-data.com/trip-planning/crowd-calendar/shanghai-disneyland/calendar/2025/a
            #:~:text=March%202025
Target:     thrill-data.com (Shanghai Disneyland crowd calendar, jumped to March 2025)
```
Text-fragment anchor drives the browser to the exact section. Specific retrieval.

### 6. Woodlands House School — history page, through a reader
```
Submitted:  markdown.new/whssgr.com/history/
Target:     whssgr.com/history/  (school history text)
Via:        markdown.new reader
```

---

## What the sample shows

1. **Every stream is a surgically-specified, answerable retrieval of a single public datum** — one
   PDF, one cell, one document, one account, one month, one page. Not a target class, not assets, not
   auth. This is the shape of a **question bank**, not recon and not theft.
2. **The jobs arrive pre-packaged.** `da.gd/bIhl5` and the `markdown.new/…` wrappers mean the task
   URLs were generated and packaged upstream before the agent ran them. You do not shorten your own
   live query — this is a **pipeline / job queue**, i.e. the "common origin" made visible as
   infrastructure rather than inferred from timing.
3. **Method is chosen by target type.** API targets get a direct call; page/document targets get
   wrapped in a reader. Deliberate tool-composition, running across all six in parallel.
4. **Wiki provenance is present** (the MAX `2374423602.pdf`).

### Verdict on the three hypotheses (this window only)
- **Eval / benchmark queue — confirmed-shaped.** Six precise answerable questions, pre-packaged,
  drained in parallel.
- **Recon — ruled out for this window.** No enumeration, no asset/auth interest.
- **Nefarious / foothold — no support in this sample.** No credentials, no persistence, no escalation;
  all output routed to public reports.

### The honest limit
No shared literal run-ID was visible across these six (unlike the `e898` Quidax series). The
"tied together" claim rests on **simultaneity + identical MO + pre-packaged URLs**, not a common stamp
in these payloads. Whose pipeline it is stays outside both the metadata and these payloads: the
eval-shape is in the data; the OpenAI attribution is not. The one question this window cannot touch —
does it ever go private or reuse a credential — is exactly what AIT-12's `R2` arm is built to measure
directly.

---

*Compiled 2026-09-24 from the six report IDs above and the local catalog
(`all-reports.csv` ⋈ `report-sources.csv`, exact). Payloads read from urlquery.net; no requests were
sent to any target. Pairs with `MACHINE-TRAFFIC-INDICATORS.md` (indicators) and the AIT-12 draft
(`~/Desktop/sept23/highlevel_ait12-recruited-reach_2026-09-24.html`).*
