import { execFile } from "child_process";
import { promisify } from "util";
import { existsSync } from "fs";
import { join } from "path";

import { DATA_DIR, ok } from "../shared";

const execFileAsync = promisify(execFile);

function pythonBinary(): string {
  const venvPython = join(DATA_DIR, ".venv", "bin", "python");
  return existsSync(venvPython) ? venvPython : "python3";
}

async function runGmailCli(args: string[]) {
  const scriptPath = join(DATA_DIR, "scripts", "gmail_cli.py");
  const { stdout, stderr } = await execFileAsync(pythonBinary(), [scriptPath, ...args], {
    cwd: DATA_DIR,
    timeout: 120_000,
    maxBuffer: 1024 * 1024,
  });

  if (stderr?.trim()) {
    const parsed = safeJson(stdout);
    if (!parsed) throw new Error(stderr.trim());
  }

  const parsed = safeJson(stdout);
  if (!parsed) throw new Error(stdout.trim() || "gmail_cli returned invalid JSON");
  if (!parsed.ok) throw new Error(parsed.error || "gmail_cli failed");
  return parsed.result;
}

function safeJson(text: string) {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

export function registerGmailDomain(api: any) {
  api.registerTool({
    name: "ha_gmail",
    label: "Gmail",
    description: "Read-only Gmail inbox access for Baris. Actions: status, recent. Use to summarize important emails, triage inbox, and search recent mail. This tool must not send, delete, or modify mail.",
    parameters: {
      type: "object",
      properties: {
        action: { type: "string" },
        args: { type: "object" },
      },
      required: ["action"],
    },
    execute: async (_id: string, params: any) => {
      const action = String(params.action || "");
      const args = params.args ?? {};

      if (action === "status") {
        const result = await runGmailCli(["status"]);
        const lines = [
          `Client credentials present: ${result.client_secret_present ? "yes" : "no"}`,
          `Authorized token present: ${result.token_present ? "yes" : "no"}`,
          `Authorized for read-only use: ${result.authorized ? "yes" : "no"}`,
          `Token valid: ${result.token_valid ? "yes" : "no"}`,
          `Scopes: ${(result.scopes || []).join(", ")}`,
        ];
        if (result.token_error) lines.push(`Token error: ${result.token_error}`);
        return ok(lines.join("\n"));
      }

      if (action === "recent") {
        const result = await runGmailCli([
          "recent",
          "--max-results",
          String(args.max_results ?? 10),
          "--query",
          String(args.query ?? "in:inbox newer_than:14d"),
        ]);

        if (!result.messages?.length) {
          return ok(`No messages found for query: ${result.query}`);
        }

        const lines = result.messages.map((message: any) => {
          const from = message.from || "Unknown sender";
          const subject = message.subject || "(No subject)";
          const date = message.date || "";
          const snippet = message.snippet || "";
          return `- ${date} | ${from} | ${subject}${snippet ? `\n  ${snippet}` : ""}`;
        });
        return ok(lines.join("\n"));
      }

      return ok(`Unknown ha_gmail action: ${action}`);
    },
  } as any);
}
