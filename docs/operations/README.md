# Operations

Orbit CLI operates an explicitly selected local application. It is not a remote service manager
and does not bypass authentication or provider permissions. Development server controls supervise
only a child process started by that control room instance. Closing the UI requests graceful
shutdown and enforces a bounded wait before escalation.

Keep credentials in the selected application's secret configuration and provider SDK. Secret
prompt fields are masked, but plugins must still avoid logging submitted values. Do not run the
control room against an untrusted target: importing `module:attribute` executes local code.
