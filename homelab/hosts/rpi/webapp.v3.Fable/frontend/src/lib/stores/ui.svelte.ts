// Small cross-component UI state: the command palette, board edit mode, the
// mobile rail. Runes, not stores — read `app.cmdkOpen`, call `app.setCmdk(true)`.

let cmdkOpen = $state(false);
let editMode = $state(false);
let railOpen = $state(false);

export const app = {
  get cmdkOpen() { return cmdkOpen; },
  setCmdk(v: boolean) { cmdkOpen = v; },
  toggleCmdk() { cmdkOpen = !cmdkOpen; },
  get editMode() { return editMode; },
  setEdit(v: boolean) { editMode = v; },
  get railOpen() { return railOpen; },
  setRail(v: boolean) { railOpen = v; },
};
