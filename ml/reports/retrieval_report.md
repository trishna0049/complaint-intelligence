# Retrieval evaluation

Generated 2026-10-05 23:23 UTC by `ml/eval_retrieval.py` · embedding model `sentence-transformers/all-MiniLM-L6-v2` · 30 fixed knowledge-base queries, 8 ticket triples ([ml/retrieval_examples.py](../retrieval_examples.py)).

## Knowledge-base search

| Method | Recall@1 | Recall@3 | MRR |
|---|---|---|---|
| meaning only | 0.90 | 0.97 | 0.93 |
| keywords only | 0.77 | 0.87 | 0.82 |
| hybrid, equal weights, threshold 0.35 | 0.87 | 0.97 | 0.91 |
| hybrid, keyword weight 0.3, threshold 0.35 | 0.90 | 1.00 | 0.94 |
| hybrid (app settings) | 0.93 | 1.00 | 0.96 |

The app uses weighted Reciprocal Rank Fusion (k=60): vectors weigh 1.0, keywords 0.3, and vector matches below 0.2 cosine are dropped for articles. These values were chosen on the examples above (the rows show the alternatives), so treat them as tuned on a small set: with equal weights, generic words such as *order* or *days* pulled unrelated articles up, and a 0.35 cut-off dropped correct articles for short queries (correct articles score from 0.25).

App-settings misses (expected article not in the top 3):

- none

## Similar tickets — paraphrase vs. different problem

The paraphrase is closer than the different problem in **8 of 8** triples.

| Complaint | Cosine to paraphrase | Cosine to other problem |
|---|---|---|
| I was charged twice for my order | 0.64 | 0.41 |
| refund not received even after 10 days | 0.60 | 0.10 |
| pickup for my return was not done | 0.56 | 0.01 |
| the delivery is delayed by a week | 0.65 | 0.12 |
| I received a damaged product | 0.64 | 0.14 |
| OTP is not coming on my phone | 0.40 | 0.12 |
| customer care executive was rude | 0.38 | 0.06 |
| coupon is not working | 0.59 | 0.29 |

Real-data spot checks are recorded in PROGRESS.md (step 7). Similar-ticket results in the app are filtered by the caller's visibility and drop vector matches below `SIMILAR_MIN_SCORE` (0.35) unless keywords also match.
