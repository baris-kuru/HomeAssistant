import { callBackendPython, ok } from "../shared";

export function registerPythonDomain(api: any) {
  api.registerTool({
    name: "ha_python",
    label: "Python",
    description: "Run a short Python script in the assistant sandbox. Actions: run.",
    parameters: {
      type: "object",
      properties: {
        action: { type: "string" },
        args: { type: "object" },
      },
      required: ["action"],
    },
    execute: async (_id: string, params: any) => {
      const action = params.action;
      const args = params.args ?? {};

      if (action !== "run") return ok(`Unknown ha_python action: ${action}`);
      if (!args.user_id || !args.code) return ok("ha_python run requires user_id and code.");

      const payload = await callBackendPython({
        user: args.user_id,
        code: String(args.code),
        stdin: args.stdin ? String(args.stdin) : "",
        timeout_seconds: args.timeout_seconds,
      });
      return ok(JSON.stringify(payload, null, 2));
    },
  } as any);
}
