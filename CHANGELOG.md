# Changelog

All notable changes to Orbit CLI are documented here.

## [Unreleased]

### Added

- Initial alpha package with a keyboard and mouse driven local control room, typed plugin action
  forms, masked secret inputs, destructive-action confirmation, Core inspection feeds, and local
  Uvicorn development-server supervision.
- Top-level scriptable Core commands remain available when this package is installed; Core's
  operator action contract stays in `orbit-core` and has no terminal UI dependencies.
