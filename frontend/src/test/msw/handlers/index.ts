import { attachmentHandlers } from "./attachments";
import { authHandlers } from "./auth";
import { chatHandlers } from "./chat";
import { teamsHandlers } from "./teams";
import { usersHandlers } from "./users";

export const defaultHandlers = [
  ...authHandlers,
  ...usersHandlers,
  ...teamsHandlers,
  ...chatHandlers,
  ...attachmentHandlers,
];
