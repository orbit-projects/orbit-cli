# Orbit CLI

<div align="center">

Interactive, keyboard and mouse driven control room for Orbit applications.

[![CI](https://github.com/orbit-projects/orbit-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/orbit-projects/orbit-cli/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

</div>

`orbit-cli` is the operator interface for the Orbit ecosystem. Developers write application and
plugin code as usual, then use `orbit` to inspect and operate the local application through
menus, keyboard navigation, mouse clicks, typed prompts, and bounded activity feeds. Core and
enabled plugins own the operations; this package owns the terminal experience.

```bash
python -m pip install -e ../orbit-core -e .
orbit
```

This workspace install uses the sibling Core checkout. After both distributions are published,
install `orbit-cli` from the configured package index instead.

The control room loads an explicit local `module:attribute` target. It can inspect Core
composition, configuration, routes, services, tasks, events, health, diagnostics, and registered
plugin operations. Sensitive inputs use masked fields. Destructive plugin actions require an
additional confirmation. Core's scriptable operations remain available as `orbit check`,
`orbit inspect`, `orbit health`, and related commands.

Plugin packages add domain behavior by exposing validated `ControlAction` values from their
registered Core plugin. Core owns that stable, UI-neutral contract; plugins own provider SDKs,
credentials, transport, and operation semantics. The CLI never discovers or activates arbitrary
installed packages while opening a project.

This package is alpha. See the [documentation index](docs/README.md), [contribution guide](CONTRIBUTING.md),
and [security policy](SECURITY.md) before contributing.

Licensed under Apache-2.0.
