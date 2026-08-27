import { callBackendSearch, formatSearchPayload, ok } from "../shared";

export function registerSearchDomain(api: any) {
  api.registerTool({
    name: "ha_search",
    label: "Search",
    description: "Run a backend-powered parallel web search. Actions: search.",
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
      if (action !== "search") return ok(`Unknown ha_search action: ${action}`);
      if (!args.query && !Array.isArray(args.queries)) return ok("search requires query or queries.");
      try {
        const payload = await callBackendSearch({
          query: args.query,
          queries: args.queries,
          max_results: args.max_results,
          include_pages: args.include_pages ?? true,
          lane: args.lane ?? "search",
        });
        return ok(formatSearchPayload(payload));
      } catch (e: any) {
        return ok(`Search failed: ${e.message}`);
      }
    },
  } as any);
}
