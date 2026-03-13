import * as vscode from "vscode";

const TERMINAL_NAME = "agent-smith";

export function activate(context: vscode.ExtensionContext) {
  let openNewTerminalDisposable = vscode.commands.registerCommand(
    "agent-smith.openNewTerminal",
    async () => {
      await openTerminal(true);
    }
  );

  let openTerminalDisposable = vscode.commands.registerCommand(
    "agent-smith.openTerminal",
    async () => {
      const existingTerminal = vscode.window.terminals.find(
        (t) => t.name === TERMINAL_NAME
      );
      if (existingTerminal) {
        existingTerminal.show();
        return;
      }
      await openTerminal(false);
    }
  );

  let addFilepathDisposable = vscode.commands.registerCommand(
    "agent-smith.addFilepathToTerminal",
    async () => {
      const fileRef = getActiveFile();
      if (!fileRef) {
        return;
      }

      const terminal = vscode.window.activeTerminal;
      if (!terminal) {
        return;
      }

      if (terminal.name === TERMINAL_NAME) {
        const port = (terminal.creationOptions.env as Record<string, string>)?.["_EXTENSION_AGENT_SMITH_PORT"];
        if (port) {
          await appendPrompt(parseInt(port), fileRef);
        } else {
          terminal.sendText(fileRef, false);
        }
        terminal.show();
      }
    }
  );

  context.subscriptions.push(openTerminalDisposable, addFilepathDisposable);
}

export function deactivate() {}

async function openTerminal(forceNew: boolean) {
  const port = Math.floor(Math.random() * (65535 - 16384 + 1)) + 16384;

  if (forceNew) {
    const existingTerminal = vscode.window.terminals.find(
      (t) => t.name === TERMINAL_NAME
    );
    if (existingTerminal) {
      existingTerminal.kill();
    }
  }

  const terminal = vscode.window.createTerminal({
    name: TERMINAL_NAME,
    location: {
      viewColumn: vscode.ViewColumn.Beside,
      preserveFocus: false,
    },
    env: {
      _EXTENSION_AGENT_SMITH_PORT: port.toString(),
      AGENT_SMITH_CALLER: "vscode",
    },
  });

  terminal.show();
  terminal.sendText(`agent-smith --port ${port}`);

  const fileRef = getActiveFile();
  if (!fileRef) {
    return;
  }

  let tries = 10;
  let connected = false;
  do {
    await new Promise((resolve) => setTimeout(resolve, 200));
    try {
      await fetch(`http://localhost:${port}/app`);
      connected = true;
      break;
    } catch (e) {}

    tries--;
  } while (tries > 0);

  if (connected) {
    await appendPrompt(port, `In ${fileRef}`);
    terminal.show();
  }
}

async function appendPrompt(port: number, text: string) {
  try {
    await fetch(`http://localhost:${port}/tui/append-prompt`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ text }),
    });
  } catch (e) {
    console.error("Failed to append prompt:", e);
  }
}

function getActiveFile(): string | undefined {
  const activeEditor = vscode.window.activeTextEditor;
  if (!activeEditor) {
    return;
  }

  const document = activeEditor.document;
  const workspaceFolder = vscode.workspace.getWorkspaceFolder(document.uri);
  if (!workspaceFolder) {
    return;
  }

  const relativePath = vscode.workspace.asRelativePath(document.uri);
  let filepathWithAt = `@${relativePath}`;

  const selection = activeEditor.selection;
  if (!selection.isEmpty) {
    const startLine = selection.start.line + 1;
    const endLine = selection.end.line + 1;

    if (startLine === endLine) {
      filepathWithAt += `#L${startLine}`;
    } else {
      filepathWithAt += `#L${startLine}-${endLine}`;
    }
  }

  return filepathWithAt;
}
