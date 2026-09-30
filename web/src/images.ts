// Client-side checks that mirror the API's image rules (design.md §5),
// so obvious problems are caught before uploading.

export const MAX_IMAGES = 4;
export const MAX_IMAGE_BYTES = 5 * 1024 * 1024;
export const ACCEPTED_TYPES = ["image/jpeg", "image/png", "image/gif", "image/webp"];

/** Returns an error message, or null if the file is acceptable. */
export function checkImage(file: { name: string; type: string; size: number }): string | null {
  if (!ACCEPTED_TYPES.includes(file.type)) return `${file.name}: only JPEG, PNG, GIF, or WebP images.`;
  if (file.size > MAX_IMAGE_BYTES) return `${file.name}: larger than 5 MB.`;
  return null;
}

export function readAsDataUrl(file: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}
