export function cropRectangle(sourceWidth: number, sourceHeight: number, width: number, height: number,
  zoom: number, horizontal: number, vertical: number) {
  if (![sourceWidth, sourceHeight, width, height, zoom].every(value => Number.isFinite(value) && value > 0) ||
    ![horizontal, vertical].every(value => Number.isFinite(value) && value >= 0 && value <= 100) || zoom < 1) {
    throw new Error("Choose valid image dimensions and crop positions.");
  }
  const ratio = width / height;
  const cropWidth = Math.min(sourceWidth, sourceHeight * ratio) / zoom;
  const cropHeight = cropWidth / ratio;
  return { x: (sourceWidth - cropWidth) * horizontal / 100, y: (sourceHeight - cropHeight) * vertical / 100,
    width: cropWidth, height: cropHeight };
}
