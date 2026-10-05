---
title: Benchmarks
---

# Benchmarks

How SEMQ's operators compare with the vector formats a retrieval pipeline already uses: how much search quality survives, how many bytes each vector takes, and how fast it encodes. Every number comes from a frozen result file with its inputs, commit and hardware.

<div class="semq-evidence-stats">
<div><strong>10.7×</strong><span>smaller than FP32 · SEMQ quant at 3 bits</span></div>
<div><strong>95–100%</strong><span>of FP32 search quality kept · six runs</span></div>
<div><strong>798k</strong><span>vectors encoded per second · 768 dimensions</span></div>
</div>

## Search quality kept

For each format, the line spans the lowest and the highest nDCG@10, relative to FP32, across three embedding models and two datasets (SciFact and FiQA). Formats are ordered by storage, fewest bits per dimension first. SEMQ is in blue.

<figure class="semq-chart" role="group" aria-label="nDCG@10 kept relative to FP32, lowest to highest across six runs, per format">
<svg viewBox="0 0 760 352" xmlns="http://www.w3.org/2000/svg">
<line class="semq-chart__grid" x1="288.7" x2="288.7" y1="8" y2="308"/>
<text class="semq-chart__tick" x="288.7" y="324" text-anchor="middle">40%</text>
<line class="semq-chart__grid" x1="406.0" x2="406.0" y1="8" y2="308"/>
<text class="semq-chart__tick" x="406.0" y="324" text-anchor="middle">60%</text>
<line class="semq-chart__grid" x1="523.3" x2="523.3" y1="8" y2="308"/>
<text class="semq-chart__tick" x="523.3" y="324" text-anchor="middle">80%</text>
<line class="semq-chart__grid" x1="640.7" x2="640.7" y1="8" y2="308"/>
<text class="semq-chart__tick" x="640.7" y="324" text-anchor="middle">100%</text>
<line class="semq-chart__reference" x1="640.7" x2="640.7" y1="8" y2="308"/>
<g><title>Binary · 1 bit/dim: 38.4% to 98.7% of FP32 nDCG@10 across 6 runs</title>
<text class="semq-chart__label" x="220" y="27" text-anchor="end">Binary · 1 bit/dim</text>
<line class="semq-chart__range is-comparison" x1="279.1" x2="632.9" y1="23" y2="23"/>
<circle class="semq-chart__dot is-comparison" cx="279.1" cy="23" r="5"/>
<circle class="semq-chart__dot is-comparison" cx="632.9" cy="23" r="5"/>
<text class="semq-chart__value" x="650.7" y="27">38–99%</text></g>
<g><title>SEMQ phase · 2 bits/dim: 75.5% to 99.6% of FP32 nDCG@10 across 6 runs</title>
<text class="semq-chart__label" x="220" y="57" text-anchor="end">SEMQ phase · 2 bits/dim</text>
<line class="semq-chart__range is-semq" x1="496.8" x2="638.2" y1="53" y2="53"/>
<circle class="semq-chart__dot is-semq" cx="496.8" cy="53" r="5"/>
<circle class="semq-chart__dot is-semq" cx="638.2" cy="53" r="5"/>
<text class="semq-chart__value" x="650.7" y="57">75–100%</text></g>
<g><title>SEMQ quant · 2 bits/dim: 81.8% to 99.4% of FP32 nDCG@10 across 6 runs</title>
<text class="semq-chart__label" x="220" y="87" text-anchor="end">SEMQ quant · 2 bits/dim</text>
<line class="semq-chart__range is-semq" x1="534.0" x2="637.2" y1="83" y2="83"/>
<circle class="semq-chart__dot is-semq" cx="534.0" cy="83" r="5"/>
<circle class="semq-chart__dot is-semq" cx="637.2" cy="83" r="5"/>
<text class="semq-chart__value" x="650.7" y="87">82–99%</text></g>
<g><title>Faiss PQ · 2.0–2.1 bits/dim: 94.9% to 100.5% of FP32 nDCG@10 across 6 runs</title>
<text class="semq-chart__label" x="220" y="117" text-anchor="end">Faiss PQ · 2.0–2.1 bits/dim</text>
<line class="semq-chart__range is-comparison" x1="610.8" x2="643.7" y1="113" y2="113"/>
<circle class="semq-chart__dot is-comparison" cx="610.8" cy="113" r="5"/>
<circle class="semq-chart__dot is-comparison" cx="643.7" cy="113" r="5"/>
<text class="semq-chart__value" x="653.7" y="117">95–101%</text></g>
<g><title>TurboQuant · 2.3–8.4 bits/dim: 81.9% to 99.9% of FP32 nDCG@10 across 6 runs</title>
<text class="semq-chart__label" x="220" y="147" text-anchor="end">TurboQuant · 2.3–8.4 bits/dim</text>
<line class="semq-chart__range is-comparison" x1="534.6" x2="640.2" y1="143" y2="143"/>
<circle class="semq-chart__dot is-comparison" cx="534.6" cy="143" r="5"/>
<circle class="semq-chart__dot is-comparison" cx="640.2" cy="143" r="5"/>
<text class="semq-chart__value" x="650.7" y="147">82–100%</text></g>
<g><title>SEMQ quant · 3 bits/dim: 94.7% to 100.5% of FP32 nDCG@10 across 6 runs</title>
<text class="semq-chart__label" x="220" y="177" text-anchor="end">SEMQ quant · 3 bits/dim</text>
<line class="semq-chart__range is-semq" x1="609.7" x2="643.6" y1="173" y2="173"/>
<circle class="semq-chart__dot is-semq" cx="609.7" cy="173" r="5"/>
<circle class="semq-chart__dot is-semq" cx="643.6" cy="173" r="5"/>
<text class="semq-chart__value" x="653.6" y="177">95–100%</text></g>
<g><title>SEMQ quant · 4 bits/dim: 98.8% to 100.0% of FP32 nDCG@10 across 6 runs</title>
<text class="semq-chart__label" x="220" y="207" text-anchor="end">SEMQ quant · 4 bits/dim</text>
<line class="semq-chart__range is-semq" x1="633.4" x2="640.8" y1="203" y2="203"/>
<circle class="semq-chart__dot is-semq" cx="633.4" cy="203" r="5"/>
<circle class="semq-chart__dot is-semq" cx="640.8" cy="203" r="5"/>
<text class="semq-chart__value" x="650.8" y="207">99–100%</text></g>
<g><title>RaBitQ · 4.6–10.5 bits/dim: 99.5% to 101.0% of FP32 nDCG@10 across 6 runs</title>
<text class="semq-chart__label" x="220" y="237" text-anchor="end">RaBitQ · 4.6–10.5 bits/dim</text>
<line class="semq-chart__range is-comparison" x1="637.8" x2="646.5" y1="233" y2="233"/>
<circle class="semq-chart__dot is-comparison" cx="637.8" cy="233" r="5"/>
<circle class="semq-chart__dot is-comparison" cx="646.5" cy="233" r="5"/>
<text class="semq-chart__value" x="656.5" y="237">100–101%</text></g>
<g><title>SEMQ orbit · 8 bits/dim: 97.4% to 100.2% of FP32 nDCG@10 across 6 runs</title>
<text class="semq-chart__label" x="220" y="267" text-anchor="end">SEMQ orbit · 8 bits/dim</text>
<line class="semq-chart__range is-semq" x1="625.3" x2="641.6" y1="263" y2="263"/>
<circle class="semq-chart__dot is-semq" cx="625.3" cy="263" r="5"/>
<circle class="semq-chart__dot is-semq" cx="641.6" cy="263" r="5"/>
<text class="semq-chart__value" x="651.6" y="267">97–100%</text></g>
<g><title>INT8 · 8 bits/dim: 99.8% to 100.4% of FP32 nDCG@10 across 6 runs</title>
<text class="semq-chart__label" x="220" y="297" text-anchor="end">INT8 · 8 bits/dim</text>
<line class="semq-chart__range is-comparison" x1="639.5" x2="642.9" y1="293" y2="293"/>
<circle class="semq-chart__dot is-comparison" cx="639.5" cy="293" r="5"/>
<circle class="semq-chart__dot is-comparison" cx="642.9" cy="293" r="5"/>
<text class="semq-chart__value" x="652.9" y="297">100–100%</text></g>
<text class="semq-chart__axis" x="450" y="348" text-anchor="middle">nDCG@10 kept relative to FP32 · the line spans the lowest and highest of six runs</text>
</svg>
</figure>

??? info "Table view"

    | Format | Bits per dimension | Lowest | Highest |
    | --- | ---: | ---: | ---: |
    | Binary, sentence-transformers | 1 | 38.4% | 98.7% |
    | SEMQ phase · 16 sectors | 2 | 75.5% | 99.6% |
    | SEMQ quant · 2 bits | 2 | 81.8% | 99.4% |
    | Faiss PQ · 2 bits | 2.0–2.1 | 94.9% | 100.5% |
    | TurboQuant · 2 bits | 2.3–8.4 | 81.9% | 99.9% |
    | SEMQ quant · 3 bits | 3 | 94.7% | 100.5% |
    | SEMQ quant · 4 bits | 4 | 98.8% | 100.0% |
    | RaBitQ · 4 bits | 4.6–10.5 | 99.5% | 101.0% |
    | SEMQ orbit · scale 50 | 8 | 97.4% | 100.2% |
    | INT8, sentence-transformers | 8 | 99.8% | 100.4% |


A value above 100% means the ranking scored slightly better against the available relevance judgments; it is not a quality improvement in general. Queries search decoded rows by cosine, with no rescoring.

### Explore one run

Pick a model and a dataset to see every measured format at its storage cost.

<div class="semq-benchmark-explorer" data-semq-benchmark-explorer data-source="../assets/benchmarks/summary/quality.json">
  <p class="semq-benchmark-explorer__status" role="status">Loading measured results…</p>
</div>

## Storage per vector

Bytes per 768-dimension vector, codes only. A `.semq` file adds an 8-byte id per row and a fixed header; Faiss PQ also stores a codebook once.

<figure class="semq-chart" role="group" aria-label="Bytes per 768-dimension vector, per format">
<svg viewBox="0 0 760 352" xmlns="http://www.w3.org/2000/svg">
<line class="semq-chart__grid" x1="230.0" x2="230.0" y1="8" y2="308"/>
<text class="semq-chart__tick" x="230.0" y="324" text-anchor="middle">0</text>
<line class="semq-chart__grid" x1="345.0" x2="345.0" y1="8" y2="308"/>
<text class="semq-chart__tick" x="345.0" y="324" text-anchor="middle">1,000</text>
<line class="semq-chart__grid" x1="460.0" x2="460.0" y1="8" y2="308"/>
<text class="semq-chart__tick" x="460.0" y="324" text-anchor="middle">2,000</text>
<line class="semq-chart__grid" x1="575.0" x2="575.0" y1="8" y2="308"/>
<text class="semq-chart__tick" x="575.0" y="324" text-anchor="middle">3,000</text>
<line class="semq-chart__grid" x1="690.0" x2="690.0" y1="8" y2="308"/>
<text class="semq-chart__tick" x="690.0" y="324" text-anchor="middle">4,000</text>
<g><title>Binary: 96 B bytes per vector</title>
<text class="semq-chart__label" x="220" y="27" text-anchor="end">Binary</text>
<path class="semq-chart__bar is-comparison" d="M230.0,15.0h7.0a4.0,4.0 0 0 1 4.0,4.0v8.0a4.0,4.0 0 0 1 -4.0,4.0h-7.0z"/>
<text class="semq-chart__value" x="247.0" y="27">96 B</text></g>
<g><title>SEMQ quant · 2 bits: 192 B bytes per vector</title>
<text class="semq-chart__label" x="220" y="57" text-anchor="end">SEMQ quant · 2 bits</text>
<path class="semq-chart__bar is-semq" d="M230.0,45.0h18.1a4.0,4.0 0 0 1 4.0,4.0v8.0a4.0,4.0 0 0 1 -4.0,4.0h-18.1z"/>
<text class="semq-chart__value" x="258.1" y="57">192 B</text></g>
<g><title>SEMQ phase · 16 sectors: 192 B bytes per vector</title>
<text class="semq-chart__label" x="220" y="87" text-anchor="end">SEMQ phase · 16 sectors</text>
<path class="semq-chart__bar is-semq" d="M230.0,75.0h18.1a4.0,4.0 0 0 1 4.0,4.0v8.0a4.0,4.0 0 0 1 -4.0,4.0h-18.1z"/>
<text class="semq-chart__value" x="258.1" y="87">192 B</text></g>
<g><title>Faiss PQ: 192 B bytes per vector</title>
<text class="semq-chart__label" x="220" y="117" text-anchor="end">Faiss PQ</text>
<path class="semq-chart__bar is-comparison" d="M230.0,105.0h18.1a4.0,4.0 0 0 1 4.0,4.0v8.0a4.0,4.0 0 0 1 -4.0,4.0h-18.1z"/>
<text class="semq-chart__value" x="258.1" y="117">192 B</text></g>
<g><title>SEMQ quant · 3 bits: 288 B bytes per vector</title>
<text class="semq-chart__label" x="220" y="147" text-anchor="end">SEMQ quant · 3 bits</text>
<path class="semq-chart__bar is-semq" d="M230.0,135.0h29.1a4.0,4.0 0 0 1 4.0,4.0v8.0a4.0,4.0 0 0 1 -4.0,4.0h-29.1z"/>
<text class="semq-chart__value" x="269.1" y="147">288 B</text></g>
<g><title>SEMQ quant · 4 bits: 384 B bytes per vector</title>
<text class="semq-chart__label" x="220" y="177" text-anchor="end">SEMQ quant · 4 bits</text>
<path class="semq-chart__bar is-semq" d="M230.0,165.0h40.2a4.0,4.0 0 0 1 4.0,4.0v8.0a4.0,4.0 0 0 1 -4.0,4.0h-40.2z"/>
<text class="semq-chart__value" x="280.2" y="177">384 B</text></g>
<g><title>SEMQ orbit · scale 50: 768 B bytes per vector</title>
<text class="semq-chart__label" x="220" y="207" text-anchor="end">SEMQ orbit · scale 50</text>
<path class="semq-chart__bar is-semq" d="M230.0,195.0h84.3a4.0,4.0 0 0 1 4.0,4.0v8.0a4.0,4.0 0 0 1 -4.0,4.0h-84.3z"/>
<text class="semq-chart__value" x="324.3" y="207">768 B</text></g>
<g><title>INT8: 772 B bytes per vector</title>
<text class="semq-chart__label" x="220" y="237" text-anchor="end">INT8</text>
<path class="semq-chart__bar is-comparison" d="M230.0,225.0h84.8a4.0,4.0 0 0 1 4.0,4.0v8.0a4.0,4.0 0 0 1 -4.0,4.0h-84.8z"/>
<text class="semq-chart__value" x="324.8" y="237">772 B</text></g>
<g><title>FP16: 1,536 B bytes per vector</title>
<text class="semq-chart__label" x="220" y="267" text-anchor="end">FP16</text>
<path class="semq-chart__bar is-comparison" d="M230.0,255.0h172.6a4.0,4.0 0 0 1 4.0,4.0v8.0a4.0,4.0 0 0 1 -4.0,4.0h-172.6z"/>
<text class="semq-chart__value" x="412.6" y="267">1,536 B</text></g>
<g><title>FP32: 3,072 B bytes per vector</title>
<text class="semq-chart__label" x="220" y="297" text-anchor="end">FP32</text>
<path class="semq-chart__bar is-comparison" d="M230.0,285.0h349.3a4.0,4.0 0 0 1 4.0,4.0v8.0a4.0,4.0 0 0 1 -4.0,4.0h-349.3z"/>
<text class="semq-chart__value" x="589.3" y="297">3,072 B</text></g>
<text class="semq-chart__axis" x="460" y="348" text-anchor="middle">bytes per vector</text>
</svg>
</figure>

??? info "Table view"

    | Format | Bytes per vector | Smaller than FP32 | GB for 100M vectors |
    | --- | ---: | ---: | ---: |
    | Binary | 96 | 32.0× | 9.6 |
    | SEMQ quant · 2 bits | 192 | 16.0× | 19.2 |
    | SEMQ phase · 16 sectors | 192 | 16.0× | 19.2 |
    | Faiss PQ | 192 | 16.0× | 19.2 |
    | SEMQ quant · 3 bits | 288 | 10.7× | 28.8 |
    | SEMQ quant · 4 bits | 384 | 8.0× | 38.4 |
    | SEMQ orbit · scale 50 | 768 | 4.0× | 76.8 |
    | INT8 | 772 | 4.0× | 77.2 |
    | FP16 | 1,536 | 2.0× | 153.6 |
    | FP32 | 3,072 | 1.0× | 307.2 |


## Encode and decode speed

Vectors per second for 768-dimension rows, measured from Python on one arm64 CPU with the `neon` backend, median of five runs. Encode includes the unit-norm check and the state's digests.

<figure class="semq-chart" role="group" aria-label="Encode and decode throughput in vectors per second, 768 dimensions, per SEMQ configuration">
<svg viewBox="0 0 760 294" xmlns="http://www.w3.org/2000/svg">
<line class="semq-chart__grid" x1="230.0" x2="230.0" y1="30" y2="250"/>
<text class="semq-chart__tick" x="230.0" y="266" text-anchor="middle">0</text>
<line class="semq-chart__grid" x1="361.4" x2="361.4" y1="30" y2="250"/>
<text class="semq-chart__tick" x="361.4" y="266" text-anchor="middle">2.0M</text>
<line class="semq-chart__grid" x1="492.9" x2="492.9" y1="30" y2="250"/>
<text class="semq-chart__tick" x="492.9" y="266" text-anchor="middle">4.0M</text>
<line class="semq-chart__grid" x1="624.3" x2="624.3" y1="30" y2="250"/>
<text class="semq-chart__tick" x="624.3" y="266" text-anchor="middle">6.0M</text>
<text class="semq-chart__label" x="220" y="55" text-anchor="end">SEMQ quant · 2 bits</text>
<g><title>SEMQ quant · 2 bits, encode: 875,934 vectors per second</title>
<path class="semq-chart__bar is-encode" d="M230.0,35.0h53.6a4.0,4.0 0 0 1 4.0,4.0v6.0a4.0,4.0 0 0 1 -4.0,4.0h-53.6z"/>
<text class="semq-chart__value" x="293.6" y="46">876k</text></g>
<g><title>SEMQ quant · 2 bits, decode: 1,165,874 vectors per second</title>
<path class="semq-chart__bar is-decode" d="M230.0,52.0h72.6a4.0,4.0 0 0 1 4.0,4.0v6.0a4.0,4.0 0 0 1 -4.0,4.0h-72.6z"/>
<text class="semq-chart__value" x="312.6" y="63">1.2M</text></g>
<text class="semq-chart__label" x="220" y="99" text-anchor="end">SEMQ quant · 3 bits</text>
<g><title>SEMQ quant · 3 bits, encode: 798,074 vectors per second</title>
<path class="semq-chart__bar is-encode" d="M230.0,79.0h48.4a4.0,4.0 0 0 1 4.0,4.0v6.0a4.0,4.0 0 0 1 -4.0,4.0h-48.4z"/>
<text class="semq-chart__value" x="288.4" y="90">798k</text></g>
<g><title>SEMQ quant · 3 bits, decode: 902,340 vectors per second</title>
<path class="semq-chart__bar is-decode" d="M230.0,96.0h55.3a4.0,4.0 0 0 1 4.0,4.0v6.0a4.0,4.0 0 0 1 -4.0,4.0h-55.3z"/>
<text class="semq-chart__value" x="295.3" y="107">902k</text></g>
<text class="semq-chart__label" x="220" y="143" text-anchor="end">SEMQ quant · 4 bits</text>
<g><title>SEMQ quant · 4 bits, encode: 795,248 vectors per second</title>
<path class="semq-chart__bar is-encode" d="M230.0,123.0h48.3a4.0,4.0 0 0 1 4.0,4.0v6.0a4.0,4.0 0 0 1 -4.0,4.0h-48.3z"/>
<text class="semq-chart__value" x="288.3" y="134">795k</text></g>
<g><title>SEMQ quant · 4 bits, decode: 712,510 vectors per second</title>
<path class="semq-chart__bar is-decode" d="M230.0,140.0h42.8a4.0,4.0 0 0 1 4.0,4.0v6.0a4.0,4.0 0 0 1 -4.0,4.0h-42.8z"/>
<text class="semq-chart__value" x="282.8" y="151">713k</text></g>
<text class="semq-chart__label" x="220" y="187" text-anchor="end">SEMQ phase · 16 sectors</text>
<g><title>SEMQ phase · 16 sectors, encode: 691,664 vectors per second</title>
<path class="semq-chart__bar is-encode" d="M230.0,167.0h41.5a4.0,4.0 0 0 1 4.0,4.0v6.0a4.0,4.0 0 0 1 -4.0,4.0h-41.5z"/>
<text class="semq-chart__value" x="281.5" y="178">692k</text></g>
<g><title>SEMQ phase · 16 sectors, decode: 6,473,382 vectors per second</title>
<path class="semq-chart__bar is-decode" d="M230.0,184.0h421.4a4.0,4.0 0 0 1 4.0,4.0v6.0a4.0,4.0 0 0 1 -4.0,4.0h-421.4z"/>
<text class="semq-chart__value" x="661.4" y="195">6.5M</text></g>
<text class="semq-chart__label" x="220" y="231" text-anchor="end">SEMQ orbit · scale 50</text>
<g><title>SEMQ orbit · scale 50, encode: 618,763 vectors per second</title>
<path class="semq-chart__bar is-encode" d="M230.0,211.0h36.7a4.0,4.0 0 0 1 4.0,4.0v6.0a4.0,4.0 0 0 1 -4.0,4.0h-36.7z"/>
<text class="semq-chart__value" x="276.7" y="222">619k</text></g>
<g><title>SEMQ orbit · scale 50, decode: 2,319,688 vectors per second</title>
<path class="semq-chart__bar is-decode" d="M230.0,228.0h148.4a4.0,4.0 0 0 1 4.0,4.0v6.0a4.0,4.0 0 0 1 -4.0,4.0h-148.4z"/>
<text class="semq-chart__value" x="388.4" y="239">2.3M</text></g>
<rect class="semq-chart__bar is-encode" x="230" y="5" width="12" height="10" rx="3"/>
<text class="semq-chart__label" x="248" y="14">Encode</text>
<rect class="semq-chart__bar is-decode" x="320" y="5" width="12" height="10" rx="3"/>
<text class="semq-chart__label" x="338" y="14">Decode</text>
<text class="semq-chart__axis" x="460" y="290" text-anchor="middle">Vectors per second, 768 dimensions, one thread from Python</text>
</svg>
</figure>

??? info "Table view"

    | Format | Encode, vectors/s | Decode, vectors/s |
    | --- | ---: | ---: |
    | SEMQ quant · 2 bits | 875,934 | 1,165,874 |
    | SEMQ quant · 3 bits | 798,074 | 902,340 |
    | SEMQ quant · 4 bits | 795,248 | 712,510 |
    | SEMQ phase · 16 sectors | 691,664 | 6,473,382 |
    | SEMQ orbit · scale 50 | 618,763 | 2,319,688 |
    | NumPy binary | 6,536,037 | 3,060,038 |
    | NumPy fp16 | 22,920,225 | 25,037,820 |
    | NumPy int8 | 1,472,129 | 3,311,098 |


The table also lists plain NumPy casts to FP16, INT8 and binary for scale: they convert arrays and compute no identity.

## Choose a configuration

| Configuration | Bits per dimension | Bytes per vector (768) | Search quality kept | Encode, vectors/s |
| --- | ---: | ---: | ---: | ---: |
| SEMQ quant · 2 bits | 2 | 192 | 81.8–99.4% | 876k |
| SEMQ quant · 3 bits | 3 | 288 | 94.7–100.5% | 798k |
| SEMQ quant · 4 bits | 4 | 384 | 98.8–100.0% | 795k |
| SEMQ phase · 16 sectors | 2 | 192 | 75.5–99.6% | 692k |
| SEMQ orbit · scale 50 | 8 | 768 | 97.4–100.2% | 619k |

[Quality data](../assets/benchmarks/summary/quality.json) · [Storage data](../assets/benchmarks/summary/size.json) · [Throughput data](../assets/benchmarks/summary/speed.json) · [Extended evaluation with uncertainty intervals](../guides/benchmark-results.md) · [Methodology](../guides/benchmark-protocol.md)

## Other measurements

- [Rebuild detection](rebuild.md): does the gate pass a rebuild that changed nothing, and fail one that did?
- [Scale and portability](scale.md): a million rows, and the same bytes on every platform.
