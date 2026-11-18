import { useSyncExternalStore } from "react";
import { getVersion, state, subscribe } from "./engine";

/** Re-renders the calling component whenever the engine changes; returns the live state. */
export function useEngine(): typeof state {
  useSyncExternalStore(subscribe, getVersion);
  return state;
}
