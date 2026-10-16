# Architecture

Orbit CLI is a presentation and workflow package over `orbit-core`. Core owns lifecycle,
composition, stable plugin contracts, and scriptable operations. Orbit CLI owns the interactive
terminal application, keyboard and mouse navigation, forms, confirmations, and local activity
views. Capability packages own domain operations; provider adapters own vendor behavior.

```text
Orbit application
    └── orbit-core (runtime and stable ControlAction contract)
          ├── capability package (domain behavior)
          │     └── provider adapter (SDK, credentials, transport)
          └── orbit-cli (interactive presentation and operator workflows)
```

The control room only sees actions registered by the application. It does not import arbitrary
installed plugins or infer operations by reflecting over provider APIs. This keeps activation
explicit and makes the user's composed application the authority for available capabilities.

Core command operations remain scriptable for automation. `orbit-cli` aggregates those command
registrations while using its no-command path for the interactive control room. The interactive
layer depends on Core's public APIs and does not reach into private runtime state beyond the
inspection facilities explicitly exported by Core.
