# Excluded context-recall startup samples

These three one-second sampler traces were captured during an initial runner attempt that failed on a Python import before any prompt was submitted. They contain no inference or quality results and must be excluded from performance and recall summaries. The direct-execution import regression is fixed and covered by `tests/test_context_recall.py`.
