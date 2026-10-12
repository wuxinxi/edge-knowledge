import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('edgeDesktop', {
  folders: {
    list: (library: string) => ipcRenderer.invoke('folders:list', library),
    choose: (library: string) => ipcRenderer.invoke('folders:choose', library),
    sync: (id: string) => ipcRenderer.invoke('folders:sync', id),
    pause: (id: string) => ipcRenderer.invoke('folders:pause', id),
    resume: (id: string) => ipcRenderer.invoke('folders:resume', id),
    disconnect: (id: string) => ipcRenderer.invoke('folders:disconnect', id),
  },
  access: {
    list: () => ipcRenderer.invoke('access:list'),
    choose: (kind: 'file' | 'directory') => ipcRenderer.invoke('access:choose', kind),
    revoke: (id: string) => ipcRenderer.invoke('access:revoke', id),
    scan: (id: string) => ipcRenderer.invoke('access:scan', id),
    importFiles: (id: string, files: string[], library: string) =>
      ipcRenderer.invoke('access:import', id, files, library),
  },
  getBackendSession: () => ipcRenderer.invoke('backend:session'),
})
