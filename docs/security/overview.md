# Security model

The CLI is a local operator interface. Loading a project executes trusted code in the current
user's process. The CLI is not a sandbox, remote control protocol, or privilege boundary.

Plugin actions are exposed only by plugins explicitly registered and enabled by the application.
Action identifiers and presentation text are bounded; terminal markup is not interpreted. Input
values are typed and secret fields are masked. Core suppresses raw exception text. Plugin authors
must redact provider logs and summaries, enforce authorization at the operation boundary, and
label state-changing actions destructive so the UI requires confirmation.

The UI does not store credentials. Provider packages own credential loading and refresh. Use the
application's normal secret provider and follow least-privilege practices for cloud accounts.
