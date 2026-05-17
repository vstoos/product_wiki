# Engine Selection

Decision tree for picking an OCR engine, plus per-engine specs.

## Decision tree

```
Is the doc CLEAN PDF (PyMuPDF returns full text)?
├── YES → No OCR needed. Skip Stage 2.
└── NO → How many scanned pages?
        ├── < 5 → Use lightweight engine (Gemma multi-provider; free, ~13s/page)
        ├── 5–30 → Default (Gemma multi-provider for $0)
        ├── 30+ AND user okay with cost → Azure DI (~2.8s/page, $10/1000) — also handles tables
        └── 30+ AND staying free → Remote Docker GPU (LightOnOCR or GLM-OCR) if available
                                  ELSE PaddleOCR-VL local if user has GPU
                                  ELSE Gemma multi-provider (just slow)
```

Override per-doc per user preference.

## Engine comparison table

| Engine | Type | Cost | Speed | Quality | Tables built-in? | Best for |
|---|---|---|---|---|---|---|
| **Gemma multi-provider** | Cloud (free Gemini+OpenRouter) | $0 | ~13s/page | Excellent | No | Default for everything free |
| **PaddleOCR-VL 0.9B** | Local GPU | $0 (compute) | ~2s/page | Best on FDA docs | No | Best quality if GPU available |
| **PaddleOCR-VL 1.5** | Local GPU | $0 (compute) | ~2s/page | 94.5% OmniDocBench | **Yes — cross-page merge** | Best if you have GPU + latest PaddleX |
| **Surya 0.17** | Local CPU | $0 (compute) | ~30s/page | Excellent | No | Multi-language fallback |
| **Surya GPU (Docker)** | Remote GPU | $0 (host) | ~3s/page | Excellent | No | When you have a GPU container |
| **LightOnOCR-2-1B (Docker)** | Remote GPU | $0 (host) | ~3s/page | Strong on tables | Yes (markdown) | Tables + structured data |
| **GLM-OCR (Docker)** | Remote GPU | $0 (host) | ~3s/page | Strong general | Yes | General fallback |
| **Azure DI prebuilt-layout** | Cloud | $10/1000 pp | ~2.8s/page | Excellent | **Yes** | When tables are critical AND budget exists |
| **Mistral Document AI** | Cloud | $$ | n/a | n/a | n/a | REJECTED — not on Student subscription |
| **Tesseract** | Local | $0 | ~5s/page | Mediocre | No | DEPRECATED — lower quality than Surya/PaddleVL |

## Per-engine config notes

### Gemma multi-provider (default)

Class: `MultiProviderGemmaLLM` (`core/multi_provider_llm.py`)

Round-robins between:
- Gemini API (`google:gemma-4-31b-it`) — 15 RPM cap per the API, free tier
- OpenRouter (`openrouter:google/gemma-4-31b-it:free`) — 20 RPM account-wide free cap

When one is rate-limited, the other carries. Effective throughput: ~25-30 RPM on the union.

Env vars:
```
GOOGLE_API_KEY=...          # for Gemini API path
OPENROUTER_API_KEY=...      # for OpenRouter path
GEMMA_OCR_MODEL=gemma-4-31b-it     # which Gemma variant; also gemma-4-26b-a4b-it
```

### PaddleOCR-VL

Class: `PaddleOCRVLEngine` (`pdf_extraction/pdf_ocr_paddlevl.py`)

Requires:
- PaddlePaddle GPU (NCCL must match host CUDA — see CLAUDE.md for the PyTorch/Paddle NCCL conflict resolution)
- `pip install "paddlex[ocr]"`
- A patched `paddlex/inference/utils/misc.py:33` (or apply the runtime patch in `pdf_ocr_paddlevl.py`)

Known issue: PaddleX `is_bfloat16_available` bug; runtime patch already in code.

### Surya

Class: see `pdf_extraction/pdf_ocr_surya.py`

CPU-only by default (due to NCCL conflict with Paddle). Slow but reliable. Multi-language.

### Azure Document Intelligence

Class: `AzureDIEngine` (`pdf_extraction/pdf_ocr_azuredi.py`)

Endpoint: `https://<resource>.cognitiveservices.azure.com/` (S0 tier, prebuilt-layout model).

Env:
```
AZURE_AI_ENDPOINT=https://<resource>.cognitiveservices.azure.com/
AZURE_AI_KEY=<key>
```

**Cost watch:** $10/1000 pages. A typical NDA review hits this quickly. Reserve for high-value pages.

### Remote Docker OCR servers

Two containers:
- `ocr-server:8001` — LightOnOCR-2-1B + GLM-OCR (Transformers 5.0+, supports glm_ocr)
- `surya-server:8002` — Surya 0.17 (Transformers <5.0, separate due to lib conflict)

Client class: `RemoteOCREngine(engine="lighton" | "glmocr" | "surya")` (`pdf_extraction/pdf_ocr_remote.py`)

```bash
cd docker && docker compose -f docker-compose.ocr.yml up -d --build
```

If you have a GPU machine with the containers running, this is faster than cloud Gemma and free.

## Auto-engine selection logic

When user doesn't specify, here's the selection logic (matches the original Streamlit "Auto (Smart Selection)" sidebar option):

```python
def auto_select_ocr(doc_summary):
    scanned_pages = doc_summary.scanned_page_count
    has_gpu = check_paddle_gpu_available()
    has_docker = check_docker_ocr_servers_up()
    has_azure = bool(os.getenv("AZURE_AI_KEY"))

    # 1. Many scanned pages and Azure credits available → Azure DI
    if scanned_pages >= 30 and has_azure and ALLOW_AZURE_COST:
        return "azure_di"

    # 2. GPU available → PaddleOCR-VL (best quality, fast)
    if has_gpu:
        return "paddlevl"

    # 3. Docker GPU available → LightOnOCR (best for tables)
    if has_docker:
        return "lighton"

    # 4. Default: Gemma multi-provider (free, ~13s/page)
    return "gemma_multi"
```

User-overridable via skill input: `engine_preference: gemma_multi | paddlevl | surya | azure_di | lighton | glmocr | remote_surya`.

## Engine cache directories

Each engine writes its own intermediate output:

```
<stem>.ocr/
├── paddlevl/<page>.json    # PaddleVL result per page
├── gemma/<page>.json
├── surya/<page>.json
├── azuredi/<page>.md       # Azure DI returns markdown directly
└── lighton/<page>.json
```

If two engines are run on the same doc (e.g. for quality comparison), both write to their respective subdirs and don't collide.

## Quality benchmarks (reference)

From `benchmarks/benchmark_ocr_engines.py` run on representative FDA Chemistry Review pages (Jan 2026):

| Engine | Char accuracy | Table accuracy | Wall time (per page) | Cost (1000 pp) |
|---|---|---|---|---|
| PaddleOCR-VL | 99.1% | 95% | 2.0 s | $0 |
| Gemma 4 31B (multi) | 98.2% | 87% | 13.0 s | $0 |
| Surya CPU | 98.8% | 89% | 30 s | $0 |
| Azure DI | 99.5% | 99% | 2.8 s | $10 |
| Tesseract | 91% | 50% | 5 s | $0 |

PaddleVL beats Gemma on tables but Gemma is functionally good enough for free-tier workflows.

## When to switch engines mid-document

If Stage 1 finds a doc with mixed clean + scanned pages, AND the dominant content is on clean pages → use PyMuPDF text directly for clean pages, and only OCR the scanned ones. This is the default HybridPipeline behaviour.

If a single scanned page yields garbage from one engine (e.g. confidence very low), retry with a different engine before falling back to "OCR failed" placeholder. Try order: primary → PaddleVL → Gemma → Surya → Azure DI.
