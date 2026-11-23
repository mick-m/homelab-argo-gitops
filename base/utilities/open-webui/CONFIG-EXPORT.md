# config-export.json

Reference copy of prod Open WebUI's settings (Admin Panel > Settings > Database >
Export Config), exported 2026-11-23. Not mounted or applied: the live settings
live in Open WebUI's database (PersistentConfig), which overrides the env vars in
deployment.yaml.

Secrets are replaced with "REDACTED - enter by hand in Admin > Settings": the LM
Studio token (connection 1) and the Splash token (connection 2) in
`openai.api_keys`, and `web.loader.firecrawl_api_key`.

Restore on a fresh install: Admin Panel > Settings > Database > Import Config,
then re-enter those secrets under Connections and Web Search.

Not covered: users, chats, and per-model settings (system prompts, advanced
params), which live in other tables. Re-export after significant changes.
