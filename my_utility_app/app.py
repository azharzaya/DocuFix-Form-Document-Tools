from flask import Flask, request, send_file, render_template
from werkzeug.utils import secure_filename
from PIL import Image, ImageColor
from rembg import remove
from PyPDF2 import PdfMerger
from pdf2docx import Converter
import io
import os
import tempfile

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024 

@app.route('/')
def index():
    return render_template('index.html')

# --- Helper Function for Units ---
def convert_to_pixels(val, unit, dpi=300):
    val = float(val)
    if unit == 'cm':
        return int((val / 2.54) * dpi)
    elif unit == 'inch':
        return int(val * dpi)
    return int(val) # default is px

# --- 1. IMAGE RESIZER & PAN CARD TOOL ---
@app.route('/api/resize', methods=['POST'])
def resize_image():
    if 'image' not in request.files:
        return "No image uploaded", 400
    
    file = request.files['image']
    unit = request.form.get('unit', 'px')
    
    # Handle auto PAN Card Presets
    preset = request.form.get('preset')
    if preset == 'pan_photo':
        width, height = 213, 213 # Official NSDL/UTIITSL size at 300DPI
    elif preset == 'pan_sig':
        width, height = 400, 200 # Standard approx for 2x4.5cm at 300DPI
    else:
        width = convert_to_pixels(request.form.get('width', 800), unit)
        height = convert_to_pixels(request.form.get('height', 600), unit)
    
    try:
        img = Image.open(file.stream)
        img = img.resize((width, height), Image.Resampling.LANCZOS)
        
        img_io = io.BytesIO()
        # PAN cards specifically require JPEG
        format_to_save = 'JPEG' if preset else (img.format if img.format else 'JPEG')
        
        # Convert RGBA to RGB if saving as JPEG
        if format_to_save == 'JPEG' and img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')
            
        img.save(img_io, format=format_to_save, quality=90, dpi=(300, 300))
        img_io.seek(0)
        
        return send_file(img_io, mimetype=f'image/{format_to_save.lower()}', as_attachment=True, download_name=f"resized_{file.filename}")
    except Exception as e:
        return str(e), 500

# --- 2. ADVANCED BACKGROUND REMOVAL ---
@app.route('/api/remove-bg', methods=['POST'])
def remove_background():
    if 'image' not in request.files:
        return "No image uploaded", 400
    
    file = request.files['image']
    bg_color = request.form.get('bg_color')
    bg_image_file = request.files.get('bg_image')
    
    try:
        input_image = file.read()
        output_image_data = remove(input_image) 
        
        img = Image.open(io.BytesIO(output_image_data)).convert("RGBA")
        
        # Apply new background if requested
        if bg_image_file and bg_image_file.filename != '':
            bg_img = Image.open(bg_image_file.stream).convert("RGBA")
            bg_img = bg_img.resize(img.size, Image.Resampling.LANCZOS)
            bg_img.paste(img, (0, 0), img)
            img = bg_img.convert("RGB")
            ext, mime = 'JPEG', 'image/jpeg'
        elif bg_color and bg_color != '#00000000': # Ignore if transparent
            try:
                rgb_color = ImageColor.getrgb(bg_color)
                bg = Image.new("RGBA", img.size, rgb_color)
                bg.paste(img, (0, 0), img)
                img = bg.convert("RGB")
                ext, mime = 'JPEG', 'image/jpeg'
            except ValueError:
                ext, mime = 'PNG', 'image/png'
        else:
            ext, mime = 'PNG', 'image/png'

        img_io = io.BytesIO()
        img.save(img_io, format=ext)
        img_io.seek(0)
        
        return send_file(img_io, mimetype=mime, as_attachment=True, download_name=f"processed_{file.filename}")
    except Exception as e:
        return str(e), 500

# --- 3. DOCUMENT CONVERSIONS ---
@app.route('/api/jpg-to-pdf', methods=['POST'])
def jpg_to_pdf():
    files = request.files.getlist('images')
    if not files: return "No images", 400
    try:
        image_list = []
        for file in files:
            img = Image.open(file.stream).convert('RGB')
            image_list.append(img)
            
        pdf_io = io.BytesIO()
        image_list[0].save(pdf_io, format='PDF', save_all=True, append_images=image_list[1:])
        pdf_io.seek(0)
        return send_file(pdf_io, mimetype='application/pdf', as_attachment=True, download_name="converted.pdf")
    except Exception as e:
        return str(e), 500

@app.route('/api/pdf-to-doc', methods=['POST'])
def pdf_to_doc():
    if 'pdf' not in request.files: return "No PDF", 400
    pdf_file = request.files['pdf']
    
    # pdf2docx requires physical files, so we use temp files
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_pdf:
        pdf_file.save(temp_pdf.name)
        temp_pdf_path = temp_pdf.name
        
    temp_docx_path = temp_pdf_path.replace('.pdf', '.docx')
    
    try:
        cv = Converter(temp_pdf_path)
        cv.convert(temp_docx_path)
        cv.close()
        
        return_data = io.BytesIO()
        with open(temp_docx_path, 'rb') as fo:
            return_data.write(fo.read())
        return_data.seek(0)
        
        os.remove(temp_pdf_path)
        os.remove(temp_docx_path)
        
        return send_file(return_data, mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document', as_attachment=True, download_name="converted.docx")
    except Exception as e:
        return str(e), 500

@app.route('/api/merge-pdf', methods=['POST'])
def merge_pdfs():
    files = request.files.getlist('pdfs')
    if len(files) < 2: return "Need 2+ PDFs", 400
    try:
        merger = PdfMerger()
        for pdf in files: merger.append(pdf)
        pdf_io = io.BytesIO()
        merger.write(pdf_io)
        merger.close()
        pdf_io.seek(0)
        return send_file(pdf_io, mimetype='application/pdf', as_attachment=True, download_name="merged.pdf")
    except Exception as e:
        return str(e), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)