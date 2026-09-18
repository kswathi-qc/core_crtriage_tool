# CR Debug Info Review Auth Artifacts

This directory contains the local runtime auth file used by the Orbit Web API
client.

- `orbit_auth.txt`: Orbit service-account auth file in TIP-compatible line
  format.

The expected line format is:

```text
username
realm
password
application-source
optional-impersonated-username
```

Do not print or commit secret contents from this directory. `auth/orbit_auth.txt`
is required unless the caller passes an explicit `authFile` path.
