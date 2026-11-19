Name: {{product_name}} default working branch: {{work_branch}}
Trigger: At the start of every session on {{repo_slug}}, and whenever someone asks which branch we are on

The {{product_name}} team works on `{{work_branch}}` in {{repo_slug}}.

- New work branches (`devin/<timestamp>-<slug>`) are cut from `{{work_branch}}`, and pull requests target `{{work_branch}}`.
- A person on the team merges every pull request; Devin never merges.
- The SDLC framework is in `{{sdlc_dir}}/`, the knowledge base in `{{kb_dir}}/`, rules and skills in `.devin/`.
- Jira and Confluence go through the service-account secrets `{{jira_token_env}}` and `{{confluence_token_env}}`, never a personal token.
- Tech lead and roster owner: {{tech_lead_name}} ({{tech_lead_email}}).
