[Subagent '{{ label }}' {{ status_text }}]

Task: {{ task }}

Result:
{{ result }}

Use this as an orchestration control signal. Decide the next action according
to the system routing rules:
- If the subagent failed but the pipeline should continue (e.g. a scan stage
  errored out), proceed to the next stage or generate the report with whatever
  findings are available. A partial report is always better than no report.
- If another stage or the final report is still required, call the appropriate
  tool now. Do not stop with only a user-facing summary.
- If no further action is required, summarize this naturally for the user in
  1-2 sentences. Do not mention technical details like "subagent" or task IDs.
