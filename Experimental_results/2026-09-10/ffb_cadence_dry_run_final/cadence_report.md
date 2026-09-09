# Collision FFB cadence dry-run summary

| cadence | active commands | coverage | p95 latency [ms] | stop latency [ms] | decision |
|---|---:|---:|---:|---:|---|
| continuous | 15 | 1.000 | 1.700 | 0.917 | PASS |
| double | 8 | 1.000 | 1.224 | 0.796 | PASS |
| triple | 9 | 1.000 | 2.477 | 1.129 | PASS |

総合判定: **PASS**

この比較はROS dry-runの通信・停止特性を示す。
G923上の体感差は実機試験で別途評価する。
