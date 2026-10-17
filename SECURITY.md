# Security

voice-doctor only reads your agent config and call data; its Bolna script makes GET requests and never prints your API key.

If you find a security problem (for example a way the scripts could leak a key or call data), please report it privately through [GitHub's private vulnerability reporting](https://github.com/dakshinsiva/voice-doctor/security/advisories/new) rather than a public issue.

Never paste API keys, call recordings or customer details into issues or pull requests. If you did by mistake, rotate the key (platform.bolna.ai → Developers → API Keys) and let us know so we can delete the content.
