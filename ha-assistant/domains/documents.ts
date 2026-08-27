import { basename } from "path";

import { ok } from "../shared";

export function registerDocumentDomain(api: any) {
  api.registerTool({
    name: "ha_documents",
    label: "Documents",
    description: "Broker for document actions. Actions: read_document.",
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
      if (action !== "read_document") return ok(`Unknown ha_documents action: ${action}`);

      const DOCLING_URL = "http://127.0.0.1:8183/convert";
      let buffer: Buffer;
      let filename = args.filename ?? "document";

      if (args.path) {
        const { existsSync, readFileSync } = await import("fs");
        if (!existsSync(args.path)) return ok(`File not found: ${args.path}`);
        buffer = readFileSync(args.path);
        filename = args.filename ?? basename(args.path);
      } else if (args.url) {
        const res = await fetch(args.url);
        if (!res.ok) return ok(`Failed to download: ${res.status} ${res.statusText}`);
        buffer = Buffer.from(await res.arrayBuffer());
        filename = args.filename ?? (String(args.url).split("/").pop() ?? "document");
      } else {
        return ok("read_document requires path or url.");
      }

      try {
        const form = new FormData();
        form.set("file", new Blob([buffer]), filename);
        const res = await fetch(DOCLING_URL, { method: "POST", body: form as any });
        if (!res.ok) return ok(`Docling error: ${res.status} — ${await res.text()}`);
        const data = await res.json() as { markdown: string; chars: number };
        if (!data.markdown?.trim()) return ok("Document converted but appears to be empty.");
        return ok(`**${filename}** (${data.chars} chars)\n\n${data.markdown}`);
      } catch (e: any) {
        if (e.cause?.code === "ECONNREFUSED") return ok("Docling service is not running.");
        return ok(`Conversion failed: ${e.message}`);
      }
    },
  } as any);
}
