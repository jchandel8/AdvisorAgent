/** Saving a file the API returned (the browser can't use a plain link: the sign-in token must be sent). */

/** The filename from a Content-Disposition header, or the fallback. */
export function filenameFrom(disposition: string | null, fallback: string): string {
  const match = /filename="?([^";]+)"?/i.exec(disposition ?? '');
  const name = match?.[1]?.trim();
  // Never trust a path from the server: keep only the last part.
  return name ? (name.split(/[\\/]/).pop() ?? fallback) : fallback;
}

/** Hands a downloaded file to the browser's save flow. */
export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
