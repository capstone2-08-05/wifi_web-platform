import { create } from 'zustand';

export type EditorTool =
  | 'select'
  | 'upload'
  | 'rect'      // 벽/구조물 (LineString — 2 클릭)
  | 'circle'    // 가구 (Point — 1 클릭)
  | 'polygon'   // 방 (Polygon — 다중 클릭 + 시작점 클릭으로 닫기)
  | 'opening';  // 문/창 (LineString — 2 클릭)

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
