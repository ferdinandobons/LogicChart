import { create } from "zustand";

export type SelectedConnection =
  | { kind: "root-scope"; scope: string }
  | { kind: "scope-entry"; scope: string; target: string }
  | { kind: "flow-call"; source: string; target: string }
  | null;

export interface ViewerState {
  selectedConnection: SelectedConnection;
  setSelectedConnection: (connection: SelectedConnection) => void;
  clearSelection: () => void;
}

export const useViewerStore = create<ViewerState>(set => ({
  selectedConnection: null,
  setSelectedConnection: connection => set({ selectedConnection: connection }),
  clearSelection: () => set({ selectedConnection: null }),
}));
