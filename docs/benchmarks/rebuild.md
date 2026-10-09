---
title: Rebuild detection
---

# Rebuild detection

Re-embedding a corpus rarely gives the same floats twice: another device or batch size moves the last digits. SEMQ turns each embedding into symbols, reports which rows changed, and compares the change with the noise measured on rebuilds that changed nothing. Passing the gate means the candidate stayed within that noise; it does not establish semantic equivalence.

<figure class="semq-figure"><img src="../../assets/images/rebuild-noise-vs-change.svg" alt="The same document rebuilt on another device gives other floats but the same symbols; an edited document changes symbols and its row is reported"></figure>

Illustrative values. Real rebuilds can also change a few symbols, which the floor tolerates, and a small edit can leave every symbol unchanged.

**Setup:** 5,183 SciFact documents · `e5-small-v2` · quant with four bins.

- **No false alarms on real rebuilds:** none with 20 rebuilds in the floor, over 2,000 resamples of 28 rebuilds, where a hash of the floats, `np.allclose` and a fixed tolerance rejected all of them.
- **Real changes caught:** 4 of 4 pipeline changes, and one swapped word in one document 96.8% of the time.
- **A compact, portable state.** A float check calibrated on the same rebuilds catches content changes as well, catches small numeric faults better and can list rows too; SEMQ compares a compact state that every platform reads the same way and reports a structured diff.

## How the gate decides

Here a row is one document's embedding. The reference is the state you trust; a candidate is a new rebuild. A row's hamming is how many of its symbols differ from the reference, and the p99 is taken over the changed rows only, not over the whole corpus.

<figure class="semq-diagram" role="img" aria-label="How the gate decides: a floor measured once from rebuilds with no change, and a candidate whose three values are each compared with the floor's bound">
<svg viewBox="0 -4 760 316" xmlns="http://www.w3.org/2000/svg">
<defs>
<marker id="gate-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L8,4 L0,8 z" class="semq-diagram__head"/></marker>
</defs>
<text class="semq-diagram__edge" x="232" y="10" text-anchor="start">measured once</text>
<text class="semq-diagram__edge" x="232" y="302" text-anchor="start">each candidate</text>
<text class="semq-diagram__edge" x="750" y="302" text-anchor="end">Example: one candidate from the synthetic pool below</text>
<rect class="semq-diagram__box is-input" x="24" y="16" width="140" height="52" rx="6"/>
<rect class="semq-diagram__box is-input" x="20" y="20" width="140" height="52" rx="6"/>
<rect class="semq-diagram__box is-input" x="16" y="24" width="140" height="52" rx="6"/>
<text class="semq-diagram__title" x="86" y="46" text-anchor="middle">Rebuilds with</text>
<text class="semq-diagram__title" x="86" y="62" text-anchor="middle">no change (20)</text>
<rect class="semq-diagram__box is-input" x="16" y="122" width="140" height="52" rx="6"/>
<text class="semq-diagram__title" x="86" y="152" text-anchor="middle">Reference state</text>
<rect class="semq-diagram__box is-input" x="16" y="220" width="140" height="52" rx="6"/>
<text class="semq-diagram__title" x="86" y="250" text-anchor="middle">Candidate rebuild</text>
<polyline class="semq-diagram__arrow" points="166,48 214,48" marker-end="url(#gate-arrow)"/>
<text class="semq-diagram__edge" x="190" y="40" text-anchor="middle">diff each</text>
<polyline class="semq-diagram__arrow" points="156,246 214,246" marker-end="url(#gate-arrow)"/>
<text class="semq-diagram__edge" x="186" y="264" text-anchor="middle">diff</text>
<polyline class="semq-diagram__link" points="156,148 186,148 186,56"/>
<polyline class="semq-diagram__link" points="186,148 186,238"/>
<text class="semq-diagram__edge" x="192" y="152" text-anchor="start">against it</text>
<rect class="semq-diagram__box is-floor" x="218" y="14" width="184" height="104" rx="6"/>
<text class="semq-diagram__title" x="232" y="36" text-anchor="start">Floor</text>
<rect class="semq-diagram__box " x="218" y="186" width="184" height="104" rx="6"/>
<text class="semq-diagram__title" x="232" y="208" text-anchor="start">Candidate's diff</text>
<text class="semq-diagram__text" x="232" y="58" text-anchor="start">changed rows</text>
<text class="semq-diagram__value" x="388" y="58" text-anchor="end">≤ 280</text>
<text class="semq-diagram__text" x="232" y="230" text-anchor="start">changed rows</text>
<text class="semq-diagram__value" x="388" y="230" text-anchor="end">243</text>
<text class="semq-diagram__text" x="232" y="78" text-anchor="start">p99 hamming</text>
<text class="semq-diagram__value" x="388" y="78" text-anchor="end">≤ 2</text>
<text class="semq-diagram__text" x="232" y="250" text-anchor="start">p99 hamming</text>
<text class="semq-diagram__value" x="388" y="250" text-anchor="end">2</text>
<text class="semq-diagram__text" x="232" y="98" text-anchor="start">largest row</text>
<text class="semq-diagram__value" x="388" y="98" text-anchor="end">≤ 3</text>
<text class="semq-diagram__text" x="232" y="270" text-anchor="start">largest row</text>
<text class="semq-diagram__value" x="388" y="270" text-anchor="end">267</text>
<rect class="semq-diagram__box " x="446" y="94" width="196" height="108" rx="6"/>
<text class="semq-diagram__title" x="460" y="116" text-anchor="start">Compare</text>
<text class="semq-diagram__value" x="460" y="140" text-anchor="start">243 ≤ 280</text>
<text class="semq-diagram__ok" x="628" y="140" text-anchor="end">✓ changed_ratio</text>
<text class="semq-diagram__value" x="460" y="160" text-anchor="start">2 ≤ 2</text>
<text class="semq-diagram__ok" x="628" y="160" text-anchor="end">✓ hamming</text>
<text class="semq-diagram__value" x="460" y="180" text-anchor="start">267 ≤ 3</text>
<text class="semq-diagram__bad" x="628" y="180" text-anchor="end">✗ per-row</text>
<polyline class="semq-diagram__arrow" points="402,66 424,66 424,120 442,120" marker-end="url(#gate-arrow)"/>
<text class="semq-diagram__edge" x="424" y="58" text-anchor="middle">bounds</text>
<polyline class="semq-diagram__arrow" points="402,238 424,238 424,176 442,176" marker-end="url(#gate-arrow)"/>
<text class="semq-diagram__edge" x="424" y="254" text-anchor="middle">values</text>
<rect class="semq-diagram__box is-fail" x="670" y="102" width="80" height="92" rx="6"/>
<polyline class="semq-diagram__arrow" points="642,148 666,148" marker-end="url(#gate-arrow)"/>
<text class="semq-diagram__bad" x="710" y="128" text-anchor="middle">Fail</text>
<text class="semq-diagram__text" x="710" y="150" text-anchor="middle">per-row</text>
<text class="semq-diagram__text" x="710" y="170" text-anchor="middle">2 rows</text>
<text class="semq-diagram__text" x="710" y="184" text-anchor="middle">named</text>
</svg>
</figure>

The floor is measured once, from rebuilds with no change. Each candidate is diffed against the same reference, and each of its values is compared with the floor's bound: `within` checks the first two, and `--per-row` adds the largest row.

## Real pipeline changes

A floor measured from 3 unchanged rebuilds, then seven candidates: two more unchanged rebuilds and five changes to the pipeline. Each bar is the share of rows whose symbols changed, not how serious the change is. Moving the normalization after the model shifts no coordinate by more than 3e-8, so it counts as no change: four real changes remain.

Hardware: CPU: Apple M4 Pro (arm64) · GPU: Apple M4 Pro (MPS).

<div class="semq-scenarios">
<div class="semq-scenario is-pass">
<div class="semq-scenario__head"><strong>GPU rebuild, different batch size</strong><span>0.10% · within floor</span></div>
<div class="semq-scenario__track"><span style="width:0.10%;min-width:2px"></span></div>
</div>
<div class="semq-scenario is-pass">
<div class="semq-scenario__head"><strong>CPU rebuild, one document per batch</strong><span>0.02% · within floor</span></div>
<div class="semq-scenario__track"><span style="width:0.02%;min-width:2px"></span></div>
</div>
<div class="semq-scenario is-fail">
<div class="semq-scenario__head"><strong>Previous encoder revision</strong><span>100% · outside floor</span></div>
<div class="semq-scenario__track"><span style="width:100.00%;min-width:2px"></span></div>
</div>
<div class="semq-scenario is-fail">
<div class="semq-scenario__head"><strong>Half precision</strong><span>51.0% · outside floor</span></div>
<div class="semq-scenario__track"><span style="width:50.96%;min-width:2px"></span></div>
</div>
<div class="semq-scenario is-fail">
<div class="semq-scenario__head"><strong>128-token truncation</strong><span>98.1% · outside floor</span></div>
<div class="semq-scenario__track"><span style="width:98.05%;min-width:2px"></span></div>
</div>
<div class="semq-scenario is-fail">
<div class="semq-scenario__head"><strong>CLS instead of mean pooling</strong><span>100% · outside floor</span></div>
<div class="semq-scenario__track"><span style="width:100.00%;min-width:2px"></span></div>
</div>
<div class="semq-scenario is-pass">
<div class="semq-scenario__head"><strong>Normalization moved after the model</strong><span>0% · within floor</span></div>
<div class="semq-scenario__track"><span style="width:0.00%;min-width:0px"></span></div>
</div>
</div>

The floor allowed 5 of 5,183 rows to change, by at most 1 symbol each.

**The same runs, judged by other checks.** A false alarm flags a rebuild that changed nothing; a miss lets a real change pass.

| Check | False alarms on rebuilds | Real changes missed |
| --- | ---: | ---: |
| Hash of the FP32 bytes | 5 of 5 | 0 of 4 |
| `np.allclose`, default tolerances | 5 of 5 | 0 of 4 |
| Any row with cosine below 0.9999 | 0 of 5 | 1 of 4 (the precision) |
| Largest absolute difference, calibrated on the nulls | 0 of 5 | 0 of 4 |
| SEMQ diff against its floor | 0 of 5 | 0 of 4 |

Hashing the floats fails on every rebuild, because devices and batch sizes change the last bits. A cosine threshold loose enough for that noise also lets a switch to half precision pass. A threshold on the largest difference works when it is calibrated on your own rebuilds, which is what the floor does.

Source: [`rebuild.json`](../assets/benchmarks/summary/rebuild.json), produced by `python -m benchmarks.rebuild`.

## False alarms and detection power

28 rebuilds of the same corpus that change only the device, the batch size and the input order. Every rebuild gave different floats, but there were only 5 SEMQ states: 9 matched the reference and the other 19 changed 1 to 2 rows (hamming at most 1).

Each of 2,000 draws holds out one rebuild, measures a floor from N of the others, and judges the held-out rebuild, then the same rebuild with one fault. Calibrated float checks take their threshold from the same N rebuilds. Intervals are 95% Clopper–Pearson.

**False alarms.** With 20 rebuilds in the floor, the floor and both calibrated float checks raised none in 2,000 draws (95% interval 0%–0.18%). A hash of the floats, `np.allclose` and a fixed tolerance of one bfloat16 spacing rejected every rebuild. With only 3 rebuilds in the floor, the floor raised 8.7% and the calibrated float checks 5.6% to 9.8%: a floor from a few rebuilds is tighter than the noise. The draws resample the same 28 rebuilds, so the intervals describe this pool, not every future rebuild.

??? info "False alarms by check"

    | Check | False alarms | 95% interval |
    | --- | ---: | ---: |
    | SEMQ floor, `within` | 0% | 0%–0.18% |
    | SEMQ floor, per-row | 0% | 0%–0.18% |
    | Largest absolute difference, calibrated | 0% | 0%–0.18% |
    | Lowest row cosine, calibrated | 0% | 0%–0.18% |
    | Hash of the FP32 bytes | 100% | 99.8%–100% |
    | `np.allclose`, default tolerances | 100% | 99.8%–100% |
    | Fixed tolerance of one bfloat16 spacing | 100% | 99.8%–100% |


**Detection.** Each fault is injected into a held-out rebuild. On the tested content edits, SEMQ and the calibrated float checks had similar detection rates: one replaced document 100% for every check, one swapped word 96.8% for the floor and 97.8% for the cosine check. A cut is not always a change: in documents longer than the model's 512-token limit, it removes text the model never reads.

Numeric faults move rows by less than a quantization bin. The floor sees them only when a coordinate crosses a bin edge, so the calibrated float checks catch them earlier. Size is the median 1 − cosine between a changed row and the same row before the fault.

<p class="semq-chart-legend"><span class="is-floor">SEMQ floor</span><span class="is-maxabs">largest difference, calibrated</span><span class="is-cosine">lowest cosine, calibrated</span></p>

<figure class="semq-chart" role="group" aria-label="Detection of numeric faults against their size">
<svg viewBox="0 0 760 280" xmlns="http://www.w3.org/2000/svg">
<text class="semq-chart__axis" x="50" y="16">injected faults detected (%)</text>
<line class="semq-chart__grid" x1="58" x2="736" y1="236.0" y2="236.0"/>
<text class="semq-chart__tick" x="50" y="240.0" text-anchor="end">0%</text>
<line class="semq-chart__grid" x1="58" x2="736" y1="184.5" y2="184.5"/>
<text class="semq-chart__tick" x="50" y="188.5" text-anchor="end">25%</text>
<line class="semq-chart__grid" x1="58" x2="736" y1="133.0" y2="133.0"/>
<text class="semq-chart__tick" x="50" y="137.0" text-anchor="end">50%</text>
<line class="semq-chart__grid" x1="58" x2="736" y1="81.5" y2="81.5"/>
<text class="semq-chart__tick" x="50" y="85.5" text-anchor="end">75%</text>
<line class="semq-chart__grid" x1="58" x2="736" y1="30.0" y2="30.0"/>
<text class="semq-chart__tick" x="50" y="34.0" text-anchor="end">100%</text>
<text class="semq-chart__tick" x="58.0" y="254" text-anchor="middle">1e-13</text>
<text class="semq-chart__tick" x="193.6" y="254" text-anchor="middle">1e-12</text>
<text class="semq-chart__tick" x="329.2" y="254" text-anchor="middle">1e-11</text>
<text class="semq-chart__tick" x="464.8" y="254" text-anchor="middle">1e-10</text>
<text class="semq-chart__tick" x="600.4" y="254" text-anchor="middle">1e-9</text>
<text class="semq-chart__tick" x="736.0" y="254" text-anchor="middle">1e-8</text>
<text class="semq-chart__axis" x="397" y="274" text-anchor="middle">size of the fault, 1 − cosine (log scale)</text>
<g><title>Noise on every coordinate, 1× rebuild noise: SEMQ floor 5.3%, largest difference, calibrated 31.7%, lowest cosine, calibrated 52.6%</title>
<circle class="semq-chart__mark is-floor" cx="95.8" cy="225.1" r="7"/>
<rect class="semq-chart__mark is-maxabs" x="92.3" y="167.2" width="7" height="7"/>
<path class="semq-chart__mark is-cosine" d="M95.8,123.1l4.5,4.5l-4.5,4.5l-4.5,-4.5z"/>
</g>
<g><title>Noise on every coordinate, 10× rebuild noise: SEMQ floor 100%, largest difference, calibrated 100%, lowest cosine, calibrated 100%</title>
<circle class="semq-chart__mark is-floor" cx="366.9" cy="30.0" r="7"/>
<rect class="semq-chart__mark is-maxabs" x="363.4" y="26.5" width="7" height="7"/>
<path class="semq-chart__mark is-cosine" d="M366.9,25.5l4.5,4.5l-4.5,4.5l-4.5,-4.5z"/>
</g>
<g><title>Scale 1% of coordinates by 1 + 1e-4: SEMQ floor 67.5%, largest difference, calibrated 100%, lowest cosine, calibrated 100%</title>
<circle class="semq-chart__mark is-floor" cx="412.6" cy="96.8" r="7"/>
<rect class="semq-chart__mark is-maxabs" x="409.1" y="26.5" width="7" height="7"/>
<path class="semq-chart__mark is-cosine" d="M412.6,25.5l4.5,4.5l-4.5,4.5l-4.5,-4.5z"/>
</g>
<g><title>Scale 10% of coordinates by 1 + 1e-4: SEMQ floor 100%, largest difference, calibrated 100%, lowest cosine, calibrated 100%</title>
<circle class="semq-chart__mark is-floor" cx="551.5" cy="30.0" r="7"/>
<rect class="semq-chart__mark is-maxabs" x="548.0" y="26.5" width="7" height="7"/>
<path class="semq-chart__mark is-cosine" d="M551.5,25.5l4.5,4.5l-4.5,4.5l-4.5,-4.5z"/>
</g>
<g><title>Noise on every coordinate, 100× rebuild noise: SEMQ floor 100%, largest difference, calibrated 100%, lowest cosine, calibrated 100%</title>
<circle class="semq-chart__mark is-floor" cx="638.1" cy="30.0" r="7"/>
<rect class="semq-chart__mark is-maxabs" x="634.6" y="26.5" width="7" height="7"/>
<path class="semq-chart__mark is-cosine" d="M638.1,25.5l4.5,4.5l-4.5,4.5l-4.5,-4.5z"/>
</g>
<g><title>Scale 1% of coordinates by 1 + 1e-3: SEMQ floor 100%, largest difference, calibrated 100%, lowest cosine, calibrated 100%</title>
<circle class="semq-chart__mark is-floor" cx="683.2" cy="30.0" r="7"/>
<rect class="semq-chart__mark is-maxabs" x="679.7" y="26.5" width="7" height="7"/>
<path class="semq-chart__mark is-cosine" d="M683.2,25.5l4.5,4.5l-4.5,4.5l-4.5,-4.5z"/>
</g>
</svg>
</figure>

??? info "Detection rates by fault"

    | Fault | Size | Floor, `within` | Floor, per-row | Largest difference, calibrated | Cosine, calibrated |
    | --- | ---: | ---: | ---: | ---: | ---: |
    | Replace 1 document | 1.9e-01 | 100% | 100% | 100% | 100% |
    | Replace 2 documents | 1.9e-01 | 100% | 100% | 100% | 100% |
    | Replace 10 documents | 1.9e-01 | 100% | 100% | 100% | 100% |
    | Cut the last 2% of one document | 1.4e-03 | 87.8% | 87.8% | 87.8% | 87.8% |
    | Cut the last 10% of one document | 2.9e-03 | 96.0% | 96.0% | 96.0% | 96.0% |
    | Cut the last 50% of one document | 1.5e-02 | 100% | 100% | 100% | 100% |
    | Swap 1 word in one document | 7.6e-04 | 96.8% | 96.8% | 97.8% | 97.8% |
    | Swap 3 words in one document | 3.3e-03 | 100% | 100% | 100% | 100% |
    | Noise on every coordinate, 1× rebuild noise | 1.9e-13 | 5.3% | 5.3% | 31.7% | 52.6% |
    | Noise on every coordinate, 10× rebuild noise | 1.9e-11 | 100% | 100% | 100% | 100% |
    | Noise on every coordinate, 100× rebuild noise | 1.9e-09 | 100% | 100% | 100% | 100% |
    | Scale 1% of coordinates by 1 + 1e-4 | 4.1e-11 | 67.5% | 67.5% | 100% | 100% |
    | Scale 1% of coordinates by 1 + 1e-3 | 4.1e-09 | 100% | 100% | 100% | 100% |
    | Scale 10% of coordinates by 1 + 1e-4 | 4.4e-10 | 100% | 100% | 100% | 100% |


Hardware: CPU: AMD EPYC 7R32 (x86_64) · GPU: NVIDIA A10G.

### When the rebuild noise varies (synthetic)

The rebuilds above changed at most 2 rows each. To test rebuilds that change hundreds of rows every time, this pool adds noise: each of 40 nulls is a GPU rebuild plus Gaussian noise (σ = 4.5e-6 per coordinate), renormalized, and changes 223 to 286 rows. It is a controlled test of varying noise, not a model of a specific GPU kernel.

**False alarms.** The floor keeps, for each statistic, the largest value over its N nulls. When the nulls and the candidate are produced the same way (exchangeable), an unchanged candidate exceeds that largest value with probability at most 1/(N+1), so a gate that checks s statistics rejects it at most s/(N+1) of the time. `within` checks two statistics and per-row adds a third. Both stay under their bound, because the statistics move together and integer hamming values tie.

<p class="semq-chart-legend"><span class="is-within">within</span><span class="is-per-row">per-row</span><span class="is-bound">bound s/(N+1)</span></p>

<figure class="semq-chart" role="group" aria-label="False alarms against the number of nulls in the floor">
<svg viewBox="0 0 760 280" xmlns="http://www.w3.org/2000/svg">
<text class="semq-chart__axis" x="50" y="12">false-alarm rate (%)</text>
<line class="semq-chart__grid" x1="58" x2="610" y1="236.0" y2="236.0"/>
<text class="semq-chart__tick" x="50" y="240.0" text-anchor="end">0%</text>
<line class="semq-chart__grid" x1="58" x2="610" y1="180.5" y2="180.5"/>
<text class="semq-chart__tick" x="50" y="184.5" text-anchor="end">20%</text>
<line class="semq-chart__grid" x1="58" x2="610" y1="125.0" y2="125.0"/>
<text class="semq-chart__tick" x="50" y="129.0" text-anchor="end">40%</text>
<line class="semq-chart__grid" x1="58" x2="610" y1="69.5" y2="69.5"/>
<text class="semq-chart__tick" x="50" y="73.5" text-anchor="end">60%</text>
<line class="semq-chart__grid" x1="58" x2="610" y1="14.0" y2="14.0"/>
<text class="semq-chart__tick" x="50" y="18.0" text-anchor="end">80%</text>
<text class="semq-chart__tick" x="58.0" y="254" text-anchor="middle">3</text>
<text class="semq-chart__tick" x="167.9" y="254" text-anchor="middle">5</text>
<text class="semq-chart__tick" x="317.1" y="254" text-anchor="middle">10</text>
<text class="semq-chart__tick" x="466.3" y="254" text-anchor="middle">20</text>
<text class="semq-chart__tick" x="610.0" y="254" text-anchor="middle">39</text>
<text class="semq-chart__axis" x="334" y="274" text-anchor="middle">nulls in the floor (N, log scale)</text>
<polyline class="semq-chart__bound is-within" points="58.0,97.2 67.2,101.7 76.4,106.0 85.6,110.2 94.8,114.3 104.0,118.3 113.2,122.2 122.4,126.0 131.6,129.7 140.8,133.4 150.0,136.9 159.2,140.3 168.4,143.7 177.6,146.9 186.8,150.1 196.0,153.1 205.2,156.1 214.4,159.0 223.6,161.8 232.8,164.5 242.0,167.1 251.2,169.6 260.4,172.1 269.6,174.5 278.8,176.8 288.0,179.0 297.2,181.1 306.4,183.2 315.6,185.2 324.8,187.2 334.0,189.0 343.2,190.8 352.4,192.6 361.6,194.3 370.8,195.9 380.0,197.4 389.2,198.9 398.4,200.4 407.6,201.8 416.8,203.1 426.0,204.4 435.2,205.7 444.4,206.9 453.6,208.0 462.8,209.2 472.0,210.2 481.2,211.3 490.4,212.3 499.6,213.2 508.8,214.1 518.0,215.0 527.2,215.9 536.4,216.7 545.6,217.4 554.8,218.2 564.0,218.9 573.2,219.6 582.4,220.3 591.6,220.9 600.8,221.5 610.0,222.1"/>
<text class="semq-chart__note" x="68.0" y="91.2">bound 2/(N+1)</text>
<polyline class="semq-chart__line is-within" points="58.0,160.8 167.9,185.1 317.1,208.1 466.3,220.9 610.0,228.9"/>
<g><title>within, 3 nulls: 27.1% (95% interval 25.2%–29.1%; bound 50.0%)</title><circle class="semq-chart__point is-within" cx="58.0" cy="160.8" r="4.5"/></g>
<g><title>within, 5 nulls: 18.4% (95% interval 16.7%–20.1%; bound 33.3%)</title><circle class="semq-chart__point is-within" cx="167.9" cy="185.1" r="4.5"/></g>
<g><title>within, 10 nulls: 10.1% (95% interval 8.8%–11.5%; bound 18.2%)</title><circle class="semq-chart__point is-within" cx="317.1" cy="208.1" r="4.5"/></g>
<g><title>within, 20 nulls: 5.5% (95% interval 4.5%–6.5%; bound 9.5%)</title><circle class="semq-chart__point is-within" cx="466.3" cy="220.9" r="4.5"/></g>
<g><title>within, 39 nulls: 2.5% (95% interval 1.9%–3.3%; bound 5.0%)</title><circle class="semq-chart__point is-within" cx="610.0" cy="228.9" r="4.5"/></g>
<polyline class="semq-chart__bound is-per-row" points="58.0,27.9 67.2,34.5 76.4,40.9 85.6,47.2 94.8,53.4 104.0,59.4 113.2,65.3 122.4,71.0 131.6,76.6 140.8,82.1 150.0,87.3 159.2,92.5 168.4,97.5 177.6,102.4 186.8,107.1 196.0,111.7 205.2,116.1 214.4,120.5 223.6,124.6 232.8,128.7 242.0,132.6 251.2,136.4 260.4,140.1 269.6,143.7 278.8,147.1 288.0,150.5 297.2,153.7 306.4,156.8 315.6,159.8 324.8,162.7 334.0,165.5 343.2,168.3 352.4,170.9 361.6,173.4 370.8,175.8 380.0,178.2 389.2,180.4 398.4,182.6 407.6,184.7 416.8,186.7 426.0,188.7 435.2,190.5 444.4,192.3 453.6,194.1 462.8,195.7 472.0,197.3 481.2,198.9 490.4,200.4 499.6,201.8 508.8,203.2 518.0,204.5 527.2,205.8 536.4,207.0 545.6,208.2 554.8,209.3 564.0,210.4 573.2,211.4 582.4,212.4 591.6,213.4 600.8,214.3 610.0,215.2"/>
<text class="semq-chart__note" x="68.0" y="21.9">bound 3/(N+1)</text>
<polyline class="semq-chart__line is-per-row" points="58.0,154.0 167.9,177.9 317.1,200.9 466.3,213.7 610.0,221.7"/>
<g><title>per-row, 3 nulls: 29.5% (95% interval 27.6%–31.6%; bound 75.0%)</title><circle class="semq-chart__point is-per-row" cx="58.0" cy="154.0" r="4.5"/></g>
<g><title>per-row, 5 nulls: 20.9% (95% interval 19.2%–22.8%; bound 50.0%)</title><circle class="semq-chart__point is-per-row" cx="167.9" cy="177.9" r="4.5"/></g>
<g><title>per-row, 10 nulls: 12.7% (95% interval 11.2%–14.2%; bound 27.3%)</title><circle class="semq-chart__point is-per-row" cx="317.1" cy="200.9" r="4.5"/></g>
<g><title>per-row, 20 nulls: 8.1% (95% interval 6.9%–9.3%; bound 14.3%)</title><circle class="semq-chart__point is-per-row" cx="466.3" cy="213.7" r="4.5"/></g>
<g><title>per-row, 39 nulls: 5.1% (95% interval 4.2%–6.2%; bound 7.5%)</title><circle class="semq-chart__point is-per-row" cx="610.0" cy="221.7" r="4.5"/></g>
<text class="semq-chart__label" x="622" y="222.3">per-row 5.1%</text>
<text class="semq-chart__label" x="622" y="236.3">within 2.5%</text>
</svg>
</figure>

??? info "False alarms by number of nulls"

    | Nulls in the floor | `within` | Bound | Per-row | Bound |
    | ---: | ---: | ---: | ---: | ---: |
    | 3 | 27.1% | 50.0% | 29.5% | 75.0% |
    | 5 | 18.4% | 33.3% | 20.9% | 50.0% |
    | 10 | 10.1% | 18.2% | 12.7% | 27.3% |
    | 20 | 5.5% | 9.5% | 8.1% | 14.3% |
    | 39 | 2.5% | 5.0% | 5.1% | 7.5% |


**Why `within` misses a replaced document.** One candidate from these draws, with 20 nulls in the floor: its 243 changed rows, sorted by hamming. Rebuild noise moves 241 of them by 1 or 2 units; the two replaced documents change 260 and 267. The p99 ignores the ⌊243/100⌋ = 2 most-changed rows, so it reads 2, no more than the floor's p99, and `within` passes. Per-row compares every row with `max_hamming`, the largest hamming of any row in any null, and flags the two documents.

<p class="semq-chart-legend"><span class="is-noise">rows moved by rebuild noise</span><span class="is-faulted">replaced documents</span><span class="is-within">floor p99, read by within</span><span class="is-per-row">floor max_hamming, read by per-row</span></p>

<figure class="semq-chart" role="group" aria-label="One candidate's changed rows sorted by hamming">
<svg viewBox="0 0 760 280" xmlns="http://www.w3.org/2000/svg">
<text class="semq-chart__axis" x="50" y="12" text-anchor="start">hamming (log scale)</text>
<line class="semq-chart__grid" x1="58.0" x2="261.4" y1="228.3" y2="228.3"/>
<line class="semq-chart__grid" x1="283.4" x2="736.0" y1="228.3" y2="228.3"/>
<text class="semq-chart__tick" x="50" y="232.3" text-anchor="end">1</text>
<line class="semq-chart__grid" x1="58.0" x2="261.4" y1="204.4" y2="204.4"/>
<line class="semq-chart__grid" x1="283.4" x2="736.0" y1="204.4" y2="204.4"/>
<text class="semq-chart__tick" x="50" y="208.4" text-anchor="end">2</text>
<line class="semq-chart__grid" x1="58.0" x2="261.4" y1="190.5" y2="190.5"/>
<line class="semq-chart__grid" x1="283.4" x2="736.0" y1="190.5" y2="190.5"/>
<text class="semq-chart__tick" x="50" y="194.5" text-anchor="end">3</text>
<line class="semq-chart__grid" x1="58.0" x2="261.4" y1="149.0" y2="149.0"/>
<line class="semq-chart__grid" x1="283.4" x2="736.0" y1="149.0" y2="149.0"/>
<text class="semq-chart__tick" x="50" y="153.0" text-anchor="end">10</text>
<line class="semq-chart__grid" x1="58.0" x2="261.4" y1="111.2" y2="111.2"/>
<line class="semq-chart__grid" x1="283.4" x2="736.0" y1="111.2" y2="111.2"/>
<text class="semq-chart__tick" x="50" y="115.2" text-anchor="end">30</text>
<line class="semq-chart__grid" x1="58.0" x2="261.4" y1="69.7" y2="69.7"/>
<line class="semq-chart__grid" x1="283.4" x2="736.0" y1="69.7" y2="69.7"/>
<text class="semq-chart__tick" x="50" y="73.7" text-anchor="end">100</text>
<line class="semq-chart__grid" x1="58.0" x2="261.4" y1="31.9" y2="31.9"/>
<line class="semq-chart__grid" x1="283.4" x2="736.0" y1="31.9" y2="31.9"/>
<text class="semq-chart__tick" x="50" y="35.9" text-anchor="end">300</text>
<text class="semq-chart__tick" x="58.4" y="254" text-anchor="middle">1</text>
<text class="semq-chart__tick" x="261.0" y="254" text-anchor="middle">231</text>
<text class="semq-chart__tick" x="302.3" y="254" text-anchor="middle">232</text>
<text class="semq-chart__tick" x="415.4" y="254" text-anchor="middle">235</text>
<text class="semq-chart__tick" x="528.6" y="254" text-anchor="middle">238</text>
<text class="semq-chart__tick" x="641.7" y="254" text-anchor="middle">241</text>
<text class="semq-chart__tick" x="717.1" y="254" text-anchor="middle">243</text>
<line class="semq-chart__reference" x1="266.4" x2="272.4" y1="241" y2="231"/>
<line class="semq-chart__reference" x1="272.4" x2="278.4" y1="241" y2="231"/>
<text class="semq-chart__axis" x="397" y="274" text-anchor="middle">changed rows, sorted by hamming; the last 12 drawn wide</text>
<rect class="semq-chart__band" x="660.6" y="22" width="75.4" height="214"/>
<text class="semq-chart__note" x="652.6" y="111.2" text-anchor="end">the p99 ignores these 2 rows</text>
<line class="semq-chart__threshold is-per-row" x1="58.0" x2="261.4" y1="190.5" y2="190.5"/>
<line class="semq-chart__threshold is-per-row" x1="283.4" x2="660.6" y1="190.5" y2="190.5"/>
<text class="semq-chart__note" x="66" y="184.5">floor max_hamming = 3: per-row flags any row above it</text>
<line class="semq-chart__threshold is-within" x1="58.0" x2="261.4" y1="204.4" y2="204.4"/>
<line class="semq-chart__threshold is-within" x1="283.4" x2="660.6" y1="204.4" y2="204.4"/>
<text class="semq-chart__note" x="66" y="218.4">floor p99 = 2: within compares the candidate's p99, 2</text>
<g><title>241 rows moved by rebuild noise, hamming 1 to 2</title><polyline class="semq-chart__line is-noise" points="58.4,228.3 59.3,228.3 60.2,228.3 61.1,228.3 62.0,228.3 62.8,228.3 63.7,228.3 64.6,228.3 65.5,228.3 66.4,228.3 67.2,228.3 68.1,228.3 69.0,228.3 69.9,228.3 70.8,228.3 71.6,228.3 72.5,228.3 73.4,228.3 74.3,228.3 75.2,228.3 76.1,228.3 76.9,228.3 77.8,228.3 78.7,228.3 79.6,228.3 80.5,228.3 81.3,228.3 82.2,228.3 83.1,228.3 84.0,228.3 84.9,228.3 85.7,228.3 86.6,228.3 87.5,228.3 88.4,228.3 89.3,228.3 90.1,228.3 91.0,228.3 91.9,228.3 92.8,228.3 93.7,228.3 94.5,228.3 95.4,228.3 96.3,228.3 97.2,228.3 98.1,228.3 98.9,228.3 99.8,228.3 100.7,228.3 101.6,228.3 102.5,228.3 103.3,228.3 104.2,228.3 105.1,228.3 106.0,228.3 106.9,228.3 107.7,228.3 108.6,228.3 109.5,228.3 110.4,228.3 111.3,228.3 112.2,228.3 113.0,228.3 113.9,228.3 114.8,228.3 115.7,228.3 116.6,228.3 117.4,228.3 118.3,228.3 119.2,228.3 120.1,228.3 121.0,228.3 121.8,228.3 122.7,228.3 123.6,228.3 124.5,228.3 125.4,228.3 126.2,228.3 127.1,228.3 128.0,228.3 128.9,228.3 129.8,228.3 130.6,228.3 131.5,228.3 132.4,228.3 133.3,228.3 134.2,228.3 135.0,228.3 135.9,228.3 136.8,228.3 137.7,228.3 138.6,228.3 139.4,228.3 140.3,228.3 141.2,228.3 142.1,228.3 143.0,228.3 143.9,228.3 144.7,228.3 145.6,228.3 146.5,228.3 147.4,228.3 148.3,228.3 149.1,228.3 150.0,228.3 150.9,228.3 151.8,228.3 152.7,228.3 153.5,228.3 154.4,228.3 155.3,228.3 156.2,228.3 157.1,228.3 157.9,228.3 158.8,228.3 159.7,228.3 160.6,228.3 161.5,228.3 162.3,228.3 163.2,228.3 164.1,228.3 165.0,228.3 165.9,228.3 166.7,228.3 167.6,228.3 168.5,228.3 169.4,228.3 170.3,228.3 171.1,228.3 172.0,228.3 172.9,228.3 173.8,228.3 174.7,228.3 175.5,228.3 176.4,228.3 177.3,228.3 178.2,228.3 179.1,228.3 180.0,228.3 180.8,228.3 181.7,228.3 182.6,228.3 183.5,228.3 184.4,228.3 185.2,228.3 186.1,228.3 187.0,228.3 187.9,228.3 188.8,228.3 189.6,228.3 190.5,228.3 191.4,228.3 192.3,228.3 193.2,228.3 194.0,228.3 194.9,228.3 195.8,228.3 196.7,228.3 197.6,228.3 198.4,228.3 199.3,228.3 200.2,228.3 201.1,228.3 202.0,228.3 202.8,228.3 203.7,228.3 204.6,228.3 205.5,228.3 206.4,228.3 207.2,228.3 208.1,228.3 209.0,228.3 209.9,228.3 210.8,228.3 211.7,228.3 212.5,228.3 213.4,228.3 214.3,228.3 215.2,228.3 216.1,228.3 216.9,228.3 217.8,228.3 218.7,228.3 219.6,228.3 220.5,228.3 221.3,228.3 222.2,228.3 223.1,228.3 224.0,228.3 224.9,228.3 225.7,228.3 226.6,228.3 227.5,228.3 228.4,228.3 229.3,228.3 230.1,228.3 231.0,228.3 231.9,228.3 232.8,228.3 233.7,228.3 234.5,228.3 235.4,228.3 236.3,228.3 237.2,228.3 238.1,228.3 238.9,228.3 239.8,228.3 240.7,228.3 241.6,228.3 242.5,228.3 243.3,228.3 244.2,228.3 245.1,228.3 246.0,228.3 246.9,228.3 247.8,228.3 248.6,228.3 249.5,228.3 250.4,228.3 251.3,228.3 252.2,228.3 253.0,228.3 253.9,228.3 254.8,228.3 255.7,228.3 256.6,228.3 257.4,228.3 258.3,228.3 259.2,228.3 260.1,228.3 261.0,228.3"/></g>
<g><title>241 rows moved by rebuild noise, hamming 1 to 2</title><polyline class="semq-chart__line is-noise" points="302.3,228.3 340.0,228.3 377.7,228.3 415.4,228.3 453.1,204.4 490.8,204.4 528.6,204.4 566.3,204.4 604.0,204.4 641.7,204.4"/></g>
<g><title>row 232: hamming 1, rebuild noise</title><circle class="semq-chart__point is-noise" cx="302.3" cy="228.3" r="3.5"/></g>
<g><title>row 233: hamming 1, rebuild noise</title><circle class="semq-chart__point is-noise" cx="340.0" cy="228.3" r="3.5"/></g>
<g><title>row 234: hamming 1, rebuild noise</title><circle class="semq-chart__point is-noise" cx="377.7" cy="228.3" r="3.5"/></g>
<g><title>row 235: hamming 1, rebuild noise</title><circle class="semq-chart__point is-noise" cx="415.4" cy="228.3" r="3.5"/></g>
<g><title>row 236: hamming 2, rebuild noise</title><circle class="semq-chart__point is-noise" cx="453.1" cy="204.4" r="3.5"/></g>
<g><title>row 237: hamming 2, rebuild noise</title><circle class="semq-chart__point is-noise" cx="490.8" cy="204.4" r="3.5"/></g>
<g><title>row 238: hamming 2, rebuild noise</title><circle class="semq-chart__point is-noise" cx="528.6" cy="204.4" r="3.5"/></g>
<g><title>row 239: hamming 2, rebuild noise</title><circle class="semq-chart__point is-noise" cx="566.3" cy="204.4" r="3.5"/></g>
<g><title>row 240: hamming 2, rebuild noise</title><circle class="semq-chart__point is-noise" cx="604.0" cy="204.4" r="3.5"/></g>
<g><title>row 241: hamming 2, rebuild noise</title><circle class="semq-chart__point is-noise" cx="641.7" cy="204.4" r="3.5"/></g>
<g><title>row 242: replaced document, hamming 260</title><circle class="semq-chart__point is-faulted" cx="679.4" cy="36.8" r="5"/></g>
<g><title>row 243: replaced document, hamming 267</title><circle class="semq-chart__point is-faulted" cx="717.1" cy="35.9" r="5"/></g>
<text class="semq-chart__note" x="66" y="220.3">241 rows changed by rebuild noise</text>
<text class="semq-chart__label" x="652.6" y="39.9" text-anchor="end">2 replaced documents, hamming 260 and 267</text>
</svg>
</figure>


**Detection with 20 nulls**, across all draws:

<p class="semq-chart-legend"><span class="is-within">within</span><span class="is-per-row">per-row</span></p>

<figure class="semq-chart" role="group" aria-label="Detection of replaced documents by within and per-row">
<svg viewBox="0 0 760 172" xmlns="http://www.w3.org/2000/svg">
<line class="semq-chart__grid" x1="230.0" x2="230.0" y1="8" y2="128"/>
<text class="semq-chart__tick" x="230.0" y="144" text-anchor="middle">0%</text>
<line class="semq-chart__grid" x1="345.0" x2="345.0" y1="8" y2="128"/>
<text class="semq-chart__tick" x="345.0" y="144" text-anchor="middle">25%</text>
<line class="semq-chart__grid" x1="460.0" x2="460.0" y1="8" y2="128"/>
<text class="semq-chart__tick" x="460.0" y="144" text-anchor="middle">50%</text>
<line class="semq-chart__grid" x1="575.0" x2="575.0" y1="8" y2="128"/>
<text class="semq-chart__tick" x="575.0" y="144" text-anchor="middle">75%</text>
<line class="semq-chart__grid" x1="690.0" x2="690.0" y1="8" y2="128"/>
<text class="semq-chart__tick" x="690.0" y="144" text-anchor="middle">100%</text>
<g><title>Replace 1 document, within: 5.5% of draws</title>
<text class="semq-chart__label" x="220" y="27" text-anchor="end">Replace 1 document, within</text>
<path class="semq-chart__bar is-within" d="M230.0,15.0h21.1a4.0,4.0 0 0 1 4.0,4.0v8.0a4.0,4.0 0 0 1 -4.0,4.0h-21.1z"/>
<text class="semq-chart__value" x="261.1" y="27">5.5%</text></g>
<g><title>Replace 1 document, per-row: 100% of draws</title>
<text class="semq-chart__label" x="220" y="57" text-anchor="end">Replace 1 document, per-row</text>
<path class="semq-chart__bar is-per-row" d="M230.0,45.0h456.0a4.0,4.0 0 0 1 4.0,4.0v8.0a4.0,4.0 0 0 1 -4.0,4.0h-456.0z"/>
<text class="semq-chart__value" x="696.0" y="57">100%</text></g>
<g><title>Replace 2 documents, within: 8.5% of draws</title>
<text class="semq-chart__label" x="220" y="87" text-anchor="end">Replace 2 documents, within</text>
<path class="semq-chart__bar is-within" d="M230.0,75.0h34.9a4.0,4.0 0 0 1 4.0,4.0v8.0a4.0,4.0 0 0 1 -4.0,4.0h-34.9z"/>
<text class="semq-chart__value" x="274.9" y="87">8.5%</text></g>
<g><title>Replace 2 documents, per-row: 100% of draws</title>
<text class="semq-chart__label" x="220" y="117" text-anchor="end">Replace 2 documents, per-row</text>
<path class="semq-chart__bar is-per-row" d="M230.0,105.0h456.0a4.0,4.0 0 0 1 4.0,4.0v8.0a4.0,4.0 0 0 1 -4.0,4.0h-456.0z"/>
<text class="semq-chart__value" x="696.0" y="117">100%</text></g>
<text class="semq-chart__axis" x="460" y="168" text-anchor="middle">injected changes detected (%)</text>
</svg>
</figure>

??? info "Detection of replaced documents"

    | Fault | SEMQ floor, `within` | SEMQ floor, per-row | Largest absolute difference, calibrated | Lowest row cosine, calibrated |
    | --- | ---: | ---: | ---: | ---: |
    | Replace 1 document | 5.5% | 100% | 100% | 100% |
    | Replace 2 documents | 8.5% | 100% | 100% | 100% |


**The tradeoff of per-row**, with 20 nulls in the floor:

|  | `within` | With per-row |
| --- | ---: | ---: |
| Replace 1 document: detected | 5.5% | 100% |
| Replace 2 documents: detected | 8.5% | 100% |
| Unchanged rebuild: false alarm | 5.5% | 8.1% |

Per-row caught localized changes the p99 hid, at the cost of more false alarms in this synthetic test. These are observed rates, not guarantees.

Source: [`floor-power.json`](../assets/benchmarks/summary/floor-power.json), produced by `python -m benchmarks.floor_power`.

## Which rows changed?

Edit 1% of the corpus (52 documents cut to their first half and embedded again). Distribution drift, the check embedding monitors use, sees nothing; `diff` returns the 52 ids that changed and no others. The two answer different questions: whether the distribution moved, and which documents changed.

| Documents edited | Centroid distance | Domain classifier AUC | SEMQ diff |
| --- | ---: | ---: | ---: |
| 0.1% (5 rows) | 5.1e-09 · no drift | 0.40 · no drift | 5 of 5 identified |
| 1% (52 rows) | 4.0e-07 · no drift | 0.41 · no drift | 52 of 52 identified |
| 5% (259 rows) | 9.8e-06 · no drift | 0.43 · no drift | 258 of 259 identified |
| 10% (518 rows) | 3.9e-05 · no drift | 0.46 · no drift | 516 of 518 identified |
| 50% (2,592 rows) | 9.6e-04 · no drift | 0.71 · **drift** | 2,586 of 2,592 identified |

Drift checks follow Evidently's defaults (centroid distance with threshold 0.2, a domain classifier with ROC AUC threshold 0.55), re-implemented in numpy. With these thresholds, only the domain classifier flagged drift, and only when half the corpus changed. From 5% up a few edited documents encode to the same quantized row as before, so `diff` misses them; no unedited row was reported in these runs.

Source: [`granularity.json`](../assets/benchmarks/summary/granularity.json), produced by `python -m benchmarks.granularity`.

??? note "What these runs do and do not show"

    - One corpus and one model. The floor describes these rebuilds, not another pipeline's.
    - The rebuilds vary the device, the batch size and the input order, and changed at most 2 rows each.
    - The varying-noise pool is synthetic.
    - The previous model revision also changes the manifest, which alone fails the gate. With the manifest unchanged, it still changes 100% of rows.
    - The draws resample one fixed pool. The intervals describe that pool.

[Run the gate yourself](../guides/gate-a-rebuild.md)
