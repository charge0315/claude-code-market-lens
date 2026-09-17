// SVG要素をPNG画像としてダウンロードする（🆕 note下書きのチャート書き出し用）。
//
// note.comの画像アップロードはPNG/JPEG等のラスター画像を前提とするため、SVGのまま渡すのではなく
// canvas経由でPNGへ変換してからダウンロードする。ブラウザのCanvas/Image APIに依存するため、
// 未対応環境（テスト環境含む）では例外を投げる（呼び出し側でエラー表示にフォールバックする）。

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error('画像の読み込みに失敗しました'));
    img.src = src;
  });
}

function triggerDownload(dataUrl: string, filename: string): void {
  const a = document.createElement('a');
  a.href = dataUrl;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

export async function downloadSvgAsPng(svg: SVGSVGElement, filename: string): Promise<void> {
  const width = svg.viewBox.baseVal.width || svg.width.baseVal.value;
  const height = svg.viewBox.baseVal.height || svg.height.baseVal.value;
  const serialized = new XMLSerializer().serializeToString(svg);
  const svgBlob = new Blob([serialized], { type: 'image/svg+xml;charset=utf-8' });
  const url = URL.createObjectURL(svgBlob);

  try {
    const image = await loadImage(url);
    const canvas = document.createElement('canvas');
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext('2d');
    if (!ctx) {
      throw new Error('このブラウザでは画像書き出しに対応していません');
    }
    ctx.drawImage(image, 0, 0, width, height);
    triggerDownload(canvas.toDataURL('image/png'), filename);
  } finally {
    URL.revokeObjectURL(url);
  }
}
