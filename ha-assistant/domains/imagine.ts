import { canonicalUserId, FIREWORKS_API_KEY, getTelegramChatId, ok, TELEGRAM_BOT_TOKEN_EXPORT } from "../shared";

const FLUX_MODELS: Record<string, string> = {
  schnell: "accounts/fireworks/models/flux-1-schnell-fp8",
  dev:     "accounts/fireworks/models/flux-1-dev-fp8",
  kontext: "accounts/fireworks/models/flux-kontext-pro",
};

async function generateFluxImage(prompt: string, quality: "schnell" | "dev" | "kontext" = "dev"): Promise<Buffer> {
  if (!FIREWORKS_API_KEY) {
    throw new Error("FIREWORKS_API_KEY is not configured");
  }
  const modelId = FLUX_MODELS[quality];
  const body: Record<string, any> = { prompt };

  // Fireworks' current serverless FLUX API is exposed as a workflow endpoint.
  // Keep the request conservative to avoid vendor-side 500s from unsupported knobs.
  if (quality === "schnell") {
    body.aspect_ratio = "1:1";
  }

  const res = await fetch(
    `https://api.fireworks.ai/inference/v1/workflows/${modelId}/text_to_image`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Accept": "image/png",
        "Authorization": `Bearer ${FIREWORKS_API_KEY}`,
      },
      body: JSON.stringify(body),
    }
  );
  if (!res.ok) throw new Error(`Fireworks image gen error: ${res.status} ${await res.text()}`);
  const imageData = Buffer.from(await res.arrayBuffer());
  if (!imageData.length) throw new Error("Fireworks returned an empty image response");
  return imageData;
}

async function sendTelegramPhoto(chatId: string, imageBuffer: Buffer, caption?: string): Promise<void> {
  if (!TELEGRAM_BOT_TOKEN_EXPORT) {
    throw new Error("TELEGRAM_BOT_TOKEN is not configured");
  }
  const form = new FormData();
  form.append("chat_id", chatId);
  form.append("photo", new Blob([imageBuffer], { type: "image/png" }), "image.png");
  if (caption) form.append("caption", caption);
  const response = await fetch(`https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN_EXPORT}/sendPhoto`, {
    method: "POST",
    body: form,
  });
  if (!response.ok) {
    throw new Error(`Telegram sendPhoto failed: ${response.status} ${await response.text()}`);
  }
}

export function registerImagineDomain(api: any) {
  api.registerTool({
    name: "ha_imagine",
    label: "Imagine",
    description: "Generate an image from a text prompt using FLUX AI. Actions: generate.",
    parameters: {
      type: "object",
      properties: {
        action: { type: "string" },
        args: {
          type: "object",
          properties: {
            user_id: { type: "string", description: "User ID" },
            prompt: { type: "string", description: "Detailed description of the image to generate" },
            quality: {
              type: "string",
              enum: ["schnell", "dev", "kontext"],
              description: "schnell=fast & cheap, dev=better quality, kontext=best (paid per image)",
            },
          },
        },
      },
      required: ["action"],
    },
    execute: async (_id: string, params: any) => {
      try {
        const action = String(params?.action ?? "").trim().toLowerCase();
        const directPrompt = typeof params?.prompt === "string" ? params.prompt : "";
        const directQuality = typeof params?.quality === "string" ? params.quality : undefined;
        const directUserId = typeof params?.user_id === "string" ? params.user_id : undefined;
        const args = params?.args ?? {};

        if (action && action !== "generate") {
          return ok(`Unknown ha_imagine action: ${action}`);
        }

        const prompt = String(args.prompt ?? directPrompt ?? "").trim();
        const quality = String(args.quality ?? directQuality ?? "dev").trim().toLowerCase() as "schnell" | "dev" | "kontext";
        const userId = String(args.user_id ?? directUserId ?? "baris").trim() || "baris";

        if (!prompt) {
          return ok("generate requires a prompt.");
        }

        const uid = canonicalUserId(userId);
        const chatId = getTelegramChatId(uid) ?? userId;
        const imageBuffer = await generateFluxImage(prompt, quality);
        await sendTelegramPhoto(chatId, imageBuffer, prompt.slice(0, 200));
        return ok(`Image sent (${quality} quality, 1024×1024)`);
      } catch (err: any) {
        return ok(`Image generation failed: ${err?.message ?? err}`);
      }
    },
  } as any);
}
