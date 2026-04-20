# Context Strategy Benchmark Results

## Test Files

| File | Description |
|------|-----------|
| `run_benchmark.py` | Basic strategy comparison |
| `run_compaction_benchmark.py` | Compaction trigger tests |
| `run_forced_compaction.py` | Forced low max_tokens |
| `run_quick_eval.py` | Quick validation tests |

## JSON Results

| File | Tests |
|------|-------|
| `topic-id-compaction-benchmark.json` | 5 strategies x 3 lengths |
| `compaction-benchmark.json` | 100x messages |
| `forced-compaction-benchmark.json` | 20/50/100 msgs, max_tokens=500 |
| `eval-results.json` | 5 quick tests |

## Key Findings

### Strategy Behavior (100 messages, forced compaction)

| Strategy | Output Msgs | Behavior |
|----------|-----------|----------|
| sliding_window | 13 | Prunes older messages |
| summary | 13 | Prunes + summarizes |
| compaction | 100 | Keeps all until LLM |
| topic_id | 100 | Keeps all until LLM |

### When topic_id wins:
- Long conversations (>50 messages)
- High entity reuse
- Hallucination prevention critical
- Cache hit/miss visibility

### Quick Tests: 5/5 passed
- ContextStrategy.TOPIC_ID enum ✓
- ID format (topic_8hex) ✓
- Empty content filtering ✓
- Corrupt JSON handling ✓
- Idempotent hashing ✓

## Running Benchmarks

```bash
cd benchmark
python run_benchmark.py        # Basic comparison
python run_quick_eval.py     # Quick tests
python run_forced_compaction.py  # Forced low tokens
```