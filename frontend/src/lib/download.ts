/** Hands a received file to the browser as a download. */
export function saveFile(blob: Blob, fileName: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  document.body.append(link);
  link.click();
  link.remove();
  // The browser has taken the file by now; the delay only covers slow download handlers.
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
}
