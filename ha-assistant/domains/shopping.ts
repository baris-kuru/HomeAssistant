import { loadShopping, ok, saveShopping, today } from "../shared";

export function registerShoppingDomain(api: any) {
  api.registerTool({
    name: "ha_shopping",
    label: "Shopping",
    description: "Broker for shopping list actions. Actions: add, list, remove, clear.",
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
      if (!args.user_id) return ok("ha_shopping actions require user_id.");

      if (action === "add") {
        const list = loadShopping(args.user_id);
        const toAdd = args.items ?? (args.item ? [{ item: args.item, qty: args.qty }] : []);
        if (!toAdd.length) return ok("No items provided.");
        for (const entry of toAdd) {
          list.push({ id: Date.now().toString(36) + Math.random().toString(36).slice(2, 5), item: entry.item, qty: entry.qty, added: today(), done: false });
        }
        saveShopping(args.user_id, list);
        return ok(`Added: ${toAdd.map((entry: any) => entry.qty ? `${entry.qty} ${entry.item}` : entry.item).join(", ")}`);
      }

      if (action === "list") {
        const list = loadShopping(args.user_id);
        const filtered = args.show_done ? list : list.filter((item) => !item.done);
        if (!filtered.length) return ok("Shopping list is empty.");
        return ok(filtered.map((item) => `${item.done ? "✓" : "○"} ${item.qty ? `${item.qty} ` : ""}${item.item}`).join("\n"));
      }

      if (action === "remove") {
        if (!args.item) return ok("remove requires item.");
        const list = loadShopping(args.user_id);
        const nameLower = String(args.item).toLowerCase();
        let changed = 0;
        const updated = list.map((item) => {
          if (!item.item.toLowerCase().includes(nameLower)) return item;
          changed++;
          return args.delete ? null : { ...item, done: true };
        }).filter(Boolean) as typeof list;
        if (!changed) return ok(`"${args.item}" not found on the list.`);
        saveShopping(args.user_id, updated);
        return ok(args.delete ? `Removed "${args.item}".` : `Marked "${args.item}" as bought.`);
      }

      if (action === "clear") {
        const list = loadShopping(args.user_id);
        const updated = args.all ? [] : list.filter((item) => !item.done);
        saveShopping(args.user_id, updated);
        return ok(`Cleared ${list.length - updated.length} item(s).`);
      }

      return ok(`Unknown ha_shopping action: ${action}`);
    },
  } as any);
}
