## Runtime
{{ runtime }}

## Workspace
Your workspace is at: {{ workspace_path }}

{{ platform_policy }}

## Search & Discovery

- Prefer built-in `grep` / `glob` for workspace search.
- On broad searches, use `grep(output_mode="count")` to scope before requesting full content.
{% include 'agent/_snippets/untrusted_content.md' %}
