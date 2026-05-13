# Quirks and Gotchas

Real bugs hit in production. Don't re-discover them.

## DHPP `search=` vs `query=`

Health Canada's Drug and Health Product Portal silently ignores `query=`. Use `search=`.

```
GOOD: https://hpr-rps.hres.ca/?ds=1&search=apalutamide&lang=en
BAD:  https://hpr-rps.hres.ca/?ds=1&query=apalutamide&lang=en   # returns global listing
```

## EMA JSON shape

EMA's daily JSON exports have envelope structure:

```json
{
  "data": [...],
  "meta": {...}
}
```

NOT a top-level array. Parse `data` field. Endpoint URLs:

```
https://www.ema.europa.eu/en/documents/report/medicines-output-medicines_json-report_en.json
https://www.ema.europa.eu/en/documents/report/documents-output-epar_documents_json-report_en.json
```

## PMC PDF endpoint returns HTML

NCBI's PubMed Central PDF endpoint `https://www.ncbi.nlm.nih.gov/pmc/articles/<PMCID>/pdf/` often redirects to an HTML landing page with `content-type: text/html` instead of returning a PDF.

**Detect by content-type, not by HTTP status.** The response is HTTP 200, just with the wrong body.

```python
resp = httpx.get(url)
if "application/pdf" not in resp.headers.get("content-type", ""):
    # save as .html fallback
    ...
else:
    # save as .pdf
    ...
```

## Brotli encoding on HC and some FDA endpoints

Some Health Canada and FDA endpoints respond with `Content-Encoding: br` (Brotli) and httpx (without the brotli dep) won't decode it. Symptom: text looks like garbage bytes.

Fix: in the request headers, explicitly send:

```
Accept-Encoding: gzip, deflate
```

…to opt out of brotli, OR ensure `brotli` is installed in the env.

## Azure migrated TestVS1 deployments

(May 2026 incident — relevant only if using Azure OpenAI as an extraction model.) Azure migrated old `openai.azure.com` endpoints to new region-specific URIs on 2026-05-01. Old 401 errors after that date mean the deployment was migrated. Check Target URI in Azure portal.

## FDA Applications.txt is HUGE

`https://www.accessdata.fda.gov/cder/Applications.zip` unzips to ~100 MB of tab-separated data. Don't load it row-by-row through `pd.read_csv` defaults — it OOMs on small dev VMs. Use:

```python
df = pd.read_csv("Applications.txt", sep="\t", dtype=str, low_memory=False, encoding="latin-1")
```

`latin-1` because Applications.txt contains diacritics in sponsor names (e.g. "Glaxo Wellcome") that fail UTF-8 strict decoding.

## TGA AusPAR search rate-limits aggressively

The TGA scrape endpoint will throw 429 if you exceed ~30 requests/min sustained. Default to 1 request every 2 seconds.

## PMDA serves PDFs without Content-Disposition

PMDA PDFs come with no filename hint. Derive filename from the URL: `https://www.pmda.go.jp/files/000XXXXXX.pdf` → use the URL's last segment as the on-disk name, then rename to the descriptive form after parsing the page's HTML for substance name.

## HMA OAuth tokens expire quickly

HMA JWT tokens are typically valid 1 hour. Cache the token + expiry in memory; refresh before issuing any request more than ~58 min after token issue. The OAuth endpoint is at `https://api.hma.eu/oauth2/token`.

## DailyMed pagination

`spls.json?application_number=NDA<n>` returns paginated results (50 per page). For drugs with many label revisions (FDA SUPPL_007, _008, _009 → each may have its own SetID), you need to follow `paging.next_page` until null.

## EMA Variation / Extension naming

EMA assessment reports for **variations** (post-approval changes) have URLs like:

```
.../Erleada-H-C-4452-II-0001___EPAR_-_Assessment_Report_-_Variation.pdf
```

Note the dash variations: `H-C-4452` vs `H-C-004452`. The procedure number can appear with or without leading zeros across documents. Don't try to normalise; preserve as-is in filename.

## Erleada vs apalutamide: dual identity

Brand name search vs INN search at EMA returns different things sometimes:
- INN `apalutamide` → matches medicine record but might miss some Variations indexed under brand
- Brand `Erleada` → matches medicine record but might miss EU-wide INN aliases

Fetch both ways and dedupe on URL.

## §SafeNameStem — `.extracted.extracted.txt` doublet

When saving extracted text for a non-FDA source via:

```python
safe_name = Path(src_doc.local_path).stem
src_text_path = text_dir / f"{src_doc.source.value}_{safe_name}.extracted.txt"
```

If `src_doc.local_path` already ends in `.extracted.txt`, then `.stem` keeps the inner `.extracted` extension, and you create `..._<name>.extracted.extracted.txt` doublets.

Fix: strip trailing `.extracted` from the stem before appending the new suffix.

```python
safe_name = Path(src_doc.local_path).stem
if safe_name.endswith(".extracted"):
    safe_name = safe_name[:-len(".extracted")]
```

This was a real bug fixed 2026-05-12. Read-side dedupe also added: when scanning `*.extracted.txt`, skip files matching `*.extracted.extracted.txt`.

## Streamlit cache hold across reruns

(Not relevant to fetching skill directly, but worth knowing if you orchestrate via Streamlit.) Streamlit re-imports `app.py` on every interaction but caches `core/*` modules until process restart. After editing core code, you must restart Streamlit, not just rerun.

## OpenRouter `:free` slug rate-limited globally

If chaining into LLM-based extraction, OpenRouter's `:free` slugs share a 20 req/min cap across the entire account. Doesn't affect fetching, but if you orchestrate "fetch → extract → analyze" in one workflow, the extract phase will throttle.

## Brand-INN-substance triangulation

Some drugs have multiple brands (e.g. roxadustat = Evrenzo / Aerodar / Roxa-something). Searching by INN typically finds all; searching by one brand misses the others. The user usually provides the INN; if they give a brand, resolve to INN first via EMA medicines.json or a Wikipedia look-up (last resort).
