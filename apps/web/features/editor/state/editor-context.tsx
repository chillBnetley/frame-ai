"use client";

import {
  createContext,
  useContext,
  useReducer,
  type Dispatch,
  type ReactNode,
} from "react";

import {
  createInitialEditorState,
  editorReducer,
  type EditorAction,
  type EditorState,
} from "@/features/editor/state/editor-reducer";

interface EditorStore {
  state: EditorState;
  dispatch: Dispatch<EditorAction>;
}

const EditorStoreContext = createContext<EditorStore | null>(null);

interface EditorProviderProps {
  children: ReactNode;
  initialState?: EditorState;
}

export function EditorProvider({ children, initialState }: EditorProviderProps) {
  const [state, dispatch] = useReducer(
    editorReducer,
    initialState ?? createInitialEditorState(),
  );

  return (
    <EditorStoreContext.Provider value={{ state, dispatch }}>
      {children}
    </EditorStoreContext.Provider>
  );
}

export function useEditorStore(): EditorStore {
  const store = useContext(EditorStoreContext);
  if (!store) {
    throw new Error("Editor hooks must be used inside EditorProvider");
  }
  return store;
}

export function useEditorState(): EditorState {
  return useEditorStore().state;
}

export function useEditorDispatch(): Dispatch<EditorAction> {
  return useEditorStore().dispatch;
}
