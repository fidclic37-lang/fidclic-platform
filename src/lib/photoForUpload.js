// A photo made light enough to send (2026-10-15): an iPhone photo is 3–5 MB,
// over Vercel's 4.5 MB request body once in base64. Where the browser can
// read it, it is brought down to 1600 px and sent as JPEG; where it cannot
// (a .HEIC in Chrome), it goes as it is and the server converts it
// (api/services/vision_image.py).
const MAX_SIDE = 1600;

const asDataUrl = (blob) => new Promise((resolve, reject) => {
  const r = new FileReader(); r.onload = () => resolve(r.result); r.onerror = reject; r.readAsDataURL(blob);
});

export async function photoForUpload(file) {
  try {
    const bmp = await createImageBitmap(file, { imageOrientation: 'from-image' });
    const k = Math.min(1, MAX_SIDE / Math.max(bmp.width, bmp.height));
    const canvas = document.createElement('canvas');
    canvas.width = Math.round(bmp.width * k);
    canvas.height = Math.round(bmp.height * k);
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#fff';                      // a transparent PNG: on white
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(bmp, 0, 0, canvas.width, canvas.height);
    bmp.close?.();
    return { dataUrl: canvas.toDataURL('image/jpeg', 0.85), mime: 'image/jpeg' };
  } catch (_e) {
    return { dataUrl: await asDataUrl(file), mime: file.type || 'image/heic' };
  }
}
