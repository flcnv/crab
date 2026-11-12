"""Eval metrics. Pure functions over labels + predictions.

- observable: line count error, color accuracy, warning tape detection/text match,
  scale reference detection
- per utility type P/R/F1 on `certain` labels (report `likely` separately), confusion matrix
- material accuracy on matched lines
- abstention rate, hallucinated measurements (target 0), calibration buckets, cost/latency
"""
