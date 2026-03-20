# Agent Smith VS Code Extension

A Visual Studio Code extension that integrates [Agent Smith](https://github.com/daedalus/nanocode) directly into your development workflow.

## Prerequisites

This extension requires the [Agent Smith CLI](https://github.com/daedalus/nanocode) to be installed on your system.

## Features

- **Quick Launch**: Use `Cmd+Esc` (Mac) or `Ctrl+Esc` (Windows/Linux) to open Agent Smith in a split terminal view, or focus an existing terminal session if one is already running.
- **New Session**: Use `Cmd+Shift+Esc` (Mac) or `Ctrl+Shift+Esc` (Windows/Linux) to start a new Agent Smith terminal session, even if one is already open.
- **Context Awareness**: Automatically share your current selection or tab with Agent Smith.
- **File Reference Shortcuts**: Use `Cmd+Option+K` (Mac) or `Alt+Ctrl+K` (Linux/Windows) to insert file references. For example, `@File#L37-42`.

## Installation

1. Clone the repository
2. Navigate to `sdks/vscode`
3. Run `npm install`
4. Run `npm run compile`
5. Press `F5` to start debugging

## Development

1. `code sdks/vscode` - Open the `sdks/vscode` directory in VS Code. **Do not open from repo root.**
2. `npm install` - Run inside the `sdks/vscode` directory.
3. Press `F5` to start debugging - This launches a new VS Code window with the extension loaded.

#### Making Changes

`tsc` watchers run automatically during debugging. Changes to the extension are automatically rebuilt.

To test your changes:
1. In the debug VS Code window, press `Cmd+Shift+P`
2. Search for `Developer: Reload Window`
3. Reload to see your changes without restarting the debug session
