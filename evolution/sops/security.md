# SOP: SECURITY_GATE_v1
# TRIGGER: Handing API keys, credentials, or network tools

## 1. MASK
- Never print full API keys in logs.
- Use environment variables via 'os.environ'.

## 2. ENCRYPT
- Store any learned secrets in the Encrypted Vault using the 'learn' tool.

## 3. AUDIT
- Before completing a mission, verify that 'vault.json.enc' is present and not 'vault.json'.
