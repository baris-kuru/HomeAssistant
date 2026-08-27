import { registerCalendarDomain } from "./domains/calendar";
import { registerDocumentDomain } from "./domains/documents";
import { registerHealthDomain } from "./domains/health";
import { registerGmailDomain } from "./domains/gmail";
import { registerHooks } from "./domains/hooks";
import { registerImagineDomain } from "./domains/imagine";
import { registerIdentityDomain } from "./domains/identity";
import { registerNotesRemindersDomain } from "./domains/notes-reminders";
import { registerProfileMemoryDomain } from "./domains/profile-memory";
import { registerPythonDomain } from "./domains/python";
import { registerSearchDomain } from "./domains/search";
import { registerShoppingDomain } from "./domains/shopping";
import { registerWellbeingDomain } from "./domains/wellbeing";
import { ensureKnownUserScaffolds, localWhisperProvider } from "./shared";

const haAssistantPlugin = {
  id: "ha-assistant",
  name: "Home Assistant",
  description: "Personal assistant: memory, health, habits, journal, dreams, people, calendar, shopping, food diary",

  register(api: any) {
    api.registerMediaUnderstandingProvider(localWhisperProvider);
    ensureKnownUserScaffolds();

    registerProfileMemoryDomain(api);
    registerNotesRemindersDomain(api);
    registerShoppingDomain(api);
    registerHealthDomain(api);
    registerWellbeingDomain(api);
    registerCalendarDomain(api);
    registerDocumentDomain(api);
    registerIdentityDomain(api);
    registerPythonDomain(api);
    registerSearchDomain(api);
    registerGmailDomain(api);
    registerImagineDomain(api);
    registerHooks(api);
  },
};

export default haAssistantPlugin;
