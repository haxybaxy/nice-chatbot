import { useQuery } from "@tanstack/react-query";

import { QUERY_KEYS } from "@/shared/constants/query-keys";

import { chatService } from "../services/chat.service";

/** The model picker's entries (`GET /api/chat/models`). Settings-driven on the backend: never stale. */
export function useChatModels() {
  return useQuery({
    queryKey: QUERY_KEYS.chat.models,
    queryFn: () => chatService.listModels(),
    staleTime: Infinity,
  });
}
