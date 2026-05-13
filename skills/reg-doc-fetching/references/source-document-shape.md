# SourceDocument shape + storage layout

The common in-memory descriptor and the on-disk layout each agency writes to.

## SourceDocument dataclass

```python
@dataclass
class SourceDocument:
    title: str                    # Human-readable title (e.g. "Multidisciplinary Review")
    url: str                      # Direct URL to the source document
    source: SourceType            # FDA | EMA | HEALTH_CANADA | TGA | PMDA | HMA | PUBMED | EU_NATIONAL | COMPOSITION
    doc_type: str                 # Slug-style identifier (e.g. "epar_assessment", "product_monograph")
    language: str = "en"          # ISO 639-1
    file_format: str = "pdf"      # "pdf" | "html" | "json" | "xml" | "txt"
    metadata: Dict = {}           # Arbitrary key-values (publication_date, sponsor, etc.)

    # Populated after download
    local_path: Optional[str] = None
    text_content: Optional[str] = None
    file_size_kb: float = 0.0
    error: Optional[str] = None
```

## SourceType enum

```python
class SourceType(Enum):
    FDA = "fda"
    EMA = "ema"
    HEALTH_CANADA = "health_canada"
    TGA = "tga"
    PMDA = "pmda"
    HMA = "hma"
    PUBMED = "pubmed"
    EU_NATIONAL = "eu_national"
    COMPOSITION = "composition"   # RLS/GRLS/ISP (reference listed standards) — niche
```

## Common protocol all source tools implement

```python
class RegulatorySource(Protocol):
    async def search(self, query: str, **kwargs) -> List[SourceDocument]:
        """Return candidate documents matching the query. Doesn't download."""

    async def download(self, doc: SourceDocument, dest_dir: Path) -> SourceDocument:
        """Download to dest_dir. Sets local_path, file_size_kb, error if any.
        Idempotent: if file already exists at expected path, returns immediately."""
```

Convention: `search()` returns `[]` (not raise) when no results found; `download()` sets `.error` (not raise) when download fails.

## On-disk layout

```
$FDA_DATA_DIR/
├── Applications.txt            # FDA local Drugs@FDA catalog (refreshed weekly)
├── Products.txt                # FDA local product table
├── (other .txt cache files from FDA's Applications.zip)
│
├── fda/
│   ├── reviews/<substance>/
│   │   ├── <appl>Orig1s000<suffix>.pdf
│   │   ├── PSG_<appl>.pdf
│   │   ├── SUPPL_<N>_<appl>s<N>lbl.pdf
│   │   ├── SUPPL_<N>_<appl>Orig1s<N>ltr.pdf
│   │   ├── dailymed_<setid>.pdf
│   │   ├── <filename>.meta.json    # retrieval-evidence sidecar
│   │   └── <filename>.extracted.txt  # post-extraction sidecar (written by pdf-doc-extraction)
│   └── extracted_text/<substance>/   # for non-PDF sources, plain-text extracts go here
│       └── (used by multi-source pipeline, see below)
│
├── ema/documents/<substance>/
│   ├── <Brand>_-_..._EPAR_-_Public_assessment_report.pdf
│   ├── <Brand>_-_EMA_Product_Page.html
│   └── ..._meta.json
│
├── health_canada/documents/<substance>/
│   ├── Product_Monograph_-_<BRAND>.pdf
│   ├── Summary_Basis_of_Decision_for_<Brand>.html
│   ├── Regulatory_Decision_Summary_for_<Brand>.html
│   └── ...
│
├── pmda/documents/<substance>/
│   └── PMDA_Review_Report_-_<Brand>_<INN>.pdf
│
├── tga/documents/<substance>/
│   ├── TGA_AusPAR_-_AusPAR_<INN>.pdf
│   └── TGA_PI_-_AusPAR_<INN>.pdf
│
├── hma/documents/<substance>/
│   └── <procedure_id>_<doc_type>.pdf
│
└── pubmed/documents/<substance>/
    ├── pubmed_<PMID>_abstract.txt
    ├── pubmed_<PMID>_<PMCID>.pdf       # if Open Access
    └── pubmed_<PMID>_<PMCID>.html      # fallback when PDF endpoint returns HTML
```

## Multi-source plain-text staging (optional)

The downstream Streamlit app pipeline (`app.py`) needs a single plain-text per source for the document-assessor LLM. This is OPTIONAL for this skill — only relevant if you're chaining into the synthesis pipeline.

```
$FDA_DATA_DIR/fda/extracted_text/<substance>/
├── ema_<safe_name>.extracted.txt        # plain-text from an EMA HTML page
├── health_canada_<safe_name>.extracted.txt
├── pmda_<safe_name>.extracted.txt
├── tga_<safe_name>.extracted.txt
├── pubmed_<safe_name>.extracted.txt
```

Naming: `<source.value>_<filename_stem>.extracted.txt`. Source value is the SourceType enum value (lowercase).

**KNOWN BUG (May 2026):** if you save text using `Path(local_path).stem` and `local_path` already ends in `.extracted.txt`, the stem keeps the inner `.extracted` and you get `..._<name>.extracted.extracted.txt` doublets. Strip a trailing `.extracted` from the stem before appending. See `quirks-and-gotchas.md` §SafeNameStem.

## meta.json sidecar shape

Per-document retrieval evidence:

```json
{
  "agency": "FDA",
  "doc_type": "Multidisciplinary Review",
  "appl_no": "NDA-210951",
  "url": "https://www.accessdata.fda.gov/drugsatfda_docs/nda/2018/210951Orig1s000MultidisciplineR.pdf",
  "retrieval_date": "2026-05-13T11:42:18Z",
  "retrieval_tool": "reg-doc-fetching skill via Claude Code",
  "sha256": "a1b2c3d4...",
  "file_size_bytes": 11036459,
  "content_type": "application/pdf",
  "filename": "210951Orig1s000MultidisciplineR.pdf"
}
```

Always write a `.meta.json` next to every downloaded document. The downstream wiki source-card writer consumes these.

## Idempotency rules

- Re-running the skill should NOT re-download docs already on disk with `file_size_bytes > 0`.
- Re-running SHOULD refresh stale catalog caches (medicines.json, Applications.txt) if older than 7 days.
- Re-running with `--force` (user-requested) overrides both.

## Filename safety

Apply this transform to any agency-provided title or URL when forming a filename:

```python
def safe_name(raw: str) -> str:
    # Replace anything non-alphanumeric (except dash, underscore, period) with underscore
    s = "".join(c if c.isalnum() or c in "-_." else "_" for c in raw)
    # Collapse multiple underscores
    while "__" in s:
        s = s.replace("__", "_")
    # Trim
    return s.strip("_.").strip()[:100]
```

100-char cap prevents Windows MAX_PATH issues on WSL/NTFS bind mounts.
