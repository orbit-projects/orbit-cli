# Interactive control room

Run `orbit` with no arguments. Select a local application target such as
`examples.minimal.app:runtime`, then use arrow keys and Enter or click menu items. The target
imports trusted local Python code. It describes the selected local process, not a remote worker.

The control room provides Core overview and validation, services and route inspection, plugin
inventory, redacted configuration, task and event metadata, a health/diagnostics activity feed,
and local Uvicorn development-server controls. Enabled plugin actions appear in the same menu.
Actions may declare text, integer, boolean, secret, and choice inputs. Secret fields are masked;
Core does not echo them. An action that changes or deletes state must set `destructive=True`, which
causes a second confirmation screen with Cancel focused by default.

## Plugin contributions

Plugins expose a tuple of `orbit.plugins.ControlAction` values as `control_actions`. Each action
has a bounded identifier, title, description, async handler, optional input declarations, and
destructive flag. Handlers receive a detached mapping of validated primitive input values and
return an optional bounded `ControlResult`. The contract has no Textual or Rich dependency.

Handlers must keep provider work bounded, close resources they own, and avoid secret values in
logs, errors, and returned summaries. Errors are reported by safe exception type; raw provider
messages and tracebacks are not displayed. The UI invokes only actions on enabled plugins
registered by the selected application.

For example, a provider plugin can contribute a read-only connectivity check without adding a
dependency on the terminal UI:

```python
from collections.abc import Mapping

from orbit.plugins import ControlAction, ControlResult, Plugin


class SearchPlugin(Plugin):
    control_actions = ()

    def __init__(self, client) -> None:
        self._client = client

        async def check_connection(_: Mapping[str, object]) -> ControlResult:
            await self._client.ping()
            return ControlResult("Search provider is reachable")

        self.control_actions = (
            ControlAction(
                id="check-connection",
                title="Check search connection",
                description="Send a read-only health request to the configured provider.",
                handler=check_connection,
            ),
        )
```

Actions should be short, read-only by default, and close any temporary resources they create. If
an action changes external state, declare its inputs and set `destructive=True` so the control
room asks for confirmation. Keep authorization checks in the provider operation itself.

## Scriptable operations

Named Core commands remain available at the top level for scripts and automation:

```bash
orbit --help
orbit check examples.minimal.app:application
orbit diagnostics-watch examples.minimal.app:application --interval 5
```

Use an explicit target. Inspection and health commands do not contact a remote deployment.
Remote privileged operations require an authenticated API owned by the relevant capability.
