import { useEffect, useId, useRef, useState } from "react";
import { X } from "lucide-react";
import { cropRectangle } from "../features/imageCrop";
import { toAssetUrl } from "../features/catalog/utils";

export function ImageCropEditor({ source, label, width = 1000, height = 1000, presets = [], onApply, onClose }: {
  source: string; label: string; width?: number; height?: number;
  presets?: Array<{ label: string; width: number; height: number }>;
  onApply: (image: string) => void; onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const previewClip = useId();
  const image = useRef<HTMLImageElement | null>(null);
  const drag = useRef<{ x: number; y: number; horizontal: number; vertical: number; scale: number;
    availableWidth: number; availableHeight: number } | null>(null);
  const [dimensions, setDimensions] = useState<{ width: number; height: number }>();
  const [outputWidth, setOutputWidth] = useState(width);
  const [outputHeight, setOutputHeight] = useState(height);
  const [zoom, setZoom] = useState(1);
  const [horizontal, setHorizontal] = useState(50);
  const [vertical, setVertical] = useState(50);
  const [error, setError] = useState("");
  useEffect(() => {
    dialog.current?.showModal();
    image.current = null;
    setDimensions(undefined);
    setError("");
    let active = true;
    const photo = new Image();
    photo.crossOrigin = "anonymous";
    photo.onload = () => {
      if (!active) return;
      image.current = photo;
      setDimensions({ width: photo.naturalWidth, height: photo.naturalHeight });
      if (validSize(photo.naturalWidth, photo.naturalHeight)) {
        setOutputWidth(photo.naturalWidth);
        setOutputHeight(photo.naturalHeight);
      }
    };
    photo.onerror = () => { if (active) setError("This image cannot be opened for cropping. For an external URL, upload the original file instead."); };
    photo.src = toAssetUrl(source);
    return () => { active = false; };
  }, [source]);
  const valid = validSize(outputWidth, outputHeight);
  const crop = dimensions && valid ? cropRectangle(dimensions.width, dimensions.height, outputWidth, outputHeight,
    zoom, horizontal, vertical) : undefined;
  const chooseSize = (nextWidth: number, nextHeight: number) => {
    setOutputWidth(nextWidth); setOutputHeight(nextHeight);
    setZoom(1); setHorizontal(50); setVertical(50); setError("");
  };
  const apply = () => {
    if (!image.current || !crop) return;
    try {
      const canvas = document.createElement("canvas");
      canvas.width = outputWidth; canvas.height = outputHeight;
      const context = canvas.getContext("2d");
      if (!context) throw new Error("Your browser cannot create the crop.");
      context.drawImage(image.current, crop.x, crop.y, crop.width, crop.height, 0, 0, outputWidth, outputHeight);
      const result = canvas.toDataURL("image/png");
      if ((result.length - result.indexOf(",") - 1) * 3 / 4 > 1024 * 1024) {
        throw new Error("The cropped PNG is over 1 MiB. Reduce the output pixels and try again.");
      }
      onApply(result);
      onClose();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Unable to crop this image.");
    }
  };
  return <dialog ref={dialog} className="image-crop-dialog" aria-label={`Crop ${label}`} onCancel={event => {
    event.preventDefault(); onClose();
  }} onClick={event => { if (event.target === event.currentTarget) onClose(); }}>
    <header className="image-crop-header">
      <div><h2>Crop {label}</h2><p>Drag the green frame to move it. Your image will not be stretched.</p></div>
      <button type="button" className="image-crop-close" aria-label="Close crop editor" onClick={onClose}><X size={20} /></button>
    </header>
    <div className="image-crop-content">
      {error ? <p role="alert" className="ops-error">{error}</p> : null}
      {dimensions ? <p className="image-crop-original-size">Current image: {dimensions.width} x {dimensions.height} px. Recommended: {width} x {height} px.</p> : !error ? <p role="status">Opening image...</p> : null}
      <div className="image-crop-presets" aria-label="Image size options">
        <button type="button" disabled={!dimensions} onClick={() => chooseSize(width, height)}>Recommended {width} x {height}</button>
        {presets.map(preset => <button key={preset.label} type="button" disabled={!dimensions} onClick={() => chooseSize(preset.width, preset.height)}>
          {preset.label} {preset.width} x {preset.height}</button>)}
        <button type="button" disabled={!dimensions || !validSize(dimensions.width, dimensions.height)}
          onClick={() => { if (dimensions) chooseSize(dimensions.width, dimensions.height); }}>Keep current size</button>
      </div>
      {crop && dimensions ? <div className="image-crop-previews">
        <figure><figcaption>1. Choose the area</figcaption>
          <svg className="image-crop-source" role="img" aria-label="Original with crop selection"
            viewBox={`0 0 ${dimensions.width} ${dimensions.height}`}
            onPointerDown={event => {
              if (event.button !== 0) return;
              const bounds = event.currentTarget.getBoundingClientRect();
              drag.current = { x: event.clientX, y: event.clientY, horizontal, vertical,
                scale: Math.min(bounds.width / dimensions.width, bounds.height / dimensions.height),
                availableWidth: dimensions.width - crop.width, availableHeight: dimensions.height - crop.height };
              event.currentTarget.setPointerCapture(event.pointerId);
            }}
            onPointerMove={event => {
              const start = drag.current;
              if (!start) return;
              if (start.availableWidth > 0) setHorizontal(Math.max(0, Math.min(100,
                start.horizontal + (event.clientX - start.x) / start.scale / start.availableWidth * 100)));
              if (start.availableHeight > 0) setVertical(Math.max(0, Math.min(100,
                start.vertical + (event.clientY - start.y) / start.scale / start.availableHeight * 100)));
            }}
            onPointerUp={() => { drag.current = null; }} onPointerCancel={() => { drag.current = null; }}
            onLostPointerCapture={() => { drag.current = null; }}>
            <image href={toAssetUrl(source)} width={dimensions.width} height={dimensions.height} />
            <rect x={crop.x} y={crop.y} width={crop.width} height={crop.height} fill="#147d7814"
              stroke="#147d78" strokeWidth={3} vectorEffect="non-scaling-stroke" />
          </svg>
        </figure>
        <figure><figcaption>2. Check the result</figcaption>
          <svg role="img" aria-label="Cropped card preview" viewBox={`${crop.x} ${crop.y} ${crop.width} ${crop.height}`}>
          <defs><clipPath id={previewClip}><rect x={crop.x} y={crop.y} width={crop.width} height={crop.height} /></clipPath></defs>
          <image href={toAssetUrl(source)} width={dimensions.width} height={dimensions.height} clipPath={`url(#${previewClip})`} />
        </svg><p className="image-crop-output-size">Output: {outputWidth} x {outputHeight} px</p></figure>
      </div> : null}
      <div className="image-crop-fields">
        <label>Output width (px)<input type="number" min={32} max={4096} value={outputWidth}
          onChange={event => setOutputWidth(Number(event.target.value))} /></label>
        <label>Output height (px)<input type="number" min={32} max={4096} value={outputHeight}
          onChange={event => setOutputHeight(Number(event.target.value))} /></label>
      </div>
      <details className="image-crop-position">
        <summary>Zoom &amp; position</summary>
        <div className="image-crop-fields">
        <label>Zoom ({zoom.toFixed(2)}x)<input aria-label="Zoom" type="range" min={1} max={4} step={0.05} value={zoom} onChange={event => setZoom(Number(event.target.value))} /></label>
        <label>Horizontal position<input type="range" min={0} max={100} value={horizontal} onChange={event => setHorizontal(Number(event.target.value))} /></label>
        <label>Vertical position<input type="range" min={0} max={100} value={vertical} onChange={event => setVertical(Number(event.target.value))} /></label>
        </div>
      </details>
      {!valid ? <p role="alert">Use 32–4096 whole pixels per side, at most 16 million pixels total.</p> : null}
      <p className="image-crop-help">This updates your draft only. Save to publish. Larger pixels cannot add missing detail.</p>
    </div>
    <footer className="image-crop-actions"><button type="button" className="btn light" onClick={onClose}>Cancel</button>
      <button type="button" className="btn" disabled={!crop} onClick={apply}>Apply crop</button></footer>
  </dialog>;
}

function validSize(width: number, height: number) {
  return Number.isInteger(width) && Number.isInteger(height) && width >= 32 && height >= 32 &&
    width <= 4096 && height <= 4096 && width * height <= 16_000_000;
}
