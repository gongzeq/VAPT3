---
name: hydra-bruteforce
display_name: Hydra Credential Brute-force
version: 1.0.0
risk_level: critical
category: weak_password
external_binary: hydra
network_egress: required
expected_runtime_sec: 900
summary_size_hint: medium
---

Run `hydra` against a single target/service with a bounded username and
password list to enumerate weak credentials. **Critical risk**: this skill
will be gated by `HighRiskGate.guard` — the LLM must have explicit user
authorisation for the target service before calling it.

## Wordlist workflow (secbot/resource/fuzzDicts/)

Dictionary files live under `secbot/resource/fuzzDicts/` but are **never**
auto-loaded. Before calling this skill with `user_dict` / `pass_dict`:

1. List the sub-categories first:
   ```
   ls secbot/resource/fuzzDicts/
   ```
   This reveals category folders such as `passwordDict/`, `userNameDict/`,
   `ServiceWeakPass/`, etc.
2. Drill into the folder that matches the target service
   (e.g. `ls secbot/resource/fuzzDicts/passwordDict/ServiceWeakPass/ssh弱口令/`).
3. Pick exactly ONE filename per slot (`user_dict` / `pass_dict`).
4. Pass those filenames as relative paths under `secbot/resource/fuzzDicts/`
   (e.g. `passwordDict/ServiceWeakPass/ssh弱口令/ssh-user.txt`).

> **Note:** Do NOT use `glob("secbot/resource/fuzzDicts/**/*.txt")` —
> relative-path globs are not resolved correctly by the glob tool.
> Always drill down from the top-level listing.

Inline `users` / `passwords` arrays still take precedence when supplied;
`user_dict` / `pass_dict` only extend them.


Options:
  -R        restore a previous aborted/crashed session
  -I        ignore an existing restore file (don't wait 10 seconds)
  -S        perform an SSL connect
  -s PORT   if the service is on a different default port, define it here
  -l LOGIN or -L FILE  login with LOGIN name, or load several logins from FILE
  -p PASS  or -P FILE  try password PASS, or load several passwords from FILE
  -x MIN:MAX:CHARSET  password bruteforce generation, type "-x -h" to get help
  -y        disable use of symbols in bruteforce, see above
  -r        use a non-random shuffling method for option -x
  -e nsr    try "n" null password, "s" login as pass and/or "r" reversed login
  -u        loop around users, not passwords (effective! implied with -x)
  -C FILE   colon separated "login:pass" format, instead of -L/-P options
  -M FILE   list of servers to attack, one entry per line, ':' to specify port
  -D XofY   Divide wordlist into Y segments and use the Xth segment.
  -o FILE   write found login/password pairs to FILE instead of stdout
  -b FORMAT specify the format for the -o FILE: text(default), json, jsonv1
  -f / -F   exit when a login/pass pair is found (-M: -f per host, -F global)
  -t TASKS  run TASKS number of connects in parallel per target (default: 16)
  -T TASKS  run TASKS connects in parallel overall (for -M, default: 64)
  -w / -W TIME  wait time for a response (32) / between connects per thread (0)
  -c TIME   wait time per login attempt over all threads (enforces -t 1)
  -4 / -6   use IPv4 (default) / IPv6 addresses (put always in [] also in -M)
  -v / -V / -d  verbose mode / show login+pass for each attempt / debug mode 
  -O        use old SSL v2 and v3
  -K        do not redo failed attempts (good for -M mass scanning)
  -q        do not print messages about connection errors
  -U        service module usage details
  -m OPT    options specific for a module, see -U output for information
  -h        more command line options (COMPLETE HELP)
  server    the target: DNS, IP or 192.168.0.0/24 (this OR the -M option)
  service   the service to crack (see below for supported protocols)
  OPT       some service modules support additional input (-U for module help)

Examples:
  hydra -l user -P passlist.txt ftp://192.168.0.1
  hydra -L userlist.txt -p defaultpw imap://192.168.0.1/PLAIN
  hydra -C defaults.txt -6 pop3s://[2001:db8::1]:143/TLS:DIGEST-MD5
  hydra -l admin -p password ftp://[192.168.0.0/24]/
  hydra -L logins.txt -P pws.txt -M targets.txt ssh
