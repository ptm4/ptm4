// Cross-page UI state: command palette visibility, board edit mode (P4).
import { create } from 'zustand';

interface UiState {
  cmdkOpen: boolean;
  setCmdkOpen: (open: boolean) => void;
  editMode: boolean;
  setEditMode: (on: boolean) => void;
}

export const useUi = create<UiState>((set) => ({
  cmdkOpen: false,
  setCmdkOpen: (cmdkOpen) => set({ cmdkOpen }),
  editMode: false,
  setEditMode: (editMode) => set({ editMode }),
}));
