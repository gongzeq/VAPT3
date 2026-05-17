---
name: katana-crawl-web
display_name: Katana web crawl
version: 1.0.0
risk_level: medium
category: crawl_web
external_binary: katana
binary_min_version: "1.0.0"
network_egress: required
expected_runtime_sec: 600
summary_size_hint: medium
---

Run ProjectDiscovery Katana against an authorized HTTP/HTTPS target and return
a bounded list of URLs that deserve later vulnerability scanning.

The default invocation is equivalent to:

`katana -u <target> -d 5 -jc -ef css,png,jpg,gif,svg,woff,ttf,js -aff -o <scan_dir>/katana/katana_urls.txt`

The skill deduplicates Katana's URL file, drops static/noisy endpoints, and
classifies query parameters, JSON/XML indicators, upload/download/fetch/export
paths, and admin/login-like paths into structured candidate hypotheses.
