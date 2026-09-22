import numpy as np
from PIL import Image, ImageDraw


def generate_cover(output_path="docs/note/images/00_cover.png"):
    # 1. 元の cover 画像
    base = Image.open("docs/note/images/00_cover.png").convert("RGBA")
    W, H = base.size  # 2560, 1340

    # 2. 背景グリッド
    # トークン準拠: 背景色 #f5ead8, グリッド色 #ecdec9, ピッチ 80px, 線幅 2px
    bg_color = (245, 234, 216, 255)
    grid_color = (236, 222, 201, 255)
    clean_canvas = Image.new("RGBA", (W, H), bg_color)
    draw_canvas = ImageDraw.Draw(clean_canvas)

    for x in range(0, W, 80):
        draw_canvas.line([(x, 0), (x, H)], fill=grid_color, width=2)
    for y in range(0, H, 80):
        draw_canvas.line([(0, y), (W, y)], fill=grid_color, width=2)

    # 3. 左側のオリジナル画像（x < 1300）をマスク合成
    # タイポグラフィ・タグ等のオリジナル高品位デザインを100%保持
    left_mask = Image.new("L", (W, H), 0)
    draw_mask = ImageDraw.Draw(left_mask)
    draw_mask.rectangle([(0, 0), (1300, H)], fill=255)
    for i, x in enumerate(range(1300, 1340)):
        alpha = int(255 * (1 - i / 40.0))
        draw_mask.line([(x, 0), (x, H)], fill=alpha)

    canvas = Image.composite(base, clean_canvas, left_mask)

    # 4. 新しいダッシュボード画面からメインコンテンツを切り出し
    dash = Image.open("docs/screenshots/dashboard.png").convert("RGBA")
    # サイドバー境界 x=220、上部「● ザラ場中」の上マージンから
    y_start = 56
    # 9999 デモ商事カード全体 + 8888 サンプル工業のヘッダーが自然に収まる位置
    y_end = 848
    main_content = dash.crop((220, y_start, 1440, y_end))

    # カードサイズ（高解像度スケール）
    target_card_w = 1650
    scale = target_card_w / main_content.width
    target_card_h = int(main_content.height * scale)

    resized_content = main_content.resize((target_card_w, target_card_h), Image.Resampling.LANCZOS)

    card_w = target_card_w
    card_h = target_card_h
    shadow_offset_x = 18
    shadow_offset_y = 22
    shadow_color = (198, 113, 57, 255)  # #c67139 (tokens.css: --color-accent)
    border_color = (32, 22, 14, 255)  # #20160e (tokens.css: --color-text-primary 近傍)
    border_width = 4
    corner_radius = 24

    pad = 50
    card_canvas_w = card_w + pad * 2 + shadow_offset_x + 10
    card_canvas_h = card_h + pad * 2 + shadow_offset_y + 10
    card_img = Image.new("RGBA", (card_canvas_w, card_canvas_h), (0, 0, 0, 0))
    card_draw = ImageDraw.Draw(card_img)

    # (1) ソリッドシャドウ描画
    card_draw.rounded_rectangle(
        [
            (pad + shadow_offset_x, pad + shadow_offset_y),
            (pad + card_w + shadow_offset_x, pad + card_h + shadow_offset_y),
        ],
        radius=corner_radius,
        fill=shadow_color,
    )

    # (2) カード本体マスク描画 & コンテンツ貼り付け
    mask = Image.new("L", (card_w, card_h), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle([(0, 0), (card_w, card_h)], radius=corner_radius, fill=255)

    card_body = Image.new("RGBA", (card_w, card_h), (245, 234, 216, 255))
    card_body.paste(resized_content, (0, 0))
    card_body.putalpha(mask)

    card_img.paste(card_body, (pad, pad), card_body)

    # (3) ボーダー描画
    card_draw.rounded_rectangle(
        [(pad, pad), (pad + card_w, pad + card_h)], radius=corner_radius, outline=border_color, width=border_width
    )

    # 5. 反時計回りに -2.988 度回転
    rotated_card = card_img.rotate(2.988, resample=Image.Resampling.BICUBIC, expand=True)

    # 6. 配置位置の精密計算 (元の 00_cover.png の Top-Left: (1441, 217) に完全一致)
    target_tl_x = 1441
    target_tl_y = 217

    rot_arr = np.array(rotated_card)
    rot_dark = (rot_arr[:, :, 0] < 50) & (rot_arr[:, :, 1] < 45) & (rot_arr[:, :, 2] < 35)
    ys, xs = np.where(rot_dark)
    min_x = xs.min()
    min_y_at_min_x = ys[xs == min_x].min()

    paste_x = int(round(target_tl_x - min_x))
    paste_y = int(round(target_tl_y - min_y_at_min_x))

    canvas.paste(rotated_card, (paste_x, paste_y), rotated_card)

    # RGB 形式（2560x1340, note 推奨フォーマット）に変換して保存
    final_img = canvas.convert("RGB")
    final_img.save(output_path, quality=95, optimize=True)
    print(f"Successfully updated {output_path} (size: {final_img.size}, mode: {final_img.mode})")


if __name__ == "__main__":
    generate_cover("docs/note/images/00_cover.png")
