// Markierungsfenster (overlay.html): empfängt nur die geprüfte, umgerechnete Markierung des Lichtrahmens aus main.js
// (oder null zum Leeren), sonst nichts.
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("overlay", {
  onMarkierung: (callback) => ipcRenderer.on("markierung", (_event, markierung) => callback(markierung)),
});
