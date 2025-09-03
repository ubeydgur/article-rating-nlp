from .models import IlgiAlani, Hakem, HakemAtama
import fitz, os, spacy, re, base64, io, cv2, numpy as np
from django.conf import settings
from collections import Counter
from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes
from PIL import Image, ImageFilter
from io import BytesIO

nlp = spacy.load("en_core_web_trf")
AES_KEY = b'16byteslongkey!!'

def pad(text):
    padding_len = 16 - (len(text.encode('utf-8')) % 16)
    return text + chr(padding_len) * padding_len

def unpad(text):
    return text[:-ord(text[-1])]

def encrypt_text_aes(plain_text):
    cipher = AES.new(AES_KEY, AES.MODE_CBC)
    ct_bytes = cipher.encrypt(pad(plain_text).encode('utf-8'))
    iv = base64.b64encode(cipher.iv).decode('utf-8')
    ct = base64.b64encode(ct_bytes).decode('utf-8')
    return f"{iv}:{ct}"

def decrypt_text_aes(encrypted_text):
    iv, ct = encrypted_text.split(":")
    iv = base64.b64decode(iv)
    ct = base64.b64decode(ct)
    cipher = AES.new(AES_KEY, AES.MODE_CBC, iv)
    return unpad(cipher.decrypt(ct).decode('utf-8'))

def belirle_makale_alanlari_nlp(text):
    keywords = extract_keywords_with_nlp(text)
    ilgi_alani_etiketleri = {
        'AI': ['deep learning', 'machine', 'neural', 'nlp', 'algorithm', 'recognition', 'ai', 'cnn', 'lstm', 'svm', 'transformer', 'bert', 'model'],
        'HCI': ['user', 'emotion', 'interface', 'stress', 'arousal', 'reaction', 'signal', 'eeg', 'experiment'],
        'BIGDATA': ['data', 'analysis', 'dataset', 'visualization', 'streaming', 'bigdata', 'feature', 'dimensionality'],
        'SECURITY': ['security', 'blockchain', 'encryption', 'attack', 'cyber', 'authentication'],
        'NETWORK': ['network', 'protocol', 'communication', '5g', 'iot']
    }
    sayac = {alan: sum(1 for k in keywords if any(tag in k for tag in kelimeler)) for alan, kelimeler in ilgi_alani_etiketleri.items()}
    en_yuksek = max(sayac.values())
    return IlgiAlani.objects.filter(kategori=max(sayac, key=sayac.get)) if en_yuksek > 0 else []


def extract_text_from_pdf(pdf_path):
    full_path = os.path.join(settings.MEDIA_ROOT, pdf_path)
    doc = fitz.open(full_path)
    text = ""
    for page in doc:
        text += page.get_text("text")
    doc.close()
    return text

def extract_keywords_with_nlp(text, max_keywords=30):
    doc = nlp(text)
    keywords = []

    for token in doc:
        if token.pos_ in ['NOUN', 'PROPN'] and not token.is_stop and len(token.text) > 2:
            keywords.append(token.lemma_.lower())

    # En sık geçen max_keywords kelimeyi al
    most_common = Counter(keywords).most_common(max_keywords)
    return [word for word, freq in most_common]

def pixmap_to_base64(pix):
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    buffered = BytesIO()
    img.save(buffered, format="PNG")
    return base64.b64encode(buffered.getvalue()).decode()

def blur_image(pix):
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    blurred = img.filter(ImageFilter.GaussianBlur(radius=8))
    return blurred

def hakem_atama(makale):
    uygun_hakemler = Hakem.objects.filter(ilgi_alanlari__in=makale.alanlar.all()).distinct()

    if uygun_hakemler.exists():
        en_uygun_hakem = uygun_hakemler.order_by('?').first()  # Rastgele uygun hakemi seç
        HakemAtama.objects.create(makale=makale, hakem=en_uygun_hakem)
        return en_uygun_hakem.kullanici.username
    return None

def blur_author_images_after_references(doc, page_number, encrypted_names_dict, makale_id, y_start=0):
   
    page = doc.load_page(page_number)
    page_height = page.rect.height

    zoom = 2
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat)

    # RGB formatındaki veriyi doğrudan al
    mode = "RGB" if pix.alpha == 0 else "RGBA"
    pil_image = Image.frombytes(mode, [pix.width, pix.height], pix.samples)

    # OpenCV uyumlu hale getir
    cv_img = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)


    if cv_img is None:
        return encrypted_names_dict

    gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    h, w = cv_img.shape[:2]
    index = 0

    for contour in contours:
        x, y, bw, bh = cv2.boundingRect(contour)

        if y < int(h * (y_start / page_height)) or bw < 50 or bh < 50:
            continue
        if not (0.6 < bw / bh < 1.7):
            continue

        roi = cv_img[y:y+bh, x:x+bw]

        original_roi = roi.copy()
        blurred_roi = cv2.GaussianBlur(roi, (23, 23), 30)

        img_io = io.BytesIO()
        Image.fromarray(blurred_roi).save(img_io, format="PNG")
        img_io.seek(0)

        rect = fitz.Rect(x / zoom, y / zoom, (x + bw) / zoom, (y + bh) / zoom)
        page.insert_image(rect, stream=img_io.read(), keep_proportion=False)

        # 📦 Orijinal vesikalığı kaydet
        filename = f"{makale_id}_p{page_number}_{index}.png"
        save_path = os.path.join(settings.MEDIA_ROOT, "original_images", filename)
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        Image.fromarray(cv2.cvtColor(original_roi, cv2.COLOR_BGR2RGB)).save(save_path)

        # 🔐 Metadata olarak AES şifreli kayıt
        encrypted_names_dict[f"image_p{page_number}_{index}"] = {
            "type": "image",
            "page": page_number,
            "position": [rect.tl.x, rect.tl.y],
            "size": [rect.width, rect.height],
            "original_image_path": encrypt_text_aes(filename),
            "blurred": True
        }

        index += 1

    return encrypted_names_dict

def anonymize_names_in_pdf(input_pdf_path, output_relative_path, encrypted_names_dict, secilen_turler=None, makale_id=None):
    import os
    import re
    import fitz
    from django.conf import settings
    from .utils import encrypt_text_aes, blur_author_images_after_references, nlp

    if secilen_turler is None:
        secilen_turler = ["PERSON", "ORG", "EMAIL", "GPE", "LOC", "IMAGE"]

    input_path = os.path.join(settings.MEDIA_ROOT, input_pdf_path)
    output_path = os.path.join(settings.MEDIA_ROOT, output_relative_path)
    doc = fitz.open(input_path)

    stop_at_reference = ["references", "kaynakça", "referanslar", "bibliography"]
    skip_sections = ["introduction", "related work", "acknowledgement", "teşekkür"]

    reference_page_index = -1
    reference_y_position = None
    reference_found = False
    in_skipped_section = False
    in_references = False
    reference_done = False

    # REFERANS BAŞLIĞI BUL
    for page_number, page in enumerate(doc):
        blocks = page.get_text("blocks")
        sorted_blocks = sorted(blocks, key=lambda b: (b[1], b[0]))
        for block in sorted_blocks:
            text = block[4].strip().lower()
            if not reference_found and any(text.startswith(k) for k in stop_at_reference):
                reference_page_index = page_number
                reference_y_position = block[1]
                reference_found = True
                break
        if reference_found:
            break

    # METİN ANONİMLEŞTİRME
    for page_number, page in enumerate(doc):
        blocks = page.get_text("blocks")
        sorted_blocks = sorted(blocks, key=lambda b: (b[1], b[0]))

        for block in sorted_blocks:
            text = block[4].strip()
            lowered = text.lower()

            if any(lowered.startswith(k) for k in stop_at_reference):
                in_references = True
                continue

            if in_references:
                if re.match(r"^\[\d+\]", text):
                    continue
                elif len(text.split()) > 10:
                    reference_done = True

            if any(section in lowered for section in skip_sections):
                in_skipped_section = True
                continue
            if in_skipped_section and not reference_done:
                continue
            if not text:
                continue

            doc_nlp = nlp(text)
            for ent in doc_nlp.ents:
                if ent.label_ in secilen_turler and ent.label_ in ["PERSON", "ORG", "EMAIL", "GPE", "LOC"]:
                    entity_text = ent.text.strip()
                    if not entity_text:
                        continue

                    if ent.label_ == "ORG" and not any(x in entity_text.lower() for x in ["university", "institute", "faculty", "department"]):
                        continue

                    encrypted = encrypt_text_aes(entity_text)

                    # Tüm pozisyonları topla
                    positions = []
                    for occ in page.search_for(entity_text):
                        positions.append({
                            "page": page_number,
                            "x0": occ.x0,
                            "y0": occ.y0,
                            "x1": occ.x1,
                            "y1": occ.y1
                        })

                        # Metni beyaza boyayarak gizle
                        page.draw_rect(occ, color=(1, 1, 1), fill=(1, 1, 1))

                    # 🔐 Şifreli veri + koordinatlar olarak kaydet
                    if positions:
                        encrypted_names_dict[entity_text] = {
                            "type": "text",
                            "encrypted": encrypted,
                            "positions": positions
                        }

            # REGEX destekli ek tarama
            regex_patterns = [
                r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
                r"(university|institute|faculty|department) of [\w\s]+",
                r"\baddress[:\- ]?.*", r"\bemail[:\- ]?.*", r"\bphone[:\- ]?.*"
            ]
            for pattern in regex_patterns:
                for match in re.findall(pattern, text, flags=re.IGNORECASE):
                    match = match.strip()
                    if match in encrypted_names_dict:
                        continue
                    encrypted = encrypt_text_aes(match)
                    encrypted_names_dict[match] = {
                        "type": "text",
                        "encrypted": encrypted,
                        "positions": []
                    }
                    for occ in page.search_for(match):
                        page.draw_rect(occ, fill=(1, 1, 1))
                        encrypted_names_dict[match]["positions"].append({
                            "page": page_number,
                            "x0": occ.x0,
                            "y0": occ.y0,
                            "x1": occ.x1,
                            "y1": occ.y1
                        })

    # VESİKALIK BLURLAMA
    if "IMAGE" in secilen_turler and reference_page_index != -1:
        for i in range(reference_page_index, len(doc)):
            blur_author_images_after_references(
                doc, i, encrypted_names_dict, makale_id,
                y_start=reference_y_position + (doc[i].rect.height / 3) if i == reference_page_index else 0
            )

    doc.save(output_path)
    doc.close()
    return output_relative_path

def decrypt_anonymized_pdf(anon_pdf_path, output_path, encrypted_data, media_root, original_images_folder):
    doc = fitz.open(anon_pdf_path)
    
    for page_number in range(len(doc)):
        page = doc[page_number]
        
        for key, val in encrypted_data.items():
            if isinstance(val, dict) and val.get("type") == "image":
                if val["page"] != page_number:
                    continue

                # Görsel koordinatları
                x, y = val["position"]
                width, height = val["size"]
                rect = fitz.Rect(x, y, x + width, y + height)

                original_name = decrypt_text_aes(val["original_image_path"])
                image_path = os.path.join(media_root, original_images_folder, original_name)
                if not os.path.exists(image_path):
                    continue

                with open(image_path, "rb") as img_file:
                    img_bytes = img_file.read()

                page.insert_image(rect, stream=img_bytes, keep_proportion=False)

            elif isinstance(val, dict) and val.get("type") == "text":
                try:
                    decrypted_text = decrypt_text_aes(val["encrypted"])

                    # 🔁 Önceki yazılan metin ve y-koordinatı takibi
                    previous_text = None
                    previous_y = None
                    previous_x = None
                    for pos in val.get("positions", []):
                        if pos["page"] != page_number:
                            continue

                        # Pozisyonu biraz büyüt (taşmalar için)
                        rect = fitz.Rect(pos["x0"] - 1, pos["y0"], pos["x1"] + 1, pos["y1"])
                        y0 = round(rect.y0, 2)
                        x0 = round(rect.x0, 2)
                        # 🔁 Aynı metin art arda ve aynı satıra yakınsa yazma
                        if decrypted_text == previous_text and previous_y is not None and abs(y0 - previous_y) <= 150 and abs(x0 -previous_x) <=150:
                            continue

                        # ⚠️ Yeni metni yazmak üzere önce güncelle
                        previous_text = decrypted_text
                        previous_y = y0
                        previous_x = x0
                        # Alanı beyaza boya
                        page.draw_rect(rect, fill=(1, 1, 1), overlay=True)

                        # Yazı yüksekliğini ortalamak için y1'den biraz düş
                        y = rect.y1 - 1

                        # Metni sola hizalı ekle
                        page.insert_text(
                            fitz.Point(rect.x0, y),
                            decrypted_text,
                            fontsize=9,
                            fontname="helv",
                            color=(0, 0, 0)
                        )

                except Exception:
                    continue


    doc.save(output_path)
    doc.close()
    return output_path
