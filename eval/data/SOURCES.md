# Eval data: sources and licences

| data | source | authors | licence | how it is used |
|------|--------|---------|---------|----------------|
| OpenTrench3D point clouds (21 of 310, seeded subset) | [Kaggle `hestogpony/opentrench3d`](https://www.kaggle.com/datasets/hestogpony/opentrench3d), [GitHub](https://github.com/SimonBuusJensen/OpenTrench3D), [paper](https://arxiv.org/abs/2404.07711) | Hansen, Jensen, Philipsen et al. (CVPR 2024 Workshops) | [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/) | downloaded to `~/datasets/opentrench3d` (not in git); rendered to `eval/data/opentrench3d/` (git-ignored); truth from the per-point classes and the area's utility type |

Regenerate: `uv run python -m eval.opentrench download && uv run python -m eval.opentrench render`.
