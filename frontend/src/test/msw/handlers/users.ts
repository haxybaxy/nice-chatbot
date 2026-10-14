import { HttpResponse } from "msw";

import { API_ENDPOINTS } from "@/shared/config/api-endpoints";

import { makeUserProfile } from "../fixtures/user";
import { mockApi } from "../typed-http";

export const usersHandlers = [
  // `/users/me` answers with the wider profile shape (`UserOut`), unlike sign-up — see the
  // fixture docstrings.
  mockApi.get(API_ENDPOINTS.USERS.ME, () => HttpResponse.json(makeUserProfile({ id: "user-1" }))),

  // Echo the patch back on top of the resting profile so a test can assert the refetched
  // value without its own handler.
  mockApi.patch(API_ENDPOINTS.USERS.ME, async ({ request }) => {
    const body = await request.json(); // `UpdateUserIn`, from the spec — no cast
    return HttpResponse.json(makeUserProfile({ id: "user-1", ...body }));
  }),
];
