[Subagent '{{ label }}' {{ status_text }}]

Task: {{ task }}

Result:
{{ result }}

Use this as an orchestration control signal. The result above IS the
complete subagent output — you do NOT need to read any file unless the
result explicitly says `[tool output persisted]` with a saved path.
In that case, use `read_file` on the saved path for the full output.

Decide the next action according to the system routing rules:
- If the subagent was **interrupted** (status includes "interrupted" or
  "not completed"), the task is unfinished. Evaluate the summary:
  - If the remaining work is actionable, re-dispatch a new subagent with
    the summary as context to continue from where it left off.
  - If the blocker is external (e.g. network, permission), report the
    blocker to the user and await instructions.
- If the subagent completed a scan stage, check whether the next stage
  in the pipeline should run. Do NOT skip to the report until ALL
  stages have finished or errored.
- If the subagent failed but the pipeline should continue (e.g. a scan
  stage errored out), proceed to the next stage when dependencies are
  satisfied. Generate a partial report only when the user explicitly asks
  for current results or the remaining work is clearly blocked/skipped.
- If another stage or the final report is still required, call the
  appropriate tool now. Do not stop with only a user-facing summary.
- If no further action is required, summarize this naturally for the
  user in 1-2 sentences. Do not mention technical details like
  "subagent" or task IDs.
