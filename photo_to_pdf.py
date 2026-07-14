import os
from PIL import Image, ImageOps
import argparse

def create_photo_pdf(image_folder, output_pdf, page_width=3508, page_height=2480):
    """
    Creates a highly professional, justified landscape PDF.
    Images are scaled proportionally to form perfectly aligned rows,
    matching the exact "masonry/justified" layout of premium photo albums.
    """
    # Spacing and margins
    margin_x = 150
    margin_y = 150
    spacing = 40
    
    # A single, very thin, elegant black border (no clunky multiple borders)
    border_thickness = 2 
    
    valid_extensions = {".jpg", ".jpeg", ".png", ".bmp"}
    image_files = [
        os.path.join(image_folder, f) 
        for f in os.listdir(image_folder) 
        if os.path.splitext(f)[1].lower() in valid_extensions
    ]
    
    if not image_files:
        print("No images found in the specified folder.")
        return

    pages = []
    
    # Process images in batches of up to 4
    for i in range(0, len(image_files), 4):
        batch_files = image_files[i:i+4]
        
        # Create a blank white page
        page = Image.new('RGB', (page_width, page_height), 'white')
        
        # Load images for this page
        images = []
        for path in batch_files:
            try:
                img = Image.open(path).convert('RGB')
                images.append(img)
            except Exception as e:
                print(f"Error loading {path}: {e}")
                
        n = len(images)
        if n == 0: 
            continue
            
        # Partition the images into justified rows
        if n == 4:
            rows = [images[0:2], images[2:4]]
        elif n == 3:
            rows = [images[0:2], images[2:3]]
        elif n == 2:
            rows = [images[0:2]]
        elif n == 1:
            rows = [images[0:1]]
            
        max_w = page_width - 2 * margin_x
        max_h = page_height - 2 * margin_y
        
        row_heights = []
        # Calculate the mathematical height required for each row so that
        # the sum of the widths of its images exactly matches the page width.
        for row in rows:
            sum_ratios = sum(img.width / img.height for img in row)
            h = (max_w - (len(row) - 1) * spacing) / sum_ratios
            row_heights.append(h)
            
        total_h = sum(row_heights) + (len(rows) - 1) * spacing
        
        # If the perfectly justified rows are too tall for the page,
        # we scale the entire formation down proportionately.
        scale = 1.0
        if total_h > max_h:
            scale = max_h / total_h
            
        # Center the block vertically on the page
        current_y = margin_y + (max_h - total_h * scale) / 2
        
        for r_idx, row in enumerate(rows):
            h = row_heights[r_idx] * scale
            # Center the row horizontally (only relevant if we scaled down)
            current_x = margin_x + (max_w - max_w * scale) / 2
            row_spacing = spacing * scale
            
            for img in row:
                ratio = img.width / img.height
                w = h * ratio
                
                # Calculate dimensions leaving space for the border
                final_w = int(w)
                final_h = int(h)
                
                inner_w = max(1, final_w - 2 * border_thickness)
                inner_h = max(1, final_h - 2 * border_thickness)
                
                # High-quality resize
                resized_img = img.resize((inner_w, inner_h), Image.Resampling.LANCZOS)
                
                # Add the sleek border
                bordered_img = ImageOps.expand(resized_img, border=border_thickness, fill='black')
                
                # Paste the perfectly fitted image onto the page
                page.paste(bordered_img, (int(current_x), int(current_y)))
                
                current_x += w + row_spacing
                
            current_y += h + row_spacing
            
        pages.append(page)
        
    if pages:
        # Save as PDF
        pages[0].save(
            output_pdf,
            "PDF",
            resolution=300.0,
            save_all=True,
            append_images=pages[1:]
        )
        print(f"Successfully created a perfectly justified PDF with {len(pages)} pages: {output_pdf}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate a beautiful justified photo collage PDF.")
    parser.add_argument("image_folder", help="Folder containing the photos")
    parser.add_argument("output_pdf", help="Output PDF file name (e.g. album.pdf)")
    args = parser.parse_args()
    
    create_photo_pdf(args.image_folder, args.output_pdf)
