import { authHandlers } from "./auth";
import { usersHandlers } from "./users";

export const defaultHandlers = [...authHandlers, ...usersHandlers];
