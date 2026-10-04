# Stage 2.5 RAG Evaluation

> Baseline comparison only. It does not establish semantic answer correctness or faithfulness.

## Run Metadata

- run_timestamp_utc: `2026-10-04T15:10:25.146042+00:00`
- dataset_sha256: `85117f3403f1079f2ef95952ddf1a40bacae03f34f747a3b530ab5a6224ccb05`
- corpus_manifest_sha256: `b093b13c2812dbfeccbe8b89caecead69b0e3649b0dfcad40717bcf641a20206`
- code_revision: `c7f58863f8b013be4d5624c3190fa6040032e94c`
- worktree_dirty: `true`
- evaluator_sha256: `7e0edd54fc4ed9897976f4cb6f8d1fad8d4408c5d8ee348278f3b9d23f10644a`
- python_version: `3.14.4`
- httpx_version: `0.28.1`
- pydantic_version: `2.13.5`
- pyyaml_version: `6.0.3`
- pypdf_version: `6.19.0`
- tiktoken_version: `0.14.0`
- models_observed: `gpt-oss-20b`
- embedding_model_config: `unavailable_not_exposed_by_api`
- reranker_model_config: `unavailable_not_exposed_by_api`
- dataset_case_count: `35`
- requests_per_mode: `35`
- timeout_seconds: `60.0`
- api_origin: `http://127.0.0.1:8000`
- api_base_path_sha256: `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`
- Retrieval modes: `dense`, `hybrid`, `hybrid_rerank`
- `top_k`: 5 for every request; equal-weight RRF retained
- Each case/mode attempted once; mode order rotates deterministically; no HTTP retries
- Token usage: unavailable from the public response; not added to the API for this evaluation

## Aggregate Results

| Mode | Recall@5 | MRR | Citation precision (n) | No citations | Citation mapping errors | Answerability accuracy | Client latency median/p95 ms | Service latency median/p95 ms | Failures |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| dense | 0.966 (n=29) | 0.931 (n=29) | 76.1% (n=46) | 6 | 0 | 100.0% (n=35) | 7936/12696 | 7910/12668 | 0/35 (0.0%) |
| hybrid | 0.983 (n=29) | 0.948 (n=29) | 79.5% (n=44) | 6 | 0 | 100.0% (n=35) | 8313/10711 | 8257/10677 | 0/35 (0.0%) |
| hybrid_rerank | 1.000 (n=29) | 0.948 (n=29) | 78.7% (n=47) | 6 | 0 | 100.0% (n=35) | 7476/10646 | 7450/10618 | 0/35 (0.0%) |

Retrieval metrics use answerable cases only. Citation precision is pooled across returned citations; zero-citation responses are counted separately and are not assigned an artificial precision.
Answerability accuracy uses successful HTTP responses only. Request failures remain in the failure-rate denominator.
Client latency includes all attempts; service latency is available only for successful responses.

## Per-Case Results

| Case | Mode | Result | Gold answerable | Status | Recall@5 | MRR | Citation precision | Answerability correct | Client ms | Service ms | Trace |
|---|---|---|---|---|---:|---:|---:|---|---:|---:|---|
| home-flood-extension-cover | dense | ok | true | answered | 1.000 | 0.500 | 50.0% | true | 1495 | 1420 | 52ae540f074978c04df533f44bedbd8c |
| home-flood-extension-cover | hybrid | ok | true | answered | 1.000 | 0.500 | 50.0% | true | 1127 | 1104 | 899a60df9b7102d45174e8d01b049dfd |
| home-flood-extension-cover | hybrid_rerank | ok | true | answered | 1.000 | 0.500 | 50.0% | true | 3072 | 3047 | 2ff0e155f497b5a10979570e7458bb9d |
| home-surface-water-definition | hybrid | ok | true | answered | 1.000 | 1.000 | 100.0% | true | 1532 | 1499 | 5cc95a040e1a0fed888ecac60f17e743 |
| home-surface-water-definition | hybrid_rerank | ok | true | answered | 1.000 | 1.000 | 100.0% | true | 2978 | 2952 | 46174f8de52b1e6d5700c77b4abd565d |
| home-surface-water-definition | dense | ok | true | answered | 1.000 | 1.000 | 50.0% | true | 1017 | 989 | fb78781d9757dcd89e34c05139c561b6 |
| home-base-flood-exclusion | hybrid_rerank | ok | true | answered | 1.000 | 0.500 | 100.0% | true | 2971 | 2937 | 7376d313247f89a881699df61b56c99b |
| home-base-flood-exclusion | dense | ok | true | answered | 1.000 | 0.500 | 100.0% | true | 5224 | 5193 | 05688c9369bf48bea2184aafdc0b1ab9 |
| home-base-flood-exclusion | hybrid | ok | true | answered | 1.000 | 0.500 | 100.0% | true | 9716 | 9685 | 00fde6f010426a651c3f9d72a46100a5 |
| home-ground-floor-contents | dense | ok | true | answered | 1.000 | 1.000 | 50.0% | true | 8920 | 8884 | bd5d7d5f78abf7093850fbe1e40030c2 |
| home-ground-floor-contents | hybrid | ok | true | answered | 1.000 | 1.000 | 50.0% | true | 8909 | 8873 | ee54955e926e3a9520534a315ec5fadb |
| home-ground-floor-contents | hybrid_rerank | ok | true | answered | 1.000 | 1.000 | 50.0% | true | 8232 | 8197 | b954c5e23022ba178af1e79c28e28309 |
| home-cellar-contents | hybrid | ok | true | answered | 1.000 | 1.000 | 100.0% | true | 8766 | 8738 | 94b2b4c12592bb7d313d2e67ff9a4875 |
| home-cellar-contents | hybrid_rerank | ok | true | answered | 1.000 | 1.000 | 100.0% | true | 8396 | 8362 | a95c8e83087959de5e88157c2fdea2b7 |
| home-cellar-contents | dense | ok | true | answered | 1.000 | 1.000 | 100.0% | true | 7876 | 7840 | f360343977ae98b3ce0fb7530541933f |
| home-sudden-escape-cover | hybrid_rerank | ok | true | answered | 1.000 | 1.000 | 100.0% | true | 9329 | 9296 | cac81858ac374a5c4f667ac1a1c7cd75 |
| home-sudden-escape-cover | dense | ok | true | answered | 1.000 | 1.000 | 100.0% | true | 8486 | 8461 | 64b78f5c7a408635cf4aabc27d82c957 |
| home-sudden-escape-cover | hybrid | ok | true | answered | 1.000 | 1.000 | 100.0% | true | 6359 | 6333 | 2e1f8e4492ea24dac45bad8dad605990 |
| home-failed-pipe-repair-cost | dense | ok | true | answered | 1.000 | 1.000 | 50.0% | true | 9319 | 9293 | db58d8e03136eb80f289822e630056a3 |
| home-failed-pipe-repair-cost | hybrid | ok | true | answered | 1.000 | 1.000 | 50.0% | true | 7579 | 7554 | 37e84655b489fd39e294479cb9f8c5fd |
| home-failed-pipe-repair-cost | hybrid_rerank | ok | true | answered | 1.000 | 1.000 | 50.0% | true | 9214 | 9184 | 825ddc60359ad8a2f16415d28e7b8cbc |
| home-gradual-leak-before-clarification | hybrid | ok | true | answered | 1.000 | 1.000 | 50.0% | true | 8593 | 8568 | 045089038886b19a717278b1bc08ba3b |
| home-gradual-leak-before-clarification | hybrid_rerank | ok | true | answered | 1.000 | 1.000 | 50.0% | true | 9021 | 8996 | 228f998b668fd3116a779a8f16f76ced |
| home-gradual-leak-before-clarification | dense | ok | true | answered | 1.000 | 1.000 | 50.0% | true | 8807 | 8782 | 9fdf7b03b22cb16a81cb8f900fc3aa12 |
| home-gradual-leak-clarification-effective | hybrid_rerank | ok | true | answered | 1.000 | 1.000 | 100.0% | true | 9424 | 9398 | 00e252ea869b00c0649a185fb58f28a1 |
| home-gradual-leak-clarification-effective | dense | ok | true | answered | 1.000 | 1.000 | 100.0% | true | 8805 | 8771 | f16e31621571206b0af81c4d012e6ed8 |
| home-gradual-leak-clarification-effective | hybrid | ok | true | answered | 1.000 | 1.000 | 100.0% | true | 8477 | 8450 | 305c2f42170ff1587f89213c5d17910e |
| home-discovery-date-is-not-start-date | dense | ok | true | answered | 1.000 | 1.000 | 100.0% | true | 9117 | 9085 | 4c4fb692e6b5e31b707f51a1c79a7b20 |
| home-discovery-date-is-not-start-date | hybrid | ok | true | answered | 1.000 | 1.000 | 100.0% | true | 8216 | 8186 | 646829e044a2e7ff6fb1ff709b083d0b |
| home-discovery-date-is-not-start-date | hybrid_rerank | ok | true | answered | 1.000 | 1.000 | 66.7% | true | 10646 | 10618 | 6e53a16ba090290663d67fe543db41d7 |
| home-water-tracing-costs | hybrid | ok | true | answered | 1.000 | 1.000 | 100.0% | true | 8886 | 8855 | b72be991f3b3ef09ce22bef21c4fe8b3 |
| home-water-tracing-costs | hybrid_rerank | ok | true | answered | 1.000 | 1.000 | 100.0% | true | 7800 | 7768 | 5b4d26e88c426b19e9fcb80b2f2b4bea |
| home-water-tracing-costs | dense | ok | true | answered | 1.000 | 1.000 | 100.0% | true | 8140 | 8114 | e408ce4e7f7c182abeb9f2018f6e93d1 |
| home-water-evidence-request | hybrid_rerank | ok | true | answered | 1.000 | 1.000 | 66.7% | true | 8963 | 8767 | 187068b7b2293f7c36c0e1ea0c2492b3 |
| home-water-evidence-request | dense | ok | true | answered | 1.000 | 1.000 | 50.0% | true | 13989 | 13963 | f542c7f802725c4845ff514b15c4e813 |
| home-water-evidence-request | hybrid | ok | true | answered | 1.000 | 1.000 | 50.0% | true | 8844 | 8818 | ce0f14f3f256d9353c697fb64f547042 |
| home-water-chronology | dense | ok | true | answered | 0.500 | 1.000 | 33.3% | true | 12696 | 12668 | e8c0e00f04798a3f0b891e2a3358d56a |
| home-water-chronology | hybrid | ok | true | answered | 1.000 | 1.000 | 50.0% | true | 9424 | 9391 | f53c80722ef715b3fcaf27ed8e60c69d |
| home-water-chronology | hybrid_rerank | ok | true | answered | 1.000 | 1.000 | 40.0% | true | 9933 | 9901 | a7c23ca0ed14b42185a701b2caa2e591 |
| home-ambiguous-cause-escalation | hybrid | ok | true | answered | 0.500 | 1.000 | 100.0% | true | 11675 | 11640 | ff53c9e2e3acece456d0a9aae6f9b2fc |
| home-ambiguous-cause-escalation | hybrid_rerank | ok | true | answered | 1.000 | 1.000 | 100.0% | true | 8187 | 8157 | bb966e4f587d53d0137b19ad445bd008 |
| home-ambiguous-cause-escalation | dense | ok | true | answered | 0.500 | 1.000 | 100.0% | true | 8400 | 8374 | a328368fdea6cf671aa2f2451df58da6 |
| home-claim-evidence-availability | hybrid_rerank | ok | true | answered | 1.000 | 1.000 | 100.0% | true | 6934 | 6908 | 75b95e7b0c20ffb7b97d2151b6b559c4 |
| home-claim-evidence-availability | dense | ok | true | answered | 1.000 | 0.500 | 100.0% | true | 9449 | 9424 | 702e2e1ae68599d649caa147d6eb2c20 |
| home-claim-evidence-availability | hybrid | ok | true | answered | 1.000 | 1.000 | 100.0% | true | 7283 | 7256 | e8dad0c6e5f82a8074d212bf60ff0219 |
| motor-comprehensive-accidental-damage | dense | ok | true | answered | 1.000 | 1.000 | 100.0% | true | 7880 | 7852 | d36936dd152d3ee2894bbf5cb068f9ae |
| motor-comprehensive-accidental-damage | hybrid | ok | true | answered | 1.000 | 1.000 | 100.0% | true | 6649 | 6621 | 68fc3f0acaa028f37601c7d13b928c01 |
| motor-comprehensive-accidental-damage | hybrid_rerank | ok | true | answered | 1.000 | 1.000 | 100.0% | true | 8276 | 8248 | fb0cbb3235786c11c63504e90ad6534d |
| motor-flood-damage | hybrid | ok | true | answered | 1.000 | 1.000 | 50.0% | true | 8313 | 8257 | a0a12578700b4d473fee25572901790a |
| motor-flood-damage | hybrid_rerank | ok | true | answered | 1.000 | 1.000 | 100.0% | true | 6687 | 6622 | 684666399a8dbb6bc5cd5120c558c9dd |
| motor-flood-damage | dense | ok | true | answered | 1.000 | 1.000 | 50.0% | true | 6931 | 6881 | a4a1e1c9186728e8b4476897bfaf5eb3 |
| motor-engine-start-after-flood | hybrid_rerank | ok | true | answered | 1.000 | 1.000 | 100.0% | true | 8520 | 8489 | 65e7294e04b52fb813d22fb18d37eafe |
| motor-engine-start-after-flood | dense | ok | true | answered | 1.000 | 1.000 | 100.0% | true | 6634 | 6598 | dd2d8e54e4010fa798ec7f6954269a19 |
| motor-engine-start-after-flood | hybrid | ok | true | answered | 1.000 | 1.000 | 100.0% | true | 7271 | 7236 | e11e55e66225885dbc380b7cfb533409 |
| motor-theft | dense | ok | true | answered | 1.000 | 1.000 | 100.0% | true | 7363 | 7337 | 5e6ea79f55e5240149ac8e24d2aac724 |
| motor-theft | hybrid | ok | true | answered | 1.000 | 1.000 | 100.0% | true | 7215 | 7189 | 6c4dec951c4c3fdf8f003c4ab6d257cf |
| motor-theft | hybrid_rerank | ok | true | answered | 1.000 | 1.000 | 100.0% | true | 7441 | 7416 | 1db65ede1d0fc0db6447a56191d21344 |
| motor-settlement-options | hybrid | ok | true | answered | 1.000 | 1.000 | 100.0% | true | 8703 | 8677 | c1ce37efe9598b7c940a2e0c4eab2449 |
| motor-settlement-options | hybrid_rerank | ok | true | answered | 1.000 | 1.000 | 100.0% | true | 7476 | 7450 | a7a05fc56588260b6d99416ae446951f |
| motor-settlement-options | dense | ok | true | answered | 1.000 | 1.000 | 100.0% | true | 6039 | 6013 | 34560b66e447faa3922adacef533b898 |
| motor-repair-before-inspection | hybrid_rerank | ok | true | answered | 1.000 | 1.000 | 100.0% | true | 8502 | 8352 | c7bcaf474f37b21df657779b2698bd76 |
| motor-repair-before-inspection | dense | ok | true | answered | 1.000 | 1.000 | 100.0% | true | 8405 | 8377 | 79a4700ad51c48122b3140073e6d85c3 |
| motor-repair-before-inspection | hybrid | ok | true | answered | 1.000 | 1.000 | 100.0% | true | 7183 | 7157 | 8114d1cf932c43119ec0109548a384a8 |
| motor-uninsured-mechanical-failure | dense | ok | true | answered | 1.000 | 1.000 | 100.0% | true | 6195 | 6163 | adf8175b2e4cfddd0cdf91cae46ca8f9 |
| motor-uninsured-mechanical-failure | hybrid | ok | true | answered | 1.000 | 1.000 | 100.0% | true | 7396 | 7370 | 16ca1ec306af1affff5dafbe787bb529 |
| motor-uninsured-mechanical-failure | hybrid_rerank | ok | true | answered | 1.000 | 1.000 | 100.0% | true | 7388 | 7362 | a8e250e2777790eab6f51150bc30570c |
| commercial-scheduled-property | hybrid | ok | true | answered | 1.000 | 0.500 | 100.0% | true | 8898 | 8863 | cde8d50ef9f15b75b2dc5f622af97f6b |
| commercial-scheduled-property | hybrid_rerank | ok | true | answered | 1.000 | 0.500 | 100.0% | true | 7065 | 7028 | d62747c151234e71dd1f484a21b50cd5 |
| commercial-scheduled-property | dense | ok | true | answered | 1.000 | 0.500 | 100.0% | true | 7936 | 7910 | b9d743e5c5031d68df1bca10f52bb319 |
| commercial-deliberate-damage | hybrid_rerank | ok | true | answered | 1.000 | 1.000 | 100.0% | true | 7239 | 7204 | 82568a564201b255768f06f4c237c6dc |
| commercial-deliberate-damage | dense | ok | true | answered | 1.000 | 1.000 | 100.0% | true | 7353 | 7321 | 102dfe5c9a68098399890527b9de317c |
| commercial-deliberate-damage | hybrid | ok | true | answered | 1.000 | 1.000 | 100.0% | true | 6247 | 6213 | 8cc15af9ead937fe4b8b1c1bc628f2bf |
| commercial-escape-of-water | dense | ok | true | answered | 1.000 | 1.000 | 100.0% | true | 8089 | 8062 | 6c62a8c198e70929fce9c03b8a9bf457 |
| commercial-escape-of-water | hybrid | ok | true | answered | 1.000 | 1.000 | 100.0% | true | 6655 | 6626 | 4ab4db1bb8480731aa86b89f4abffcbc |
| commercial-escape-of-water | hybrid_rerank | ok | true | answered | 1.000 | 1.000 | 100.0% | true | 7473 | 7445 | 00725b071e2d788ac65cd097d4290ca3 |
| commercial-flood-extension | hybrid | ok | true | answered | 1.000 | 1.000 | 100.0% | true | 7176 | 7149 | 1f73c537a75ed99d011e5ccc84f62b67 |
| commercial-flood-extension | hybrid_rerank | ok | true | answered | 1.000 | 1.000 | 100.0% | true | 7572 | 7539 | 1197e87b7de0a8f10f8abfdab02da59b |
| commercial-flood-extension | dense | ok | true | answered | 1.000 | 1.000 | 100.0% | true | 8203 | 8171 | 9f7ebb350593f9bbe127090dcc961433 |
| commercial-records-and-mitigation | hybrid_rerank | ok | true | answered | 1.000 | 1.000 | 100.0% | true | 5214 | 5178 | 7cf6f634a306974c043cce813c43cd15 |
| commercial-records-and-mitigation | dense | ok | true | answered | 1.000 | 1.000 | 100.0% | true | 9425 | 9394 | 5603e4ffd11191e5f48df6b070dc36ed |
| commercial-records-and-mitigation | hybrid | ok | true | answered | 1.000 | 1.000 | 100.0% | true | 8805 | 8772 | f96a8bbd48170e7891b87329245ae6c1 |
| fair-handling-unresolved-evidence | dense | ok | true | answered | 1.000 | 1.000 | 100.0% | true | 10162 | 10133 | 771e52d3ebd762dad802a8b59502b860 |
| fair-handling-unresolved-evidence | hybrid | ok | true | answered | 1.000 | 1.000 | 100.0% | true | 9470 | 9444 | 35a4b53dc9a70cafedda61b5c99efac8 |
| fair-handling-unresolved-evidence | hybrid_rerank | ok | true | answered | 1.000 | 1.000 | 100.0% | true | 4823 | 4797 | 6b6b6ffd5f0b578c18aba2711bacd36f |
| fair-guidance-on-progress | hybrid | ok | true | answered | 1.000 | 1.000 | 66.7% | true | 10257 | 10229 | a433467a1055185c180400c88d781128 |
| fair-guidance-on-progress | hybrid_rerank | ok | true | answered | 1.000 | 1.000 | 66.7% | true | 8291 | 8256 | 0b849acf47a87c7158bf739978a1dbcc |
| fair-guidance-on-progress | dense | ok | true | answered | 1.000 | 1.000 | 66.7% | true | 6962 | 6935 | 6100539875caf0c8f30bcf8b4a13dd25 |
| home-unspecified-flood-limit | hybrid_rerank | ok | false | insufficient_evidence | n/a | n/a | n/a | true | 11808 | 11782 | 0bb07337a7d40b03ff5207cd64b3d007 |
| home-unspecified-flood-limit | dense | ok | false | insufficient_evidence | n/a | n/a | n/a | true | 5531 | 5500 | d3616fce49cc4a97e3c0b83a0bd5d5c1 |
| home-unspecified-flood-limit | hybrid | ok | false | insufficient_evidence | n/a | n/a | n/a | true | 9060 | 9031 | f237d168a082289598a8213dc67d6d3e |
| home-unspecified-accommodation-cover | dense | ok | false | insufficient_evidence | n/a | n/a | n/a | true | 7132 | 7099 | c33185d7a2710249888dc4cf194e5358 |
| home-unspecified-accommodation-cover | hybrid | ok | false | insufficient_evidence | n/a | n/a | n/a | true | 10711 | 10677 | 073386be35c5867c4553120bc078b734 |
| home-unspecified-accommodation-cover | hybrid_rerank | ok | false | insufficient_evidence | n/a | n/a | n/a | true | 7075 | 7040 | e0730ebae7fae7bfeea86bef25353ff8 |
| home-scheduled-excess-amount | hybrid | ok | false | insufficient_evidence | n/a | n/a | n/a | true | 9612 | 9578 | 315de1a48893fcbdd715abd2b4f33cb7 |
| home-scheduled-excess-amount | hybrid_rerank | ok | false | insufficient_evidence | n/a | n/a | n/a | true | 4817 | 4792 | f9538ac29ef6d2d7a46376acc30c8de4 |
| home-scheduled-excess-amount | dense | ok | false | insufficient_evidence | n/a | n/a | n/a | true | 11148 | 11122 | 8e65a3ac6750a4498bdda1a57d5a60ce |
| motor-hire-car-cover | hybrid_rerank | ok | false | insufficient_evidence | n/a | n/a | n/a | true | 7178 | 7152 | 2ff5a6fd9f0ed3fc9a5a968f532111fd |
| motor-hire-car-cover | dense | ok | false | insufficient_evidence | n/a | n/a | n/a | true | 7680 | 7654 | 0f013c404e4f66fb8b8dd4bdca83cb26 |
| motor-hire-car-cover | hybrid | ok | false | insufficient_evidence | n/a | n/a | n/a | true | 6270 | 6237 | e927b7f17922cc7c26446bf6efd59aaa |
| commercial-business-interruption | dense | ok | false | insufficient_evidence | n/a | n/a | n/a | true | 7656 | 7612 | 0650ff32f9d9183ccee08fb02878e308 |
| commercial-business-interruption | hybrid | ok | false | insufficient_evidence | n/a | n/a | n/a | true | 6653 | 6478 | 9920a6839e7977ca0de8cb8b04b6e647 |
| commercial-business-interruption | hybrid_rerank | ok | false | insufficient_evidence | n/a | n/a | n/a | true | 7170 | 7139 | 2cb62b16153f1414306f44160b658ca3 |
| commercial-unspecified-flood-limit | hybrid | ok | false | insufficient_evidence | n/a | n/a | n/a | true | 7617 | 7591 | afd7d3ff57e139b5bf3e6085052093ba |
| commercial-unspecified-flood-limit | hybrid_rerank | ok | false | insufficient_evidence | n/a | n/a | n/a | true | 4455 | 4429 | c0c67497559d08123906e74f0eecce7e |
| commercial-unspecified-flood-limit | dense | ok | false | insufficient_evidence | n/a | n/a | n/a | true | 7602 | 7568 | 2e61cc79fb18370a2fcdd172cd37d538 |

## Failure Categories

- `dense` failures: none; citation mapping errors=0; responses without citations=6
- `hybrid` failures: none; citation mapping errors=0; responses without citations=6
- `hybrid_rerank` failures: none; citation mapping errors=0; responses without citations=6
