# Cost evaluation

**Goal:** estimate the operating cost of a declared scenario, cost per million
successful queries, and preparation cost per million embeddings.

**Prerequisites:** the developer checkout and environment from the
[benchmark protocol](benchmark-protocol.md), an explicit workload, and tariffs
whose source, date, currency, region and hardware are known. Real comparisons
also require quality, latency, capacity and memory evidence for that workload.

## 1. Choose the economic question

The evaluator runs as a separate workload in the same SDK benchmark suite.
It neither modifies codec adapters nor downloads cloud prices.

- **Monthly scenario cost:** compute + stored data + transfers + billed requests + additional recurring preparation.
- **Monthly cost per million embeddings:** monthly scenario cost divided by corpus count, multiplied by one million.
- **Cost per million successful queries:** the same monthly total divided by successful monthly queries, multiplied by one million.
- **Preparation run cost:** training + encoding + build/persistence compute.
- **Preparation cost per million embeddings:** preparation run cost divided by processed rows, multiplied by one million.

The first three are views of the same allocation, not additive costs. Query cost
includes idle provisioned time and recurring maintenance in the monthly total.
Zero successful queries make the unit cost undefined; the service still incurs
its monthly cost. A normalization does not establish linear scaling to a larger
corpus or different traffic volume.

These metrics describe the components declared in the scenario. They are not a
complete enterprise total-cost-of-ownership model. Embedding generation,
licensing, engineering work, tax and other platform services are excluded.

## 2. Run the arithmetic example

From the repository root:

```sh
python -m benchmarks.costs \
  --scenario benchmarks/configs/cost-illustrative.json \
  --output benchmarks/results/cost-example-001
```

**Expected result:** a new directory containing the resolved `scenario.json` and
`report.json`. The supplied example uses **invented tariffs and quantities**:
its monthly total is USD 781, its cost per million successful queries is
USD 78.10, and its preparation cost is USD 3 for one million embeddings.
These are arithmetic checks, not SEMQ deployment measurements or market prices.
Its requirement check is `not_verified`, because it has no performance evidence.

The CLI refuses to reuse an output directory. It records the input scenario
hash, evaluator source hash, timestamp and, when supplied, benchmark report hash.

## 3. Declare tariffs and quantities

Copy the example configuration and edit its version 1 fields:

- `pricing`: `kind`, provider, region, hardware, currency, date and source; effective unit tariffs.
- `workload`: actual scenario corpus size and successful queries per month.
- `deployment`: serving instances, billed hours per instance, stored bytes per copy, stored copies, aggregate transfers/requests and extra preparation runs.
- `preparation`: rows processed and aggregate billed instance-hours for training, encoding and build/persistence.
- `requirements`: quality metric and minimum value, maximum p99 in milliseconds and maximum error fraction.
- `observations`: corresponding values and their evidence source, for the same configuration and workload.
- `excluded_costs`: explicit list of items outside the cost scope.

Tariffs use currency per instance-hour, per decimal GB-month, per decimal GB
transferred, and per thousand billable requests. One GB is 1,000,000,000 bytes.
Stored copies multiply storage bytes only. Instance count already includes all
serving replicas; transfers and requests are already aggregate quantities.
A billable storage/API request is not necessarily one user search query.

The evaluator accepts decimal strings for prices and uses decimal arithmetic.
Money is emitted as decimal strings without rounding to cents, so small costs
remain visible. Unknown quantities or tariffs remain unavailable; they do not
silently become zero. An explicit zero quantity requires no tariff for that
unused component. A monthly total is unavailable if any included component
cannot be calculated; its known components are still shown.

The current model has one compute tariff. Use it for a homogeneous billed
resource type. Different training/serving hardware, pricing tiers, free tiers,
minimum billing increments, discounts and taxes are not calculated automatically.
Supply effective tariffs and already billable instance-hours, or evaluate the
more complex architecture separately. Do not claim precise billing coverage
from this linear model.

### Avoid double counting

- RAM is included in the instance tariff. There is no additional RAM charge.
- Preparation stage hours are aggregate instance-hours: two machines for three
  billed hours means six instance-hours.
- `additional_preparation_runs_month` counts jobs billed **outside** the serving
  allocation. Set it to zero if preparation shares already provisioned serving
  instances; validate that those instances still satisfy the serving requirements.
- Initial preparation is shown separately. Include it in a particular month's
  recurring-run count only if that month actually contains the additional job.
- A smaller representation only reduces compute spend if it enables a different
  validated deployment. The evaluator never resizes machines based on byte ratios.

## 4. Bind storage to a codec benchmark

An existing quality report can provide corpus count and the actual reported
NPZ artifact file size for one method:

```sh
python -m benchmarks.costs \
  --scenario benchmarks/configs/cost-storage-illustrative.json \
  --report benchmarks/results/quality-faiss-001/report.json \
  --method quant2 \
  --output benchmarks/results/quant2-storage-cost-001
```

The quality run path is the one created in the [benchmark protocol](benchmark-protocol.md).
The command rejects a failed report, unknown method, or conflicting scenario
corpus/byte count. It preserves the source report hash, artifact identity,
scoring profile and whether the dataset was synthetic.

**Expected result:** only the storage component can be calculated from this
example. Overall monthly cost, serving unit cost and preparation remain
`not_evaluated`. The stored object is a **codec NPZ artifact, not a searchable
SEMQ index**. Its size does not establish index RAM, machine count, throughput,
latency or production savings. The storage tariff remains illustrative.

## 5. Interpret evidence and requirements

Economic values have these statuses:

- `illustrative`: the scenario uses fictional tariffs for demonstration/testing.
- `estimated`: declared quoted tariffs were applied to supplied quantities.
- `not_evaluated`: a required input is missing or a denominator is zero.

Invoice-backed observed costs are not implemented. A quoted tariff alone does
not make the resulting deployment estimate an observed cost.

`requirements_check` separately reports `passed`, `failed` or `not_verified` for
quality, p99 and error rate. Observations need a source; absent evidence never
passes. Failed requirements do not hide the arithmetic, but the scenario is not
an equivalent alternative to one that meets the requirements. A passed check
only compares caller-supplied observations with bounds. It does not independently
verify capacity, measurement quality, reliability, or hardware suitability.

Compare the same workload, quality target, latency target, currency, availability
requirements and pricing basis. Do not select the cheapest method across
incompatible scenarios. The evaluator deliberately publishes no automatic
winner, percentage saving, or break-even claim.

## Next steps

- Measure the resources of your own serving path before binding them to a scenario.
- Freeze representative workloads and prices before comparing monthly scenarios.
- Run `python -m pytest benchmarks/tests -q` to check cost arithmetic, missing-data
  handling, requirement gates and benchmark binding alongside codec tests.
