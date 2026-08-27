import { canonicalUserId, ok, resolveUser, updatePassword, verifyPassword } from "../shared";

export function registerIdentityDomain(api: any) {
  api.registerTool({
    name: "ha_identity",
    label: "Identity",
    description: "Broker for identity actions. Actions: switch_user, change_password.",
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

      if (action === "switch_user") {
        if (!args.username || !args.password) return ok("switch_user requires username and password.");
        const canonical = canonicalUserId(String(args.username));
        if (!verifyPassword(canonical, args.password)) return ok("Wrong password or password not set.");
        const user = resolveUser(canonical);
        return ok(`Switched to ${user.name ?? canonical}.`);
      }

      if (action === "change_password") {
        if (!args.user_id || !args.current_password || !args.new_password) return ok("change_password requires user_id, current_password, and new_password.");
        if (!verifyPassword(args.user_id, args.current_password)) return ok("Current password is wrong.");
        updatePassword(args.user_id, args.new_password);
        return ok("Password changed.");
      }

      return ok(`Unknown ha_identity action: ${action}`);
    },
  } as any);
}
