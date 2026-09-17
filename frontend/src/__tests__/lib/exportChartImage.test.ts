import { downloadSvgAsPng } from '@/lib/exportChartImage';

// jsdom は画像の実デコードを行わないため、Image をテスト用の同期フェイクへ差し替える。
class FakeImage {
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  set src(_value: string) {
    queueMicrotask(() => this.onload?.());
  }
}

function createSvg(): SVGSVGElement {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg') as SVGSVGElement;
  svg.setAttribute('viewBox', '0 0 560 220');
  svg.setAttribute('width', '560');
  svg.setAttribute('height', '220');
  document.body.appendChild(svg);
  return svg;
}

describe('downloadSvgAsPng', () => {
  let originalImage: typeof Image;
  let originalGetContext: typeof HTMLCanvasElement.prototype.getContext;
  let originalToDataURL: typeof HTMLCanvasElement.prototype.toDataURL;
  let clickSpy: jest.SpyInstance;
  let toDataURLMock: jest.Mock;

  beforeEach(() => {
    originalImage = global.Image;
    originalGetContext = HTMLCanvasElement.prototype.getContext;
    originalToDataURL = HTMLCanvasElement.prototype.toDataURL;

    (global as unknown as { Image: unknown }).Image = FakeImage;
    toDataURLMock = jest.fn().mockReturnValue('data:image/png;base64,FAKE');
    HTMLCanvasElement.prototype.getContext = jest
      .fn()
      .mockReturnValue({ drawImage: jest.fn() }) as unknown as typeof HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.toDataURL = toDataURLMock;

    global.URL.createObjectURL = jest.fn().mockReturnValue('blob:fake');
    global.URL.revokeObjectURL = jest.fn();

    clickSpy = jest.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
  });

  afterEach(() => {
    global.Image = originalImage;
    HTMLCanvasElement.prototype.getContext = originalGetContext;
    HTMLCanvasElement.prototype.toDataURL = originalToDataURL;
    jest.restoreAllMocks();
  });

  it('SVGをPNGへ変換し、ダウンロードリンクをクリックする', async () => {
    const svg = createSvg();

    await downloadSvgAsPng(svg, 'test_chart.png');

    expect(toDataURLMock).toHaveBeenCalledWith('image/png');
    expect(clickSpy).toHaveBeenCalled();
    expect(global.URL.revokeObjectURL).toHaveBeenCalledWith('blob:fake');
  });

  it('canvas未対応環境ではエラーを投げる（呼び出し側でエラー表示にフォールバック）', async () => {
    HTMLCanvasElement.prototype.getContext = jest.fn().mockReturnValue(null);
    const svg = createSvg();

    await expect(downloadSvgAsPng(svg, 'test_chart.png')).rejects.toThrow();
  });
});
