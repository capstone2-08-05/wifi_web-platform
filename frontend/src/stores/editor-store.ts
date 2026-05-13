import { create } from 'zustand';

export type EditorTool = 'select' | 'upload' | 'rect' | 'circle' | 'text';

interface EditorActions {
  onLoadFloorplan?: () => void;
  onSaveFloorplan?: () => void;
}

interface EditorState {
  tool: EditorTool;
  setTool: (tool: EditorTool) => void;
  actions: EditorActions;
  registerActions: (actions: EditorActions) => void;
  clearActions: () => void;
}

export const useEditorStore = create<EditorState>((set) => ({
  tool: 'select',
  setTool: (tool) => set({ tool }),
  actions: {},
  registerActions: (actions) => set({ actions }),
  clearActions: () => set({ actions: {} }),
}));
